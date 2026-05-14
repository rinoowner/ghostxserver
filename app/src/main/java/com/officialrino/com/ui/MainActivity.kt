package com.officialrino.com.ui

import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import android.net.VpnService
import java.util.Locale
import com.officialrino.com.R

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var sharedPrefs: SharedPreferences
    
    private var handler = Handler(Looper.getMainLooper())
    private var updateRunnable: Runnable? = null

    companion object {
        private const val PREFS_NAME = "OfficialrinoPrefs"
        private const val SAVED_KEY = "saved_key"
        private const val SAVED_EXPIRY = "saved_expiry"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        setContentView(R.layout.activity_main)

        // Make app full screen
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.hide(android.view.WindowInsets.Type.statusBars() or android.view.WindowInsets.Type.navigationBars())
        } else {
            @Suppress("DEPRECATION")
            window.setFlags(
                android.view.WindowManager.LayoutParams.FLAG_FULLSCREEN,
                android.view.WindowManager.LayoutParams.FLAG_FULLSCREEN
            )
        }

        sharedPrefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        if (intent.getBooleanExtra("REQUEST_VPN", false)) {
            requestVpnPermission()
        }

        webView = findViewById(R.id.webView)
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.cacheMode = android.webkit.WebSettings.LOAD_DEFAULT
        
        // Add Javascript Interface
        webView.addJavascriptInterface(WebAppInterface(this), "Android")

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                // Inject Key and start countdown after page loads
                val savedKey = sharedPrefs.getString(SAVED_KEY, "N/A")
                webView.evaluateJavascript("document.getElementById('key_display').innerText = '$savedKey'", null)
                startExpiryCountdown()
            }
        }

        val decryptedHtml = AppAssets.decrypt(AppAssets.DASHBOARD_HTML)
        webView.loadDataWithBaseURL("file:///android_asset/", decryptedHtml, "text/html", "UTF-8", null)
    }

    private fun startExpiryCountdown() {
        val expiryTime = sharedPrefs.getLong(SAVED_EXPIRY, 0L)
        
        updateRunnable = object : Runnable {
            override fun run() {
                val currentTime = System.currentTimeMillis()
                val diff = expiryTime - currentTime
                
                if (diff > 0) {
                    val hours = diff / (1000 * 60 * 60)
                    val minutes = (diff / (1000 * 60)) % 60
                    val seconds = (diff / 1000) % 60
                    
                    val formattedTime = String.format(Locale.getDefault(), "%02d:%02d:%02d", hours, minutes, seconds)
                    
                    // Update WebView
                    webView.evaluateJavascript("document.getElementById('expiry_display').innerText = '$formattedTime'", null)
                    
                    handler.postDelayed(this, 1000)
                } else {
                    webView.evaluateJavascript("document.getElementById('expiry_display').innerText = 'EXPIRED'", null)
                    webView.evaluateJavascript("document.getElementById('expiry_display').style.color = 'red'", null)
                }
            }
        }
        handler.post(updateRunnable!!)
    }

    fun toggleFloatingWindow() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !android.provider.Settings.canDrawOverlays(this)) {
            val intent = Intent(
                android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                android.net.Uri.parse("package:$packageName")
            )
            startActivity(intent)
            Toast.makeText(this, "GRANT OVERLAY ACCESS", Toast.LENGTH_SHORT).show()
        } else {
            val intent = Intent(this, FloatingWindowService::class.java)
            startService(intent)
        }
    }

    private fun requestVpnPermission() {
        val vpnIntent = VpnService.prepare(this)
        if (vpnIntent != null) {
            startActivityForResult(vpnIntent, 0)
        } else {
            Toast.makeText(this, "VPN Permission already granted", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 0) {
            if (resultCode == RESULT_OK) {
                Toast.makeText(this, "VPN Permission Granted!", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "VPN Permission Denied!", Toast.LENGTH_SHORT).show()
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra("REQUEST_VPN", false)) {
            requestVpnPermission()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        updateRunnable?.let { handler.removeCallbacks(it) }
        // Stop floating window when app is closed
        val intent = Intent(this, FloatingWindowService::class.java)
        stopService(intent)
    }

    // Javascript Interface Class
    class WebAppInterface(private val activity: MainActivity) {
        @JavascriptInterface
        fun launchController() {
            activity.runOnUiThread {
                activity.toggleFloatingWindow()
            }
        }
    }
}
package com.officialrino.com.ui

import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.ContextCompat
import com.officialrino.com.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class FloatingWindowService : Service() {

    private lateinit var windowManager: WindowManager
    private lateinit var floatingView: View
    private lateinit var params: WindowManager.LayoutParams
    
    private lateinit var executeButton: Button
    private lateinit var statusText: TextView
    private lateinit var contentLayout: LinearLayout
    private lateinit var minimizedLayout: View
    private lateinit var displayIp: TextView
    private lateinit var displayPort: TextView
    private lateinit var attackTimeLabel: TextView
    private lateinit var durationSeekBar: SeekBar
    private lateinit var activeSlotsText: TextView
    
    private var isMinimized = false
    private var selectedDuration = 180
    private val serviceScope = CoroutineScope(Dispatchers.Main + Job())
    
    private var isSearching = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        floatingView = LayoutInflater.from(this).inflate(R.layout.floating_window, null)

        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val density = resources.displayMetrics.density
        
        // ========== BAN FIX MEOW x095e69 3D ==========
        params = WindowManager.LayoutParams(
            (300 * density).toInt(),
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
            PixelFormat.TRANSLUCENT
        )
        // =========================================

        params.gravity = Gravity.TOP or Gravity.START
        params.x = 100
        params.y = 100

        // Add cutout mode for Android 10+ (BAN x08e675 FIX)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            params.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_NEVER
        }

        windowManager.addView(floatingView, params)

        // Initialize Views
        executeButton = floatingView.findViewById(R.id.float_execute_button)
        statusText = floatingView.findViewById(R.id.float_status_text)
        contentLayout = floatingView.findViewById(R.id.content_layout)
        minimizedLayout = floatingView.findViewById(R.id.minimized_layout)
        minimizedLayout.outlineProvider = android.view.ViewOutlineProvider.BACKGROUND
        displayIp = floatingView.findViewById(R.id.display_ip)
        displayPort = floatingView.findViewById(R.id.display_port)
        attackTimeLabel = floatingView.findViewById(R.id.attack_time_label)
        durationSeekBar = floatingView.findViewById(R.id.duration_seekbar)
        activeSlotsText = floatingView.findViewById(R.id.active_slots_text)
        val btnGetIpPort = floatingView.findViewById<Button>(R.id.btn_get_ip_port)
        val closeButton = floatingView.findViewById<ImageView>(R.id.close_button)

        // Drag functionality
        val dragTouchListener = object : View.OnTouchListener {
            private var initialX: Int = 0
            private var initialY: Int = 0
            private var initialTouchX: Float = 0f
            private var initialTouchY: Float = 0f
            private var isMoved = false

            override fun onTouch(v: View, event: MotionEvent): Boolean {
                when (event.action) {
                    MotionEvent.ACTION_DOWN -> {
                        initialX = params.x
                        initialY = params.y
                        initialTouchX = event.rawX
                        initialTouchY = event.rawY
                        isMoved = false
                        return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        val dx = (event.rawX - initialTouchX).toInt()
                        val dy = (event.rawY - initialTouchY).toInt()
                        
                        if (Math.abs(dx) > 10 || Math.abs(dy) > 10) {
                            isMoved = true
                            params.x = initialX + dx
                            params.y = initialY + dy
                            windowManager.updateViewLayout(floatingView, params)
                        }
                        return true
                    }
                    MotionEvent.ACTION_UP -> {
                        if (!isMoved) {
                            v.performClick()
                        }
                        return true
                    }
                }
                return false
            }
        }
        
        floatingView.findViewById<View>(R.id.header_layout).setOnTouchListener(dragTouchListener)
        minimizedLayout.setOnTouchListener(dragTouchListener)

        // X Button now minimizes
        closeButton.setOnClickListener {
            vibrate(30)
            applyClickAnimation(it)
            toggleMinimize(true)
            showGlobalToast("WINDOW MINIMIZED")
        }

        minimizedLayout.setOnClickListener {
            vibrate(30)
            applyClickAnimation(it)
            toggleMinimize(false)
            showGlobalToast("WINDOW MAXIMIZED")
        }

        executeButton.setOnClickListener {
            vibrate(50)
            applyClickAnimation(it)
            performSmartLaunch()
        }
        
        btnGetIpPort.setOnClickListener {
            vibrate(50)
            applyClickAnimation(it)
            
            NetworkCaptureService.clearCaptured()
            isSearching = true
            statusText.text = "SEARCHING..."
            displayIp.text = "IP: "
            displayPort.text = "PORT: "
            showGlobalToast("SEARCHING FOR TARGET...")

            val vpnIntent = android.net.VpnService.prepare(this)
            if (vpnIntent != null) {
                val intent = Intent(this, MainActivity::class.java)
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                intent.putExtra("REQUEST_VPN", true)
                startActivity(intent)
                showGlobalToast("Please grant VPN permission in the app")
            } else {
                val intent = Intent(this, NetworkCaptureService::class.java)
                ContextCompat.startForegroundService(this, intent)
            }
        }

        durationSeekBar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                val actualDuration = progress * 60
                selectedDuration = actualDuration
                attackTimeLabel.text = "Attack Time: ${actualDuration}s"
                if (fromUser) {
                    vibrate(30)
                }
            }
            override fun onStartTrackingTouch(seekBar: SeekBar?) {}
            override fun onStopTrackingTouch(seekBar: SeekBar?) {
                showGlobalToast("DURATION SET TO ${selectedDuration}s")
            }
        })

        startSyncLoop()
    }

    private fun toggleMinimize(minimize: Boolean) {
        isMinimized = minimize
        val density = resources.displayMetrics.density
        if (minimize) {
            contentLayout.visibility = View.GONE
            minimizedLayout.visibility = View.VISIBLE
            params.width = (56 * density).toInt()
            params.height = (56 * density).toInt()
        } else {
            contentLayout.visibility = View.VISIBLE
            minimizedLayout.visibility = View.GONE
            params.width = (300 * density).toInt()
            params.height = WindowManager.LayoutParams.WRAP_CONTENT
        }
        windowManager.updateViewLayout(floatingView, params)
    }

    private fun performSmartLaunch() {
        val ip = NetworkCaptureService.getCapturedIp()
        val port = NetworkCaptureService.getCapturedPort()

        if (ip == null || port == null) {
            showGlobalToast("WAITING FOR TARGET...")
            return
        }

        val sharedPrefs = getSharedPreferences("OfficialrinoPrefs", Context.MODE_PRIVATE)
        val key = sharedPrefs.getString("saved_key", null) ?: run {
            showGlobalToast("❌ LOGIN REQUIRED")
            return
        }

        executeButton.isEnabled = false
        executeButton.text = "LAUNCHING..."
        showGlobalToast("INITIATING ATTACK...")

        serviceScope.launch {
            val deviceId = ApiClient.getDeviceId(this@FloatingWindowService)
            val result = ApiClient.startAttack(key, deviceId, ip, port, selectedDuration)
            executeButton.isEnabled = true
            executeButton.text = "START ATTACK"
            if (result.success) {
                sharedPrefs.edit()
                    .putLong("last_attack_time", System.currentTimeMillis())
                    .putInt("last_attack_duration", selectedDuration)
                    .apply()
                showGlobalToast("🚀 ATTACK SENT SUCCESSFULLY!")
                vibrate(100)
            } else {
                showGlobalToast("❌ FAILED: ${result.message}")
                if (result.message.contains("Key expired", ignoreCase = true) || result.message.contains("401")) {
                    performLogout()
                }
            }
        }
    }

    private fun performLogout() {
        val sharedPrefs = getSharedPreferences("OfficialrinoPrefs", Context.MODE_PRIVATE)
        sharedPrefs.edit().clear().apply()
        
        showGlobalToast("❌ KEY EXPIRED. LOGGING OUT...")
        
        val intent = Intent(this, LoginActivity::class.java)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
        
        stopSelf()
    }

    private fun stopActiveAttack() {
        val sharedPrefs = getSharedPreferences("OfficialrinoPrefs", Context.MODE_PRIVATE)
        sharedPrefs.edit()
            .putLong("last_attack_time", 0)
            .putInt("last_attack_duration", 0)
            .apply()
        showGlobalToast("🛑 ATTACK STOPPED BY USER")
        attackTimeLabel.text = "Attack Time: 180s"
        durationSeekBar.progress = 180
    }

    private fun startSyncLoop() {
        serviceScope.launch {
            while (true) {
                val ip = NetworkCaptureService.getCapturedIp()
                val port = NetworkCaptureService.getCapturedPort()
                
                val sharedPrefs = getSharedPreferences("OfficialrinoPrefs", Context.MODE_PRIVATE)
                val lastAttackTime = sharedPrefs.getLong("last_attack_time", 0)
                val lastDuration = sharedPrefs.getInt("last_attack_duration", 0)
                val currentTime = System.currentTimeMillis()
                val attackEndTime = lastAttackTime + (lastDuration * 1000L)
                val cooldownEndTime = attackEndTime + (40 * 1000L) // 40 seconds cooldown
                
                if (currentTime < attackEndTime) {
                    val remainingSec = (attackEndTime - currentTime) / 1000
                    
                    executeButton.isEnabled = false
                    executeButton.text = "WAIT ${remainingSec}s"
                    
                    if (ip != null && port != null) {
                        displayIp.text = "IP: $ip"
                        displayPort.text = "PORT: $port"
                    }
                } else if (currentTime < cooldownEndTime) {
                    val remainingCooldownSec = (cooldownEndTime - currentTime) / 1000
                    
                    executeButton.isEnabled = false
                    executeButton.text = "COOLDOWN ${remainingCooldownSec}s"
                    
                    if (ip != null && port != null) {
                        displayIp.text = "IP: $ip"
                        displayPort.text = "PORT: $port"
                    }
                } else {
                    executeButton.isEnabled = true
                    executeButton.text = "START ATTACK"
                    
                    if (isSearching) {
                        if (ip != null && port != null) {
                            isSearching = false
                            statusText.text = "IDLE"
                            displayIp.text = "IP: $ip"
                            displayPort.text = "PORT: $port"
                            showGlobalToast("TARGET ACQUIRED!")
                        } else {
                            statusText.text = "SEARCHING..."
                            displayIp.text = "IP: "
                            displayPort.text = "PORT: "
                        }
                    } else {
                        if (ip != null && port != null) {
                            displayIp.text = "IP: $ip"
                            displayPort.text = "PORT: $port"
                        } else {
                            displayIp.text = "IP: "
                            displayPort.text = "PORT: "
                        }
                    }
                }
                
                kotlinx.coroutines.delay(1000)
            }
        }

        serviceScope.launch {
            while (true) {
                try {
                    val attacksResult = ApiClient.getActiveAttacks()
                    if (attacksResult.success) {
                        updateActiveAttacksUI(attacksResult.attacks)
                    }
                } catch (e: Exception) {
                    // Ignore
                }
                kotlinx.coroutines.delay(5000)
            }
        }
    }

    private fun updateActiveAttacksUI(attacks: List<ApiClient.ActiveAttack>) {
        activeSlotsText.text = "ACTIVE SLOTS: ${attacks.size}/6"
    }

    private fun showGlobalToast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    private fun vibrate(durationMs: Long) {
        val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as android.os.Vibrator
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            vibrator.vibrate(android.os.VibrationEffect.createOneShot(durationMs, android.os.VibrationEffect.DEFAULT_AMPLITUDE))
        } else {
            @Suppress("DEPRECATION")
            vibrator.vibrate(durationMs)
        }
    }

    private fun applyClickAnimation(view: View) {
        view.animate()
            .scaleX(0.95f)
            .scaleY(0.95f)
            .setDuration(100)
            .withEndAction {
                view.animate()
                    .scaleX(1.0f)
                    .scaleY(1.0f)
                    .setDuration(100)
                    .start()
            }
            .start()
    }

    override fun onDestroy() {
        super.onDestroy()
        serviceScope.cancel()
        if (::floatingView.isInitialized) {
            windowManager.removeView(floatingView)
        }
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        stopSelf()
    }
}
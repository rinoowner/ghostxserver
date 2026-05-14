// Modified & Promoted by officialrino
package com.officialrino.com.ui

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.*
import java.io.FileInputStream

class NetworkCaptureService : VpnService() {
    
    private var vpnInterface: ParcelFileDescriptor? = null
    private var isRunning = false
    private var captureJob: Job? = null
    
    companion object {
        private var capturedIp: String? = null
        private var capturedPort: Int? = null
        const val ACTION_STOP_VPN = "com.officialrino.com.STOP_VPN"
        
        fun getCapturedIp(): String? = capturedIp
        fun getCapturedPort(): Int? = capturedPort
        fun clearCaptured() {
            capturedIp = null
            capturedPort = null
        }
    }
    
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP_VPN) {
            stopVpnInternal()
            return START_NOT_STICKY
        }
        
        startForeground(1, createNotification())
        startVpn()
        return START_STICKY
    }
    
    private fun startVpn() {
        isRunning = true
        capturedIp = null
        capturedPort = null
        
        try {
            val builder = Builder()
            builder.setSession("officialrino")
            builder.addAddress("10.0.0.2", 24)
            builder.addRoute("0.0.0.0", 0)
            
            // Critical for internet: Add DNS servers
            builder.addDnsServer("8.8.8.8")
            builder.addDnsServer("1.1.1.1")
            
            builder.setMtu(1400) // Lower MTU can help with stability
            builder.allowBypass() // Allow apps to bypass if they can
            
            // Removed app filtering to support loaders/hacks
            // This will capture traffic from all apps and filter by port

            
            vpnInterface = builder.establish()
            if (vpnInterface != null) {
                startPacketCapture()
                
                // SAFETY: Auto-stop after 10 seconds to restore BGMI internet
                CoroutineScope(Dispatchers.Main).launch {
                    delay(10000)
                    if (isRunning && capturedIp == null) {
                        stopVpnInternal()
                    }
                }
            } else {
                stopSelf()
            }
        } catch (e: Exception) {
            stopSelf()
        }
    }
    
    private fun startPacketCapture() {
        captureJob = CoroutineScope(Dispatchers.IO).launch {
            try {
                val inputStream = FileInputStream(vpnInterface?.fileDescriptor)
                val packet = ByteArray(32768)
                
                while (isRunning && vpnInterface != null) {
                    val length = try { inputStream.read(packet) } catch (e: Exception) { -1 }
                    if (length > 0) {
                        analyzePacket(packet, length)
                        if (capturedIp != null && capturedPort != null) {
                            isRunning = false
                            break
                        }
                    } else if (length == -1) {
                        break
                    }
                }
            } catch (e: Exception) {
            } finally {
                withContext(Dispatchers.Main) {
                    stopVpnInternal()
                }
            }
        }
    }
    
    private fun analyzePacket(packet: ByteArray, length: Int) {
        if (length < 20) return
        val protocol = packet[9].toInt() and 0xFF
        val headerLength = (packet[0].toInt() and 0x0F) * 4
        
        val dstIp = "${packet[16].toInt() and 0xFF}.${packet[17].toInt() and 0xFF}.${packet[18].toInt() and 0xFF}.${packet[19].toInt() and 0xFF}"
        if (dstIp.startsWith("10.") || dstIp == "127.0.0.1") return
        
        if (protocol == 17 && length >= headerLength + 4) {
            val dstPort = ((packet[headerLength + 2].toInt() and 0xFF) shl 8) or (packet[headerLength + 3].toInt() and 0xFF)
            
            // STRICT PORT FILTERING:
            // 1. Must be UDP (protocol 17) - already checked
            // 2. Must be between 10003 and 29999
            // 3. Must not be 17500, 20000, 20001, 20002
            
            if (dstPort < 10003 || dstPort > 29999) return
            if (dstPort == 17500 || dstPort == 20000 || dstPort == 20001 || dstPort == 20002) return

            capturedIp = dstIp
            capturedPort = dstPort
        }
    }
    
    private fun stopVpnInternal() {
        if (!isRunning && vpnInterface == null) return
        
        isRunning = false
        captureJob?.cancel()
        try {
            vpnInterface?.close()
        } catch (e: Exception) {}
        vpnInterface = null
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
        
        sendBroadcast(Intent("com.officialrino.com.VPN_STOPPED"))
        stopSelf()
    }
    
    override fun onDestroy() {
        stopVpnInternal()
        super.onDestroy()
    }
    
    private fun createNotification(): Notification {
        val intent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE)
        
        return NotificationCompat.Builder(this, "officialrino_capture_channel")
            .setContentTitle("🎮 Sniffer Active")
            .setContentText("Internet will restore automatically in 10s.")
            .setSmallIcon(android.R.drawable.ic_menu_share)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }
    
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel("officialrino_capture_channel", "officialrino Capture", NotificationManager.IMPORTANCE_LOW)
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }
}

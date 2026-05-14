// Modified & Promoted by officialrino
package com.officialrino.com.ui

import android.content.Context
import android.provider.Settings
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object ApiClient {
    
    // ========== PRODUCTION URL ==========
    private fun getBaseUrl(): String {
        return "https://ghostfree-production.up.railway.app"

    }
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()
    
    fun getDeviceId(context: Context): String {
        return Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ANDROID_ID
        ) ?: "unknown"
    }
    
    suspend fun verifyKey(key: String): VerificationResult = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
        val baseUrl = getBaseUrl()
        val json = JSONObject().apply {
            put("key", key)
            put("device_id", "apk_device")
        }
        
        val mediaType = "application/json".toMediaTypeOrNull()
        val body = json.toString().toRequestBody(mediaType)
        
        val request = Request.Builder()
            .url("$baseUrl/api/verify-key")
            .post(body)
            .build()
        
        try {
            val response = client.newCall(request).execute()
            val responseBody = response.body?.string() ?: "{}"
            
            if (response.isSuccessful) {
                val jsonResponse = JSONObject(responseBody)
                if (jsonResponse.optBoolean("success")) {
                    VerificationResult(true, "", jsonResponse.optLong("expiry"))
                } else {
                    VerificationResult(false, jsonResponse.optString("reason"), 0)
                }
            } else {
                VerificationResult(false, "Server Error: ${response.code}", 0)
            }
        } catch (e: Exception) {
            VerificationResult(false, "Connection error", 0)
        }
    }
    
    suspend fun startAttack(key: String, ip: String, port: Int, duration: Int): AttackResult = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
        val baseUrl = getBaseUrl()
        val json = JSONObject().apply {
            put("key", key)
            put("device_id", "apk_device")
            put("ip", ip)
            put("port", port)
            put("duration", duration)
        }
        
        val mediaType = "application/json".toMediaTypeOrNull()
        val body = json.toString().toRequestBody(mediaType)
        
        val request = Request.Builder()
            .url("$baseUrl/api/attack")
            .post(body)
            .build()
        
        try {
            val response = client.newCall(request).execute()
            val responseBody = response.body?.string() ?: "{}"
            
            val jsonResponse = try { JSONObject(responseBody) } catch(e: Exception) { JSONObject() }
            
            if (response.isSuccessful) {
                if (jsonResponse.optBoolean("success")) {
                    AttackResult(true, jsonResponse.optString("message"))
                } else {
                    AttackResult(false, jsonResponse.optString("reason"))
                }
            } else {
                val reason = jsonResponse.optString("reason", "Server Error: ${response.code}")
                AttackResult(false, reason)
            }
        } catch (e: Exception) {
            AttackResult(false, "Connection error")
        }
    }

    suspend fun checkUpdate(): UpdateResult = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
        val baseUrl = getBaseUrl()
        val request = Request.Builder()
            .url("$baseUrl/api/check-update")
            .get()
            .build()
            
        try {
            val response = client.newCall(request).execute()
            val responseBody = response.body?.string() ?: "{}"
            
            if (response.isSuccessful) {
                val jsonResponse = JSONObject(responseBody)
                if (jsonResponse.optBoolean("success")) {
                    UpdateResult(
                        true,
                        jsonResponse.optString("latest_version", "1.0"),
                        jsonResponse.optString("download_url", "/static/app-release.apk")
                    )
                } else {
                    UpdateResult(false, "1.0", "")
                }
            } else {
                UpdateResult(false, "1.0", "")
            }
        } catch (e: Exception) {
            UpdateResult(false, "1.0", "")
        }
    }
    suspend fun getActiveAttacks(): ActiveAttacksResult = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
        val baseUrl = getBaseUrl()
        val request = Request.Builder()
            .url("$baseUrl/api/active-attacks")
            .get()
            .build()
            
        try {
            val response = client.newCall(request).execute()
            val responseBody = response.body?.string() ?: "{}"
            
            if (response.isSuccessful) {
                val jsonResponse = JSONObject(responseBody)
                if (jsonResponse.optBoolean("success")) {
                    val attacksArray = jsonResponse.optJSONArray("attacks")
                    val attacksList = mutableListOf<ActiveAttack>()
                    if (attacksArray != null) {
                        for (i in 0 until attacksArray.length()) {
                            val obj = attacksArray.getJSONObject(i)
                            attacksList.add(ActiveAttack(
                                obj.optString("ip"),
                                obj.optInt("port"),
                                obj.optInt("remaining")
                            ))
                        }
                    }
                    ActiveAttacksResult(true, attacksList)
                } else {
                    ActiveAttacksResult(false, emptyList())
                }
            } else {
                ActiveAttacksResult(false, emptyList())
            }
        } catch (e: Exception) {
            ActiveAttacksResult(false, emptyList())
        }
    }
    
    data class ActiveAttack(val ip: String, val port: Int, val remaining: Int)
    data class ActiveAttacksResult(val success: Boolean, val attacks: List<ActiveAttack>)
    data class VerificationResult(val success: Boolean, val reason: String, val expiry: Long)
    data class AttackResult(val success: Boolean, val message: String)
    data class UpdateResult(val success: Boolean, val latestVersion: String, val downloadUrl: String)
}

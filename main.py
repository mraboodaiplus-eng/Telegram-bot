from flask import Flask
import threading
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import os
import time

# --- إعدادات Flask لإرضاء Render ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Alpha Predator Bot is alive!"

def run_flask():
    # Render يعطينا المنفذ عبر متغير بيئة
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# --- إعدادات بوت التليجرام ---
TELEGRAM_TOKEN = "8461790907:AAG1jkTs23WkRjoUsSZ58FsiPHNF3qbFRSs"

def start(update, context):
    """Handler for the /start command."""
    user_name = update.effective_user.first_name
    welcome_message = f"أهلاً بك يا {user_name}!\n\nأنا بوت Alpha Predator، جاهز للعمل."
    update.message.reply_text(welcome_message)
    print(f"User {user_name} started the bot.")

def run_telegram_bot():
    """Starts the Telegram bot."""
    try:
        updater = Updater(TELEGRAM_TOKEN, use_context=True)
        dp = updater.dispatcher

        # إضافة معالج الأوامر
        dp.add_handler(CommandHandler("start", start))

        print("Telegram bot is starting to poll...")
        updater.start_polling()
        updater.idle()
    except Exception as e:
        print(f"An error occurred in the Telegram bot: {e}")

# --- التشغيل الرئيسي ---
if __name__ == "__main__":
    print("Main script started.")
            
    # تشغيل Flask في خيط منفصل
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    print("Flask server started in a separate thread.")

    # تشغيل بوت التليجرام في الخيط الرئيسي
    print("Starting Telegram bot...")
    run_telegram_bot()

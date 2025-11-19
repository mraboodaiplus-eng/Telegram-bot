import asyncio
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
import config
from strategy import OmegaStrategy
from mexc_handler import MEXCHandler
from telegram_bot import TelegramBot

# 1. تهيئة الاستراتيجية
strategy = OmegaStrategy()

# 2. تهيئة بوت التليجرام
bot = TelegramBot(strategy)

# 3. تهيئة معالج MEXC
mexc = MEXCHandler(strategy, bot.send_notification)

# إدارة دورة حياة التطبيق (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    print("🚀 SYSTEM STARTUP: Omega Predator")
    
    # تهيئة وتشغيل بوت التليجرام في الخلفية
    await bot.app.initialize()
    await bot.app.start()
    # استخدام Polling في مهمة منفصلة (Render لا يدعم Webhooks بسهولة دون عنوان IP ثابت أحياناً، الـ Polling أسهل هنا)
    asyncio.create_task(bot.app.updater.start_polling())

    # تشغيل مراقب الأسواق (WebSocket)
    asyncio.create_task(mexc.start_websocket())
    
    yield
    
    # --- Shutdown ---
    print("🛑 SYSTEM SHUTDOWN")
    await bot.app.updater.stop()
    await bot.app.stop()
    await bot.app.shutdown()

# تطبيق FastAPI لإبقاء Render سعيداً (Health Check)
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "active", "system": "Omega Predator"}

if __name__ == "__main__":
    # يتم التشغيل عبر الأمر في Render، لكن هذا للاختبار المحلي
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
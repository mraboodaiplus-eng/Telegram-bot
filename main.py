import asyncio
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

from config import Config
from mexc_handler import MEXCHandler
from strategy import OmegaStrategy
from telegram_bot import OmegaBot

# تهيئة المكونات
mexc_handler = MEXCHandler()
omega_bot = OmegaBot(None) # سيتم ربطه لاحقاً
strategy = OmegaStrategy(mexc_handler, omega_bot)

# ربط الاستراتيجية بالمعالجات
mexc_handler.set_strategy(strategy)
omega_bot.strategy = strategy

@asynccontextmanager
async def lifespan(app: FastAPI):
    """دورة حياة التطبيق: بدء المهام الخلفية"""
    # 1. تشغيل بوت تليجرام
    await omega_bot.start()
    
    # 2. بدء الاستماع للسوق (هنا كان الخطأ وتم تصحيحه)
    # الدالة الصحيحة في ملف mexc_handler هي start_websocket
    asyncio.create_task(mexc_handler.start_websocket())
    
    print("🚀 Omega Predator System: DIAGNOSTIC MODE ACTIVE.")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {
        "status": "alive", 
        "trades": len(strategy.active_trades),
        "monitoring": len(mexc_handler.target_symbols)
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
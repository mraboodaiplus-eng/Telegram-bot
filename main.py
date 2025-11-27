import asyncio
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

from config import Config
from mexc_handler import MEXCHandler
from strategy import OmegaStrategy
from telegram_bot import OmegaBot

mexc_handler = MEXCHandler()
omega_bot = OmegaBot(None)
strategy = OmegaStrategy(mexc_handler, omega_bot)

mexc_handler.set_strategy(strategy)
omega_bot.strategy = strategy

@asynccontextmanager
async def lifespan(app: FastAPI):
    # تشغيل البوت
    await omega_bot.start()
    
    # 🔥 تشغيل النظام المتعدد (Multiplex)
    asyncio.create_task(mexc_handler.start_multiplex_sockets())
    
    print("🚀 Omega Predator: MULTIPLEX ENGINE ENGAGED.")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "alive", "mode": "Multiplex Sharding"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
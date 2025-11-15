import asyncio
import sys
import signal
from datetime import datetime

# استيراد المكونات
from config import WHITELIST_SYMBOLS
from mexc_handler import MEXCHandler
from strategy import StrategyEngine
from telegram_bot import TelegramBot, BOT_STATUS



async def main():
    """
    المنسق الرئيسي لتشغيل جميع مكونات بوت Omega Predator بشكل متزامن.
    تطبيق مبدأ السرعة المطلقة باستخدام asyncio.
    """
    print("Omega Predator: Initializing...")
    
    # 1. تهيئة قائمة انتظار Telegram
    telegram_queue = asyncio.Queue()
    
    # 2. تهيئة معالج MEXC
    # يتم تمرير قائمة انتظار الصفقات إلى MEXCHandler
    mexc_handler = MEXCHandler(strategy_queue=asyncio.Queue())
    
    # 3. تهيئة محرك الاستراتيجية
    # يتم تمرير قائمة انتظار الصفقات من MEXCHandler وقائمة انتظار Telegram إلى StrategyEngine
    strategy_engine = StrategyEngine(
        mexc_handler=mexc_handler,
        telegram_queue=telegram_queue
    )
    
    # يجب تمرير قائمة انتظار الصفقات من mexc_handler إلى strategy_engine
    mexc_handler.strategy_queue = strategy_engine.deal_queue
    
    # 4. تهيئة بوت Telegram
    telegram_bot = TelegramBot(telegram_queue=telegram_queue)
    
    # تحديث حالة البوت
    BOT_STATUS["running"] = True
    BOT_STATUS["start_time"] = datetime.now()
    
    # 5. تجميع المهام المتزامنة
    tasks = [
        asyncio.create_task(mexc_handler.connect_and_listen(), name="MEXC_WS_Listener"),
        asyncio.create_task(strategy_engine.process_deals(), name="Strategy_Processor"),
        asyncio.create_task(telegram_bot.run(), name="Telegram_Bot_Polling"),
        asyncio.create_task(telegram_bot.send_message_task(), name="Telegram_Sender")
    ]
    
    # إضافة مهمة وهمية للحفاظ على الحلقة الرئيسية قيد التشغيل
    tasks.append(asyncio.create_task(asyncio.Future(), name="Keep_Alive"))
    
    print(f"Omega Predator: Starting with {len(WHITELIST_SYMBOLS)} symbols: {', '.join(WHITELIST_SYMBOLS)}")
    
    # 6. تشغيل المهام
    try:
        await asyncio.gather(*tasks, return_exceptions=False)
    except asyncio.CancelledError:
        print("Omega Predator: All tasks cancelled.")
    except Exception as e:
        print(f"FATAL ERROR in main loop: {e}")
    finally:
        # 7. تنظيف الموارد
        print("Omega Predator: Shutting down gracefully...")
        for task in tasks:
            task.cancel()
        await mexc_handler.close()
        await telegram_bot.stop() # إيقاف بوت Telegram بشكل صريح
        print("Omega Predator: Shutdown complete.")



if __name__ == "__main__":
    # تطبيق معالجة الاستثناءات القوية (مبدأ الموثوقية الصارمة)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted by user.")
    except Exception as e:
        print(f"Critical unhandled exception: {e}")
        sys.exit(1)
"""
Omega Predator - Main Module
نقطة الدخول الرئيسية للبوت (Standalone Application)
"""

import asyncio
import os
import sys
import logging
from typing import Optional, Dict, Any

# Telegram Dependencies
from telegram import Update
from telegram.ext import Application

# Local Modules
import config
from trading_logic import TradingEngine
from mexc_handler import MEXCHandler
from websocket_handler import WebSocketHandler
from telegram_handler import TelegramHandler

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# المتغيرات العامة
omega_predator: Optional['OmegaPredator'] = None
telegram_application: Optional[Application] = None

class OmegaPredator:
    """
    البوت الرئيسي - Omega Predator
    تنسيق جميع الوحدات والتحكم في التداول
    """
    
    def __init__(self, application: Application, symbols: list[str]):
        self.symbols = symbols
        self.trading_engine = TradingEngine(symbols)
        self.mexc_handler = MEXCHandler()
        self.telegram_handler = TelegramHandler(application)
        self.websocket_handler: Optional[WebSocketHandler] = None
        self.running = False
        
        # تعيين callback لتحديد المبلغ
        self.telegram_handler.on_amount_set = self.on_amount_set
    
    async def on_trade_received(self, symbol: str, price: float, timestamp: float):
        """
        معالج استقبال صفقة جديدة من WebSocket
        هذه هي الحلقة الساخنة (Hot Loop) - يجب أن تكون سريعة للغاية
        """
        # إضافة السعر للنافذة الزمنية
        self.trading_engine.add_price(symbol, price, timestamp)
        
        # فحص شرط الشراء
        if self.trading_engine.check_buy_condition(symbol, price, timestamp):
            # تنفيذ الشراء فورًا - لا تأخير
            asyncio.create_task(self.execute_buy(symbol, price))
        
        # فحص شرط البيع (إذا كان لدينا صفقة مفتوحة)
        elif self.trading_engine.check_sell_condition(symbol, price):
            # تنفيذ البيع فورًا - لا تأخير
            asyncio.create_task(self.execute_sell(symbol, price))
    
    async def execute_buy(self, symbol: str, price: float):
        """تنفيذ أمر شراء فوري"""
        try:
            # ... (منطق التنفيذ كما هو)
            order = await self.mexc_handler.market_buy(symbol, config.TRADE_AMOUNT_USD)
            
            if order:
                executed_qty = float(order.get('executedQty', 0))
                executed_price = float(order.get('price', price))
                
                self.trading_engine.open_position(symbol, executed_price, executed_qty)
                
                await self.telegram_handler.notify_buy(
                    symbol, 
                    executed_price, 
                    executed_qty, 
                    config.TRADE_AMOUNT_USD
                )
            else:
                await self.telegram_handler.notify_error(
                    f"فشل تنفيذ أمر شراء {symbol}"
                )
        
        except Exception as e:
            await self.telegram_handler.notify_error(
                f"خطأ في تنفيذ الشراء: {str(e)}"
            )
    
    async def execute_sell(self, symbol: str, price: float):
        """تنفيذ أمر بيع فوري"""
        try:
            # ... (منطق التنفيذ كما هو)
            buy_price, peak_price, quantity = self.trading_engine.close_position(symbol)
            
            order = await self.mexc_handler.market_sell(symbol, quantity)
            
            if order:
                sell_price = float(order.get('price', price))
                profit_loss = (sell_price - buy_price) * quantity
                profit_percent = ((sell_price / buy_price) - 1) * 100
                
                await self.telegram_handler.notify_sell(
                    symbol,
                    buy_price,
                    sell_price,
                    quantity,
                    profit_loss,
                    profit_percent
                )
            else:
                self.trading_engine.open_position(symbol, buy_price, quantity)
                await self.telegram_handler.notify_error(
                    f"فشل تنفيذ أمر بيع {symbol}"
                )
        
        except Exception as e:
            await self.telegram_handler.notify_error(
                f"خطأ في تنفيذ البيع: {str(e)}"
            )
    
    async def on_amount_set(self, amount: float):
        """
        معالج عند تحديد مبلغ الصفقة
        يبدأ WebSocket بعد تحديد المبلغ
        """
        # بدء WebSocket
        if not self.websocket_handler:
            self.websocket_handler = WebSocketHandler(self.on_trade_received, self.symbols)
            asyncio.create_task(self.websocket_handler.start())
        else:
            logger.info("WebSocket already running.")
    
    async def start_websocket(self):
        """
        يبدأ WebSocket إذا كان مبلغ التداول محددًا مسبقًا
        """
        if config.TRADE_AMOUNT_USD > 0:
            await self.on_amount_set(config.TRADE_AMOUNT_USD)
            logger.info(f"✅ تم تحديد مبلغ الصفقة مسبقًا: ${config.TRADE_AMOUNT_USD}. بدء المراقبة.")
        else:
            logger.warning("⚠️ لم يتم تحديد مبلغ الصفقة. البوت في وضع الاستعداد.")
            
    async def stop(self):
        """
        إيقاف البوت بشكل آمن
        """
        logger.info("🛑 جاري إيقاف البوت...")
        self.running = False
        
        # إيقاف WebSocket
        if self.websocket_handler:
            await self.websocket_handler.disconnect()
        
        # إغلاق جلسة MEXC
        await self.mexc_handler.close_session()
        
        logger.info("✅ تم إيقاف البوت بنجاح")

async def startup_logic():
    """
    منطق بدء التشغيل الرئيسي للتطبيق المستقل
    """
    global omega_predator, telegram_application
    
    logger.info("=" * 50)
    logger.info("🎯 Omega Predator Standalone Bot Startup")
    logger.info("=" * 50)
    
    # التحقق من الإعدادات
    if not config.validate_config():
        logger.error("❌ فشل التحقق من الإعدادات. إنهاء التشغيل.")
        sys.exit(1) # إنهاء التطبيق إذا كانت الإعدادات غير صحيحة
        
    logger.info(f"✅ عتبة الشراء: {config.BUY_THRESHOLD * 100}%")
    logger.info(f"✅ عتبة البيع: {config.SELL_THRESHOLD * 100}%")
    logger.info(f"✅ النافذة الزمنية: {config.TIME_WINDOW} ثانية")
    logger.info("=" * 50)
    
    # تهيئة Telegram Application
    telegram_application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # تهيئة وبدء التطبيق
    await telegram_application.initialize()
    
    # يجب استخدام long-polling أو webhook هنا. بما أن Render لا يدعم long-polling بسهولة،
    # سنفترض أن Render سيقوم بتشغيل هذا كخدمة ويب، ولكن بدون FastAPI.
    # بما أننا حولناه إلى تطبيق مستقل، سنستخدم long-polling.
    
    # تهيئة البوت الرئيسي
    mexc_handler_temp = MEXCHandler()
    all_symbols = await mexc_handler_temp.get_all_symbols()
    await mexc_handler_temp.close_session() # إغلاق الجلسة المؤقتة

    if not all_symbols:
        logger.error("❌ فشل في جلب قائمة الرموز من MEXC. إنهاء التشغيل.")
        sys.exit(1)

    logger.info(f"✅ تم جلب {len(all_symbols)} رمز تداول للمراقبة الشاملة.")
    
    omega_predator = OmegaPredator(telegram_application, all_symbols)
    
    # بدء WebSocket إذا كان المبلغ محددًا
    asyncio.create_task(omega_predator.start_websocket())
    
    # إرسال رسالة الترحيب
    await omega_predator.telegram_handler.send_welcome_message()
    
    # بدء تشغيل البوت (long-polling)
    # بما أننا في بيئة Render، يجب أن نستخدم وضع Webhook، ولكن بما أننا أزلنا FastAPI،
    # سنستخدم long-polling ونأمل أن يكون Render قد سمح بذلك.
    # في حالة فشل long-polling، يجب على المستخدم العودة إلى Webhook مع إطار عمل ويب.
    
    # سنستخدم run_polling كحل مؤقت لتشغيل البوت بشكل مستقل
    await telegram_application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        asyncio.run(startup_logic())
    except KeyboardInterrupt:
        logger.info("تم إيقاف التشغيل بواسطة المستخدم.")
    except Exception as e:
        logger.error(f"خطأ غير متوقع في التشغيل: {e}")
        sys.exit(1)

"""
Omega Predator - Main Module
نقطة الدخول الرئيسية للبوت
"""

import asyncio
import time
import sys
from typing import Optional

import config
from trading_logic import TradingEngine
from mexc_handler import MEXCHandler
from websocket_handler import WebSocketHandler
from telegram_handler import TelegramHandler


class OmegaPredator:
    """
    البوت الرئيسي - Omega Predator
    تنسيق جميع الوحدات والتحكم في التداول
    """
    
    def __init__(self):
        self.trading_engine = TradingEngine()
        self.mexc_handler = MEXCHandler()
        self.telegram_handler = TelegramHandler()
        self.websocket_handler: Optional[WebSocketHandler] = None
        self.running = False
    
    async def on_trade_received(self, symbol: str, price: float, timestamp: float):
        """
        معالج استقبال صفقة جديدة من WebSocket
        هذه هي الحلقة الساخنة (Hot Loop) - يجب أن تكون سريعة للغاية
        
        Args:
            symbol: رمز العملة
            price: السعر
            timestamp: الطابع الزمني
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
        """
        تنفيذ أمر شراء فوري
        
        Args:
            symbol: رمز العملة
            price: السعر الحالي
        """
        try:
            # تنفيذ الأمر
            order = await self.mexc_handler.market_buy(symbol, config.TRADE_AMOUNT_USD)
            
            if order:
                # استخراج معلومات الأمر
                executed_qty = float(order.get('executedQty', 0))
                executed_price = float(order.get('price', price))
                
                # فتح الصفقة في محرك التداول
                self.trading_engine.open_position(symbol, executed_price, executed_qty)
                
                # إرسال إشعار (بعد التنفيذ)
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
        """
        تنفيذ أمر بيع فوري
        
        Args:
            symbol: رمز العملة
            price: السعر الحالي
        """
        try:
            # الحصول على معلومات الصفقة
            buy_price, peak_price, quantity = self.trading_engine.close_position(symbol)
            
            # تنفيذ الأمر
            order = await self.mexc_handler.market_sell(symbol, quantity)
            
            if order:
                # حساب الربح/الخسارة
                sell_price = float(order.get('price', price))
                profit_loss = (sell_price - buy_price) * quantity
                profit_percent = ((sell_price / buy_price) - 1) * 100
                
                # إرسال إشعار (بعد التنفيذ)
                await self.telegram_handler.notify_sell(
                    symbol,
                    buy_price,
                    sell_price,
                    quantity,
                    profit_loss,
                    profit_percent
                )
            else:
                # إذا فشل البيع، نعيد فتح الصفقة
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
        
        Args:
            amount: المبلغ المحدد
        """
        # بدء WebSocket
        self.websocket_handler = WebSocketHandler(self.on_trade_received)
        asyncio.create_task(self.websocket_handler.start())
    
    async def start(self):
        """
        بدء تشغيل البوت
        """
        print("=" * 50)
        print("🎯 Omega Predator Trading Bot")
        print("=" * 50)
        
        # التحقق من الإعدادات
        if not config.validate_config():
            print("❌ فشل التحقق من الإعدادات. يرجى التحقق من ملف .env")
            return
        
        print(f"✅ القائمة البيضاء: {', '.join(config.WHITELIST)}")
        print(f"✅ عتبة الشراء: {config.BUY_THRESHOLD * 100}%")
        print(f"✅ عتبة البيع: {config.SELL_THRESHOLD * 100}%")
        print(f"✅ النافذة الزمنية: {config.TIME_WINDOW} ثانية")
        print("=" * 50)
        
        self.running = True
        
        # تعيين callback لتحديد المبلغ
        self.telegram_handler.on_amount_set = self.on_amount_set
        
        # بدء الاستماع لأوامر Telegram
        telegram_task = asyncio.create_task(self.telegram_handler.listen_for_commands())
        
        # طلب مبلغ الصفقة
        amount = await self.telegram_handler.request_trade_amount()
        
        if amount <= 0:
            print("❌ لم يتم تحديد مبلغ صحيح. إنهاء البرنامج.")
            self.running = False
            return
        
        print(f"✅ تم تحديد مبلغ الصفقة: ${amount}")
        
        # انتظار حتى يتم إيقاف البوت
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n⚠️ تم إيقاف البوت بواسطة المستخدم")
        finally:
            await self.stop()
    
    async def stop(self):
        """
        إيقاف البوت بشكل آمن
        """
        print("🛑 جاري إيقاف البوت...")
        self.running = False
        
        # إيقاف WebSocket
        if self.websocket_handler:
            await self.websocket_handler.disconnect()
        
        # إيقاف Telegram
        await self.telegram_handler.stop()
        
        # إغلاق جلسة MEXC
        await self.mexc_handler.close_session()
        
        print("✅ تم إيقاف البوت بنجاح")


async def main():
    """
    نقطة الدخول الرئيسية
    """
    bot = OmegaPredator()
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 وداعًا!")
        sys.exit(0)

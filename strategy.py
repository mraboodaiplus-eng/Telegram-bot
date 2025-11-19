import time
import json
import os
from collections import deque
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("OmegaStrategy")

class OmegaStrategy:
    def __init__(self, mexc_handler, telegram_bot):
        self.mexc = mexc_handler
        self.bot = telegram_bot
        self.price_windows = {}
        
        # تحميل الصفقات القديمة من الملف
        self.active_trades = self.load_trades()
        
        self.trade_amount_usd = None
        self.is_running = False
        self.db_file = "trades.json"

    def load_trades(self):
        if os.path.exists("trades.json"):
            try:
                with open("trades.json", "r") as f:
                    trades = json.load(f)
                    logger.info(f"📂 تم استرجاع {len(trades)} صفقة مفتوحة من الذاكرة.")
                    return trades
            except:
                return {}
        return {}

    def save_trades(self):
        """حفظ الحالة فوراً"""
        try:
            with open("trades.json", "w") as f:
                json.dump(self.active_trades, f)
        except Exception as e:
            logger.error(f"خطأ في حفظ البيانات: {e}")

    def set_trade_amount(self, amount):
        self.trade_amount_usd = float(amount)
        self.is_running = True
        logger.info(f"🚀 Omega Predator Active. Amount: {amount}$")

    async def process_tick(self, symbol, price, timestamp_ms):
        if not self.is_running: return

        price = float(price)
        current_time = time.time()

        # تحديث النافذة الزمنية
        if symbol not in self.price_windows:
            self.price_windows[symbol] = deque()
        
        window = self.price_windows[symbol]
        window.append((current_time, price))
        while window and (current_time - window[0][0] > 20):
            window.popleft()

        # المنطق
        if symbol in self.active_trades:
            await self._check_sell_condition(symbol, price)
        elif self.trade_amount_usd: # شرط أن يكون المبلغ محدداً
            await self._check_buy_condition(symbol, price, window)

    async def _check_buy_condition(self, symbol, current_price, window):
        if len(window) < 2: return
        oldest_price = window[0][1]
        increase = (current_price / oldest_price) - 1

        if increase >= 0.05:
            # تحقق إضافي بسيط: لا تشتري إذا كنت قد بعت للتو (اختياري)
            logger.info(f"⚡ فرصة شراء: {symbol} ارتفع {increase:.2%}")
            
            success = await self.mexc.place_order(symbol, "BUY", quote_qty=self.trade_amount_usd)
            
            if success:
                # تقدير الكمية المشتراة (سنستخدمها للبيع)
                estimated_qty = self.trade_amount_usd / current_price
                
                self.active_trades[symbol] = {
                    'buy_price': current_price,
                    'peak_price': current_price,
                    'quantity': estimated_qty * 0.998 # خصم عمولة تقريبية 0.2% لتجنب أخطاء الرصيد
                }
                self.save_trades() # حفظ فوري
                await self.bot.send_message(f"🟢 *BUY* {symbol}\nPrice: {current_price}\n🚀 Pump: {increase:.2%}")

    async def _check_sell_condition(self, symbol, current_price):
        trade = self.active_trades[symbol]
        
        if current_price > trade['peak_price']:
            trade['peak_price'] = current_price
            self.save_trades() # تحديث القمة في الملف
        
        drawdown = 1 - (current_price / trade['peak_price'])

        if drawdown >= 0.03:
            logger.info(f"💀 إشارة بيع: {symbol} نزل {drawdown:.2%}")
            
            success = await self.mexc.place_order(symbol, "SELL", quantity=trade['quantity'])
            
            if success:
                pnl = (current_price - trade['buy_price']) / trade['buy_price']
                icon = "💰" if pnl > 0 else "🔻"
                
                del self.active_trades[symbol]
                self.save_trades() # حذف من الملف
                
                await self.bot.send_message(f"{icon} *SELL* {symbol}\nExit: {current_price}\nPNL: {pnl:.2%}")
import json
import os
from collections import deque
import logging

# إعدادات السجل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("OmegaStrategy")

class OmegaStrategy:
    def __init__(self, mexc_handler, telegram_bot):
        self.mexc = mexc_handler
        self.bot = telegram_bot
        self.price_windows = {}
        
        # تحميل الصفقات
        self.active_trades = self.load_trades()
        self.trade_amount_usd = None
        self.is_running = False

    def load_trades(self):
        if os.path.exists("trades.json"):
            try:
                with open("trades.json", "r") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_trades(self):
        try:
            with open("trades.json", "w") as f:
                json.dump(self.active_trades, f)
        except Exception as e:
            logger.error(f"Save Error: {e}")

    def set_trade_amount(self, amount):
        self.trade_amount_usd = float(amount)
        self.is_running = True
        logger.info(f"🚀 Omega Predator Active. Amount: {amount}$")

    async def process_tick(self, symbol, price, timestamp_ms):
        """
        معالجة السعر باستخدام توقيت المنصة (timestamp_ms) حصراً
        لضمان دقة القنص وعدم التأثر ببطء السيرفر.
        """
        if not self.is_running: return

        price = float(price)
        # تحويل التوقيت لثواني (MEXC ترسل ميلي ثانية)
        event_time = timestamp_ms / 1000.0 

        if symbol not in self.price_windows:
            self.price_windows[symbol] = deque()
        
        window = self.price_windows[symbol]
        window.append((event_time, price))
        
        # تنظيف النافذة بناءً على توقيت الصفقة وليس توقيت السيرفر
        # نحتفظ بآخر 60 ثانية لضمان التقاط الحركة حتى لو كانت ممتدة قليلاً
        while window and (event_time - window[0][0] > 60):
            window.popleft()

        # التحقق من الشروط
        if symbol in self.active_trades:
            await self._check_sell_condition(symbol, price)
        elif self.trade_amount_usd:
            await self._check_buy_condition(symbol, price, window, event_time)

    async def _check_buy_condition(self, symbol, current_price, window, current_event_time):
        if len(window) < 2: return
        
        # البحث في النافذة عن أدنى سعر في آخر 20 ثانية (القاع المحلي)
        # هذا أدق من مجرد مقارنة الأول بالأخير
        recent_window = [p for t, p in window if current_event_time - t <= 20]
        
        if not recent_window: return

        lowest_price = min(recent_window)
        
        # حساب نسبة الارتفاع من القاع
        increase = (current_price / lowest_price) - 1

        # الشرط: 2.5% ارتفاع في آخر 20 ثانية
        if increase >= 0.025:
            logger.info(f"⚡ DETECTED: {symbol} pumped {increase:.2%} from low {lowest_price}")
            
            # تنفيذ الشراء فوراً
            success = await self.mexc.place_order(symbol, "BUY", quote_qty=self.trade_amount_usd)
            
            if success:
                self.active_trades[symbol] = {
                    'buy_price': current_price,
                    'peak_price': current_price,
                    'quantity': (self.trade_amount_usd / current_price) * 0.998
                }
                self.save_trades()
                await self.bot.send_message(f"🟢 *BUY* {symbol}\nPrice: {current_price}\n📈 Change: {increase:.2%}")

    async def _check_sell_condition(self, symbol, current_price):
        trade = self.active_trades[symbol]
        
        # تحديث القمة
        if current_price > trade['peak_price']:
            trade['peak_price'] = current_price
            self.save_trades()
        
        # شرط الخروج: نزول 2% من القمة
        drawdown = 1 - (current_price / trade['peak_price'])

        if drawdown >= 0.02:
            success = await self.mexc.place_order(symbol, "SELL", quantity=trade['quantity'])
            
            if success:
                pnl = (current_price - trade['buy_price']) / trade['buy_price']
                icon = "💰" if pnl > 0 else "🔻"
                del self.active_trades[symbol]
                self.save_trades()
                await self.bot.send_message(f"{icon} *SELL* {symbol}\nExit: {current_price}\nPNL: {pnl:.2%}")
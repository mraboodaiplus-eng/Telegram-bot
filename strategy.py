import time
import json
import os
from collections import deque
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("OmegaStrategy")

class OmegaStrategy:
    def __init__(self, mexc_handler, telegram_bot):
        self.mexc = mexc_handler
        self.bot = telegram_bot
        self.price_windows = {}
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
        logger.info(f"🚀 DIAGNOSTIC MODE ON. Checking logs for movement > 0.5%. Amount: {amount}$")

    async def process_tick(self, symbol, price, timestamp_ms):
        if not self.is_running: return

        price = float(price)
        # استخدام توقيت المنصة
        event_time = timestamp_ms / 1000.0 

        if symbol not in self.price_windows:
            self.price_windows[symbol] = deque()
        
        window = self.price_windows[symbol]
        window.append((event_time, price))
        
        # نافذة 60 ثانية
        while window and (event_time - window[0][0] > 60):
            window.popleft()

        if symbol in self.active_trades:
            await self._check_sell_condition(symbol, price)
        elif self.trade_amount_usd:
            await self._check_buy_condition(symbol, price, window, event_time)

    async def _check_buy_condition(self, symbol, current_price, window, current_event_time):
        if len(window) < 2: return
        
        # فحص آخر 20 ثانية فقط للشراء
        recent_window = [p for t, p in window if current_event_time - t <= 20]
        if not recent_window: return

        lowest_price = min(recent_window)
        increase = (current_price / lowest_price) - 1

        # 🔍 تشخيص: طباعة أي حركة فوق 0.5% لنعرف أن البوت يرى السوق
        if increase > 0.005: 
            # هذه الرسالة ستظهر فقط في Logs في الموقع
            logger.info(f"👀 {symbol} is moving! Up {increase:.2%} (Price: {current_price})")

        # الشرط الحقيقي للشراء (2.5%)
        if increase >= 0.025:
            logger.info(f"⚡ ATTEMPTING BUY: {symbol} pumped {increase:.2%}")
            
            # محاولة الشراء
            try:
                success = await self.mexc.place_order(symbol, "BUY", quote_qty=self.trade_amount_usd)
                
                if success:
                    logger.info(f"✅ BUY SUCCESS: {symbol}")
                    self.active_trades[symbol] = {
                        'buy_price': current_price,
                        'peak_price': current_price,
                        'quantity': (self.trade_amount_usd / current_price) * 0.998
                    }
                    self.save_trades()
                    await self.bot.send_message(f"🟢 *BUY* {symbol}\nPrice: {current_price}\n📈 Pump: {increase:.2%}")
                else:
                    # فشل الطلب لسبب من المنصة
                    logger.error(f"❌ BUY FAILED for {symbol}. Check API permissions or Min Amount.")
                    await self.bot.send_message(f"⚠️ حاولت شراء {symbol} ولكن المنصة رفضت! تأكد من صلاحيات API أو أن المبلغ فوق 5$.")
            
            except Exception as e:
                logger.error(f"💥 CRITICAL ERROR executing buy: {e}")

    async def _check_sell_condition(self, symbol, current_price):
        trade = self.active_trades[symbol]
        if current_price > trade['peak_price']:
            trade['peak_price'] = current_price
            self.save_trades()
        
        drawdown = 1 - (current_price / trade['peak_price'])

        if drawdown >= 0.02:
            success = await self.mexc.place_order(symbol, "SELL", quantity=trade['quantity'])
            if success:
                pnl = (current_price - trade['buy_price']) / trade['buy_price']
                icon = "💰" if pnl > 0 else "🔻"
                del self.active_trades[symbol]
                self.save_trades()
                await self.bot.send_message(f"{icon} *SELL* {symbol}\nExit: {current_price}\nPNL: {pnl:.2%}")
import time
from collections import deque
import logging

# إعدادات السجل (للمتابعة فقط، يتم تعطيلها في المناطق الحرجة للسرعة)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OmegaStrategy")

class OmegaStrategy:
    def __init__(self):
        # الذاكرة السريعة لكل عملة: {symbol: deque([(timestamp, price), ...])}
        self.price_history = {}
        # حالة التداول: {symbol: {"status": "HUNTING" | "HOLDING", "buy_price": float, "peak_price": float}}
        self.trade_state = {}
        # مبلغ التداول المحدد من المدير العام
        self.trade_amount_usd = None 
        self.active = False

    def set_trade_amount(self, amount):
        self.trade_amount_usd = float(amount)
        self.active = True
        logger.info(f"🚀 Strategy Activated. Trade Amount: ${self.trade_amount_usd}")

    def init_symbol(self, symbol):
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=1000) # حجم احتياطي
            self.trade_state[symbol] = {
                "status": "HUNTING",
                "buy_price": 0.0,
                "peak_price": 0.0
            }

    def process_tick(self, symbol, current_price, timestamp):
        if not self.active or self.trade_amount_usd is None:
            return None # البوت لم يبدأ بعد

        self.init_symbol(symbol)
        state = self.trade_state[symbol]
        history = self.price_history[symbol]

        # 1. تحديث النافذة الزمنية (20 ثانية)
        # إضافة السعر الجديد
        history.append((timestamp, current_price))
        
        # إزالة الأسعار القديمة جداً (أكثر من 20 ثانية)
        while history and (timestamp - history[0][0] > 20000): # 20000 ms
            history.popleft()

        if not history:
            return None

        # --- منطق القناص (HUNTING) ---
        if state["status"] == "HUNTING":
            oldest_price = history[0][1]
            # حساب نسبة الارتفاع
            growth_ratio = (current_price / oldest_price) - 1

            # الشرط: >= 5% (0.05)
            if growth_ratio >= 0.05:
                # ⚡ تنفيذ أعمى - قرار الشراء
                # نغير الحالة فوراً لمنع تكرار الشراء
                state["status"] = "HOLDING"
                state["buy_price"] = current_price
                state["peak_price"] = current_price
                return "BUY"

        # --- منطق الظل اللاصق (HOLDING) ---
        elif state["status"] == "HOLDING":
            # تحديث سعر الذروة
            if current_price > state["peak_price"]:
                state["peak_price"] = current_price
            
            # حساب نسبة التراجع
            drawdown = 1 - (current_price / state["peak_price"])

            # الشرط: >= 3% (0.03)
            if drawdown >= 0.03:
                # ⚡ تنفيذ أعمى - قرار البيع
                state["status"] = "HUNTING" # العودة للصيد
                state["buy_price"] = 0.0
                state["peak_price"] = 0.0
                return "SELL"

        return None
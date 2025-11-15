import asyncio
from collections import deque
from typing import Dict, Tuple, Optional

from config import (
    WHITELIST_SYMBOLS, BUY_THRESHOLD, SELL_THRESHOLD, TIME_WINDOW_SECONDS
)
from mexc_handler import MEXCHandler
from telegram_bot import BOT_STATUS

# تعريف هيكل بيانات الصفقة
# (السعر, الطابع الزمني)
Deal = Tuple[float, int]



class SymbolState:
    """
    إدارة حالة التداول لكل رمز (Symbol).
    تطبيق مبدأ كفاءة هياكل البيانات باستخدام deque.
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
                # deque لتخزين الصفقات في آخر 20 ثانية:
        # (السعر، الطابع الزمني بالمللي ثانية)
        self.deals: deque[Deal] = deque()
        
        # حالة التداول
        self.is_in_position: bool = False
        self.bought_price: Optional[float] = None
        self.peak_price: Optional[float] = None
        
        # قائمة انتظار لتخزين أوامر الشراء المعلقة (للتنفيذ الفوري)
        self.buy_queue = asyncio.Queue()

    def add_deal(self, price: float, timestamp: int):
        """
        إضافة صفقة جديدة وإزالة الصفقات القديمة خارج النافذة الزمنية.
        """
        self.deals.append((price, timestamp))
        
        # إزالة الصفقات التي تجاوزت النافذة الزمنية (20 ثانية)
        time_limit = timestamp - (TIME_WINDOW_SECONDS * 1000)
        while self.deals and self.deals[0][1] < time_limit:
            self.deals.popleft()



class StrategyEngine:
    """
    محرك الاستراتيجية لتنفيذ منطق الشراء والبيع.
    تطبيق مبدأ الدقة المطلقة والسرعة القصوى.
    """
    def __init__(self, mexc_handler: MEXCHandler, telegram_queue: asyncio.Queue):
        self.mexc_handler = mexc_handler
        self.telegram_queue = telegram_queue
        # حالة كل رمز في القائمة البيضاء
        self.states: Dict[str, SymbolState] = {
            symbol: SymbolState(symbol) for symbol in WHITELIST_SYMBOLS
        }
        # قائمة انتظار الصفقات الواردة من WebSocket
        self.deal_queue = asyncio.Queue()

    async def process_deals(self):
        """
        المهمة الرئيسية لمعالجة الصفقات الواردة من mexc_handler.
        """
        while True:
            # استلام الصفقة (symbol, price, timestamp)
            symbol, price, timestamp = await self.deal_queue.get()
            
            if symbol not in self.states:
                # تجاهل أي رمز غير موجود في القائمة البيضاء (بروتوكول المراقبة)
                continue
                
            state = self.states[symbol]
            
            # 1. تحديث نافذة الصفقات
            state.add_deal(price, timestamp)
            
            # تنفيذ خوارزمية الشراء (القناص المتربص)بص)
            if not state.is_in_position and len(state.deals) > 1:
                await self._check_buy_condition(state, price)
                
              # تنفيذ خوارزمية البيع (الظل اللاصق))
            elif state.is_in_position:
                await self._check_sell_condition(state, price)
                
            self.deal_queue.task_done()

    async def _check_buy_condition(self, state: SymbolState, current_price: float):
        """
        خوارزمية الشراء: إذا كان (السعر الحالي / أقدم سعر) - 1 >= 0.05
        """
        # أقدم صفقة هي أول عنصر في deque
        oldest_price = state.deals[0][0]
        
        # الحساب الدقيق: (السعر_الحالي / السعر_الأقدم) - 1
        # لا تضع أي عمليات طباعة أو تسجيل هنا - السرعة هي كل شيء
        try:
            rise_ratio = (current_price / oldest_price) - 1
        except ZeroDivisionError:
            # معالجة حالة نادرة (السعر صفر)
            return

        if rise_ratio >= BUY_THRESHOLD:
            # الزناد (The Trigger): إطلاق أمر شراء فوري
            # يجب أن يكون هذا الجزء سريعًا جدًا
            
            # نفترض كمية ثابتة للشراء (يجب أن يتم تحديدها في config أو من خلال واجهة المستخدم)
            # لغرض التنفيذ، سنفترض كمية رمزية (يجب أن يتم تعديلها لاحقًا)
            # حساب الكمية بناءً على سعر السوق الحالي وقيمة USDT المحددة
            usdt_amount = BOT_STATUS["usdt_amount"]
            quantity = usdt_amount / current_price  # السرعة هي كل شيء: حساب فوري
            result = await self.mexc_handler.execute_order(state.symbol, "BUY", quantity)
            
            if result and result.get('orderId'):
                # تحديث الحالة بعد التنفيذ الناجح
                state.is_in_position = True
                state.bought_price = current_price # سعر التنفيذ
                state.peak_price = current_price
                
                # إبلاغ التليجرام
                message = (
                    f"🚨 BUY TRIGGERED: {state.symbol}\n"
                    f"Price: {current_price:.8f}\n"
                    f"Rise: {rise_ratio * 100:.2f}%\n"
                    f"Order ID: {result.get('orderId')}"
                )
                await self.telegram_queue.put(message)

    async def _check_sell_condition(self, state: SymbolState, current_price: float):
        """
        خوارزمية البيع: إذا كان 1 - (السعر الحالي / سعر الذروة) >= 0.03
        """
        # 1. تتبع الذروة (Peak Tracking)
        if current_price > state.peak_price:
            state.peak_price = current_price
            
        # 2. عتبة التراجع (The Drawdown Threshold)
        # 1 - (السعر_الحالي / سعر_الذروة)
        try:
            drawdown_ratio = 1 - (current_price / state.peak_price)
        except ZeroDivisionError:
            return

        if drawdown_ratio >= SELL_THRESHOLD:
            # الخروج الحاسم (The Decisive Exit): إطلاق أمر بيع فوري
            
            # نفترض كمية البيع هي نفس كمية الشراء (يجب أن يتم تعديلها لاحقًا)
            # في بيئة حقيقية، يجب استرداد الكمية المتاحة من الرصيد
            # لغرض هذا الكود، سنفترض أننا نبيع نفس الكمية التي اشتريناها (للتجربة)
            quantity = BOT_STATUS["usdt_amount"] / state.bought_price if state.bought_price else 0.001
            
            # تنفيذ الأمر
            result = await self.mexc_handler.execute_order(state.symbol, "SELL", quantity)
            
            if result and result.get('orderId'):
                # تحديث الحالة بعد التنفيذ الناجح
                profit_loss = (current_price - state.bought_price) / state.bought_price * 100
                
                # إعادة تعيين الحالة
                state.is_in_position = False
                state.bought_price = None
                state.peak_price = None
                
                # إبلاغ التليجرام
                message = (
                    f"✅ SELL EXECUTED: {state.symbol}\n"
                    f"Sell Price: {current_price:.8f}\n"
                    f"P/L: {profit_loss:.2f}%\n"
                    f"Drawdown: {drawdown_ratio * 100:.2f}%\n"
                    f"Order ID: {result.get('orderId')}"
                )
                await self.telegram_queue.put(message)

    async def run(self):
        """
        تشغيل محرك الاستراتيجية.
        """
        # يمكن إضافة مهام أخرى هنا إذا لزم الأمر
        await self.process_deals()

# ملاحظة: سيتم تهيئة StrategyEngine في main.py
# وتمرير deal_queue الخاص بها إلى MEXCHandler.

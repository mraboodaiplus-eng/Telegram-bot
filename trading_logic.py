"""
Omega Predator - Trading Logic Module
منطق التداول الأساسي: شروط الشراء والبيع
"""

from collections import deque
from typing import Dict, Optional
import time
import config


class TradingEngine:
    """
    محرك تداول "أوميغا" - مُحسَّن للسرعة القصوى.
    """
    
    def __init__(self, symbols: list[str]):
        self.price_windows: Dict[str, deque] = {symbol: deque() for symbol in symbols}
        self.positions: Dict[str, dict] = {
            symbol: {'active': False, 'peak_price': 0.0} for symbol in symbols
        }
        # تحميل الإعدادات لضمان المرونة
        self.TIME_WINDOW = config.TIME_WINDOW
        self.BUY_THRESHOLD = config.BUY_THRESHOLD
        self.SELL_THRESHOLD = config.SELL_THRESHOLD

    def process_new_trade(self, symbol: str, price: float) -> Optional[str]:
        """
        المسار الحرج: يعالج كل صفقة جديدة ويقرر الشراء أو البيع.
        هذه هي الدالة الوحيدة التي يجب استدعاؤها من الخارج.
        
        Args:
            symbol: رمز العملة
            price: سعر الصفقة الجديدة
            
        Returns:
            'BUY', 'SELL', or None
        """
        current_time = time.time()
        window = self.price_windows.get(symbol)
        position = self.positions.get(symbol)

        # حماية ضد أي رموز غير متوقعة
        if window is None or position is None:
            return None

        # الخطوة 1: إضافة الصفقة الجديدة دائمًا
        window.append((price, current_time))

        # الخطوة 2: التحقق من شرط البيع أولاً (أولوية حماية رأس المال)
        if position['active']:
            if price > position['peak_price']:
                position['peak_price'] = price
            
            drawdown = 1 - (price / position['peak_price'])
            if drawdown >= self.SELL_THRESHOLD:
                return 'SELL'
            return None

        # الخطوة 3: إذا لم تكن هناك صفقة نشطة، تحقق من شرط الشراء
        cutoff_time = current_time - self.TIME_WINDOW
        while window and window[0][1] < cutoff_time:
            window.popleft()

        if len(window) < 2:
            return None
            
        oldest_price = window[0][0]
        
        rise_ratio = (price / oldest_price) - 1
        
        if rise_ratio >= self.BUY_THRESHOLD:
            return 'BUY'
            
        return None

    def open_position(self, symbol: str, buy_price: float):
        """يتم استدعاؤها *بعد* تنفيذ أمر الشراء بنجاح."""
        if symbol in self.positions:
            self.positions[symbol] = {'active': True, 'peak_price': buy_price}
    
    def close_position(self, symbol: str):
        """يتم استدعاؤها *بعد* تنفيذ أمر البيع بنجاح."""
        if symbol in self.positions:
            self.positions[symbol] = {'active': False, 'peak_price': 0.0}

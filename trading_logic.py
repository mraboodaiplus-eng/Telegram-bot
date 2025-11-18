"""
Omega Predator - Trading Logic Module
منطق التداول الأساسي: شروط الشراء والبيع
"""

import asyncio
from collections import deque
from typing import Dict, Optional, Tuple
from datetime import datetime
import config


class TradingEngine:
    """
    محرك التداول الرئيسي
    يدير نوافذ الأسعار وشروط الشراء/البيع
    """
    
    def __init__(self, symbols: list[str]):
        # نوافذ الأسعار لكل عملة (deque للسرعة القصوى)
        self.price_windows: Dict[str, deque] = {}
        
        # حالة التداول لكل عملة
        self.positions: Dict[str, dict] = {}
        
        # تهيئة النوافذ للعملات التي تم جلبها ديناميكياً
        for symbol in symbols:
            self.price_windows[symbol] = deque(maxlen=1000)  # حد أقصى للأمان
            self.positions[symbol] = {
                'active': False,
                'buy_price': 0.0,
                'peak_price': 0.0,
                'quantity': 0.0
            }
    
    def add_price(self, symbol: str, price: float, timestamp: float):
        """
        إضافة سعر جديد للنافذة الزمنية
        
        Args:
            symbol: رمز العملة (مثل BTCUSDT)
            price: السعر الحالي
            timestamp: الطابع الزمني (Unix timestamp)
        """
        if symbol not in self.price_windows:
            # print(f"⚠️ تحذير: محاولة إضافة سعر لرمز غير مراقب: {symbol}") # تم التعليق لتقليل الضوضاء
            return
        
        self.price_windows[symbol].append({
            'price': price,
            'timestamp': timestamp
        })
    
    def clean_old_prices(self, symbol: str, current_time: float):
        """
        إزالة الأسعار القديمة خارج النافذة الزمنية
        
        Args:
            symbol: رمز العملة
            current_time: الوقت الحالي (Unix timestamp)
        """
        if symbol not in self.price_windows:
            # print(f"⚠️ تحذير: محاولة إضافة سعر لرمز غير مراقب: {symbol}") # تم التعليق لتقليل الضوضاء
            return
        
        window = self.price_windows[symbol]
        cutoff_time = current_time - config.TIME_WINDOW
        
        # إزالة الأسعار القديمة من البداية
        while window and window[0]['timestamp'] < cutoff_time:
            window.popleft()
    
    def check_buy_condition(self, symbol: str, current_price: float, current_time: float) -> bool:
        """
        فحص شرط الشراء: ارتفاع 5% خلال 20 ثانية
        
        Args:
            symbol: رمز العملة
            current_price: السعر الحالي
            current_time: الوقت الحالي
            
        Returns:
            True إذا تحقق شرط الشراء
        """
        # لا نشتري إذا كان لدينا صفقة مفتوحة
        if self.positions[symbol]['active']:
            return False
        
        # تنظيف الأسعار القديمة
        self.clean_old_prices(symbol, current_time)
        
        window = self.price_windows[symbol]
        
        # نحتاج على الأقل سعرين للمقارنة
        if len(window) < 2:
            return False
        
        # أقدم سعر في النافذة
        oldest_price = window[0]['price']
        
        # حساب نسبة الارتفاع
        rise_ratio = (current_price / oldest_price) - 1
        
        # شرط الشراء: ارتفاع >= 5%
        return rise_ratio >= config.BUY_THRESHOLD
    
    def check_sell_condition(self, symbol: str, current_price: float) -> bool:
        """
        فحص شرط البيع: تراجع 3% من الذروة
        
        Args:
            symbol: رمز العملة
            current_price: السعر الحالي
            
        Returns:
            True إذا تحقق شرط البيع
        """
        position = self.positions[symbol]
        
        # لا نبيع إذا لم يكن لدينا صفقة مفتوحة
        if not position['active']:
            return False
        
        # تحديث سعر الذروة إذا كان السعر الحالي أعلى
        if current_price > position['peak_price']:
            position['peak_price'] = current_price
        
        # حساب نسبة التراجع من الذروة
        drawdown_ratio = 1 - (current_price / position['peak_price'])
        
        # شرط البيع: تراجع >= 3%
        return drawdown_ratio >= config.SELL_THRESHOLD
    
    def open_position(self, symbol: str, buy_price: float, quantity: float):
        """
        فتح صفقة جديدة
        
        Args:
            symbol: رمز العملة
            buy_price: سعر الشراء
            quantity: الكمية المشتراة
        """
        self.positions[symbol] = {
            'active': True,
            'buy_price': buy_price,
            'peak_price': buy_price,  # الذروة تبدأ من سعر الشراء
            'quantity': quantity
        }
    
    def close_position(self, symbol: str) -> Tuple[float, float, float]:
        """
        إغلاق صفقة
        
        Args:
            symbol: رمز العملة
            
        Returns:
            (buy_price, peak_price, quantity)
        """
        position = self.positions[symbol]
        buy_price = position['buy_price']
        peak_price = position['peak_price']
        quantity = position['quantity']
        
        # إعادة تعيين الصفقة
        self.positions[symbol] = {
            'active': False,
            'buy_price': 0.0,
            'peak_price': 0.0,
            'quantity': 0.0
        }
        
        return buy_price, peak_price, quantity
    
    def get_position_status(self, symbol: str) -> dict:
        """
        الحصول على حالة الصفقة الحالية
        
        Args:
            symbol: رمز العملة
            
        Returns:
            معلومات الصفقة
        """
        return self.positions[symbol].copy()

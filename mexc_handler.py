"""
Omega Predator - MEXC Handler Module
معالج MEXC API لتنفيذ الأوامر
"""

import asyncio
import hashlib
import hmac
import time
from typing import Optional, Dict
import aiohttp
import config


class MEXCHandler:
    """
    معالج MEXC API
    تنفيذ أوامر الشراء والبيع الفورية
    """
    
    def __init__(self):
        self.api_key = config.MEXC_API_KEY
        self.secret_key = config.MEXC_SECRET_KEY
        self.base_url = config.MEXC_BASE_URL
        self.session: Optional[aiohttp.ClientSession] = None
        self.symbol_precision: Dict[str, Dict] = {} # تخزين معلومات الدقة
    
    async def init_session(self):
        """تهيئة جلسة HTTP غير متزامنة"""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close_session(self):
        """إغلاق جلسة HTTP"""
        if self.session:
            await self.session.close()
            self.session = None
    
    def _generate_signature(self, params: Dict[str, str]) -> str:
        """
        توليد التوقيع للطلبات المصادق عليها
        
        Args:
            params: معاملات الطلب
            
        Returns:
            التوقيع
        """
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    async def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """
        الحصول على معلومات العملة (الدقة، الحد الأدنى، إلخ)
        
        Args:
            symbol: رمز العملة
            
        Returns:
            معلومات العملة أو None في حالة الفشل
        # إذا كانت المعلومات مخزنة بالفعل، نرجعها
        if symbol in self.symbol_precision:
            return self.symbol_precision[symbol]
        
        await self.init_session()
        
        try:
            url = f"{self.base_url}/api/v3/exchangeInfo"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    for s in data.get('symbols', []):
                        if s['symbol'] == symbol:
                            # تخزين المعلومات قبل إرجاعها
                            self.symbol_precision[symbol] = s
                            return s
        except Exception as e:
            print(f"❌ خطأ في الحصول على معلومات {symbol}: {e}")
        
        return Noneone
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """
        الحصول على السعر الحالي للعملة
        
        Args:
            symbol: رمز العملة
            
        Returns:
            السعر الحالي أو None
        """
        await self.init_session()
        
        try:
            url = f"{self.base_url}/api/v3/ticker/price"
            params = {'symbol': symbol}
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data['price'])
        except Exception as e:
            print(f"❌ خطأ في الحصول على السعر: {e}")
        
        return None
    
    async def market_buy(self, symbol: str, amount_usd: float, current_price: float) -> Optional[Dict]:
        """
        تنفيذ أمر شراء فوري (Market Buy)
        
        Args:
            symbol: رمز العملة (مثل BTCUSDT)
            amount_usd: المبلغ بالدولار
            
        Returns:
            معلومات الأمر أو None في حالة الفشل
        """
        await self.init_session()
        
        try:
            # حساب الكمية بناءً على السعر الفوري الذي تم استقباله من WebSocket
            quantity = amount_usd / current_price
            
            # الحصول على معلومات العملة للدقة (يتم جلبها مرة واحدة وتخزينها)
            symbol_info = await self.get_symbol_info(symbol)
            
            # منطق تقريب الكمية
            if symbol_info:
                # نستخدم baseSizePrecision لتقريب الكمية
                step_size_str = symbol_info.get('baseSizePrecision', '0.000001')
                step_size = float(step_size_str)
                
                # تقريب الكمية حسب دقة العملة
                # نستخدم round() لتقريب الكمية إلى أقرب مضاعف لـ step_size
                quantity = round(quantity / step_size) * step_size
                
                # تقريب الكمية إلى عدد المنازل العشرية المناسب
                decimal_places = len(step_size_str.split('.')[-1]) if '.' in step_size_str else 0
                quantity = round(quantity, decimal_places)
            
            # إذا لم نجد معلومات الرمز، نستخدم 6 منازل عشرية كافتراضي
            else:
                quantity = round(quantity, 6)
            
            # إعداد المعاملات
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': symbol,
                'side': 'BUY',
                'type': 'MARKET',
                'quantity': str(quantity),
                'timestamp': str(timestamp)
            }
            
            # توليد التوقيع
            params['signature'] = self._generate_signature(params)
            
            # تنفيذ الأمر
            url = f"{self.base_url}/api/v3/order"
            headers = {'X-MEXC-APIKEY': self.api_key}
            
            async with self.session.post(url, params=params, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    print(f"❌ فشل أمر الشراء: {error_text}")
                    return None # إضافة return None هنا لضمان الخروج في حالة الفشل
        
        except Exception as e:
            print(f"❌ خطأ في تنفيذ أمر الشراء: {e}")
        
        return None
    
    async def market_sell(self, symbol: str, quantity: float) -> Optional[Dict]:
        """
        تنفيذ أمر بيع فوري (Market Sell)
        
        Args:
            symbol: رمز العملة
            quantity: الكمية المراد بيعها
            
        Returns:
            معلومات الأمر أو None في حالة الفشل
        """
        await self.init_session()
        
        try:
            # إعداد المعاملات
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': symbol,
                'side': 'SELL',
                'type': 'MARKET',
                'quantity': str(quantity),
                'timestamp': str(timestamp)
            }
            
            # توليد التوقيع
            params['signature'] = self._generate_signature(params)
            
            # تنفيذ الأمر
            url = f"{self.base_url}/api/v3/order"
            headers = {'X-MEXC-APIKEY': self.api_key}
            
            async with self.session.post(url, params=params, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    print(f"❌ فشل أمر البيع: {error_text}")
        
        except Exception as e:
            print(f"❌ خطأ في تنفيذ أمر البيع: {e}")
        
        return None
    
    async def get_account_balance(self) -> Optional[Dict]:
        """
        الحصول على رصيد الحساب
        
        Returns:
            معلومات الرصيد أو None
        """
        await self.init_session()
        
        try:
            timestamp = int(time.time() * 1000)
            params = {
                'timestamp': str(timestamp)
            }
            
            params['signature'] = self._generate_signature(params)
            
            url = f"{self.base_url}/api/v3/account"
            headers = {'X-MEXC-APIKEY': self.api_key}
            
            async with self.session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
        
        except Exception as e:
            print(f"❌ خطأ في الحصول على الرصيد: {e}")
        
        return None

    async def get_all_symbols(self) -> list[str]:
        """
        الحصول على قائمة بجميع أزواج التداول المتاحة (التي تنتهي بـ USDT)
        
        Returns:
            قائمة برموز العملات (مثل ['BTCUSDT', 'ETHUSDT'])
        """
        await self.init_session()
        
        try:
            url = f"{self.base_url}/api/v3/exchangeInfo"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    # تصفية الرموز التي تنتهي بـ USDT فقط
                    symbols = [s['symbol'] for s in data.get('symbols', []) if s['symbol'].endswith('USDT')]
                    
                    # تخزين معلومات الدقة لجميع الرموز التي تم جلبها
                    for s in data.get('symbols', []):
                        if s['symbol'] in symbols:
                            self.symbol_precision[s['symbol']] = s
                            
                    return symbols
                else:
                    error_text = await response.text()
                    print(f"❌ فشل في جلب قائمة الرموز: {error_text}")
        except Exception as e:
            print(f"❌ خطأ في get_all_symbols: {e}")
        
        return []

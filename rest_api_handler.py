"""
Omega Predator - REST API Handler Module (Optimized)
معالج REST API محسّن للحصول على بيانات الصفقات من MEXC بسرعة فائقة
"""

import asyncio
import aiohttp
import time
from typing import Callable, Optional
import config


class RESTAPIHandler:
    """
    معالج REST API محسّن
    مراقبة جميع الرموز بسرعة فائقة باستخدام batch processing و concurrent requests
    """
    
    def __init__(self, on_trade_callback: Callable, symbols: list[str]):
        """
        Args:
            on_trade_callback: دالة يتم استدعاؤها عند استقبال صفقة جديدة
            symbols: قائمة الرموز المراد مراقبتها
        """
        self.api_url = "https://api.mexc.com/api/v3/trades"
        self.on_trade = on_trade_callback
        self.symbols = symbols
        self.running = False
        self.last_trade_id = {}  # تتبع آخر trade_id لكل رمز
        self.session: Optional[aiohttp.ClientSession] = None
        self.batch_size = 50  # عدد الرموز في كل batch
        self.poll_interval = 0.5  # فترة polling بالثواني
    
    async def start(self):
        """
        بدء polling بيانات الصفقات بسرعة فائقة
        """
        print("🔌 بدء معالج REST API المحسّن")
        self.running = True
        
        # إنشاء session مع connection pooling
        connector = aiohttp.TCPConnector(
            limit=100,  # حد أقصى للاتصالات المتزامنة
            limit_per_host=30,  # حد أقصى لكل host
            ttl_dns_cache=300  # تخزين مؤقت لـ DNS
        )
        self.session = aiohttp.ClientSession(connector=connector)
        
        try:
            print(f"📡 بدء مراقبة {len(self.symbols)} رمز بسرعة فائقة...")
            
            # تقسيم الرموز إلى batches
            batches = [
                self.symbols[i:i + self.batch_size]
                for i in range(0, len(self.symbols), self.batch_size)
            ]
            
            # تشغيل polling مستمر
            while self.running:
                # تشغيل جميع batches بشكل متزامن
                tasks = [self.poll_batch(batch) for batch in batches]
                await asyncio.gather(*tasks, return_exceptions=True)
                
                # الانتظار قبل الدورة التالية
                await asyncio.sleep(self.poll_interval)
            
        except Exception as e:
            print(f"❌ خطأ في معالج REST API: {e}")
        finally:
            self.running = False
            if self.session:
                await self.session.close()
    
    async def poll_batch(self, symbols_batch: list[str]):
        """
        polling batch من الرموز بشكل متزامن
        """
        tasks = [self.fetch_trades(symbol) for symbol in symbols_batch]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def fetch_trades(self, symbol: str):
        """
        جلب آخر الصفقات لرمز واحد
        """
        try:
            params = {
                "symbol": symbol,
                "limit": 1  # احصل على آخر صفقة فقط
            }
            
            async with self.session.get(
                self.api_url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=2)  # timeout قصير
            ) as response:
                if response.status == 200:
                    trades = await response.json()
                    
                    if trades:
                        trade = trades[0]
                        trade_id = trade.get('id')
                        
                        # تجنب معالجة نفس الصفقة مرتين
                        if symbol not in self.last_trade_id or self.last_trade_id[symbol] != trade_id:
                            self.last_trade_id[symbol] = trade_id
                            
                            # استخراج البيانات
                            price = float(trade['price'])
                            timestamp = float(trade['time']) / 1000
                            
                            # استدعاء callback بدون انتظار
                            asyncio.create_task(
                                self.on_trade(symbol, price, timestamp)
                            )
                
        except asyncio.TimeoutError:
            # يتم تجاهل أخطاء Timeout لأنها متوقعة في بيئة polling سريعة
            pass
        except Exception as e:
            # تسجيل الأخطاء الأخرى للمساعدة في التشخيص
            print(f"⚠️ خطأ في fetch_trades لـ {symbol}: {e}")
    
    async def stop(self):
        """
        إيقاف polling
        """
        self.running = False
        if self.session:
            await self.session.close()
        print("🔌 تم إيقاف معالج REST API")

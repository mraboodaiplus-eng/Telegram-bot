"""
Omega Predator - REST API Handler Module
معالج REST API للحصول على بيانات الصفقات من MEXC
"""

import asyncio
import aiohttp
import time
from typing import Callable, Optional
import config


class RESTAPIHandler:
    """
    معالج REST API
    الحصول على بيانات الصفقات عبر REST API مع polling
    """
    
    def __init__(self, on_trade_callback: Callable, symbols: list[str]):
        """
        Args:
            on_trade_callback: دالة يتم استدعاؤها عند استقبال صفقة جديدة
                              يجب أن تكون async وتقبل (symbol, price, timestamp)
            symbols: قائمة الرموز المراد مراقبتها
        """
        self.api_url = "https://api.mexc.com/api/v3/trades"
        self.on_trade = on_trade_callback
        self.symbols = symbols
        self.running = False
        self.last_trade_id = {}  # تتبع آخر trade_id لكل رمز لتجنب التكرار
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def start(self):
        """
        بدء polling بيانات الصفقات
        """
        print("🔌 بدء معالج REST API")
        self.running = True
        self.session = aiohttp.ClientSession()
        
        try:
            # بدء مهام polling لجميع الرموز
            print(f"📡 بدء polling لـ {len(self.symbols)} رمز...")
            
            # تشغيل polling متوازي لجميع الرموز
            tasks = [self.poll_symbol(symbol) for symbol in self.symbols]
            await asyncio.gather(*tasks)
            
        except Exception as e:
            print(f"❌ خطأ في معالج REST API: {e}")
        finally:
            self.running = False
            if self.session:
                await self.session.close()
    
    async def poll_symbol(self, symbol: str):
        """
        polling بيانات صفقة واحدة بشكل مستمر
        """
        print(f"📊 بدء polling لـ {symbol}")
        
        while self.running:
            try:
                # الحصول على آخر الصفقات
                params = {
                    "symbol": symbol,
                    "limit": 1  # احصل على آخر صفقة فقط
                }
                
                async with self.session.get(self.api_url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        trades = await response.json()
                        
                        if trades:
                            for trade in trades:
                                trade_id = trade.get('id')
                                
                                # تجنب معالجة نفس الصفقة مرتين
                                if symbol not in self.last_trade_id or self.last_trade_id[symbol] != trade_id:
                                    self.last_trade_id[symbol] = trade_id
                                    
                                    # استخراج البيانات
                                    price = float(trade['price'])
                                    timestamp = float(trade['time']) / 1000  # تحويل من ms إلى seconds
                                    
                                    # استدعاء callback
                                    asyncio.create_task(
                                        self.on_trade(symbol, price, timestamp)
                                    )
                    else:
                        print(f"⚠️ خطأ في الحصول على بيانات {symbol}: {response.status}")
                
                # الانتظار قبل الاستطلاع التالي (1 ثانية)
                await asyncio.sleep(1)
                
            except asyncio.TimeoutError:
                print(f"⚠️ انقطع الاتصال بـ {symbol} بسبب timeout")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"❌ خطأ في polling {symbol}: {e}")
                await asyncio.sleep(2)
    
    async def stop(self):
        """
        إيقاف polling
        """
        self.running = False
        if self.session:
            await self.session.close()
        print("🔌 تم إيقاف معالج REST API")

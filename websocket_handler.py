"""
Omega Predator - WebSocket Handler Module
معالج WebSocket للاتصال الفوري بمنصة MEXC
"""

import asyncio
import json
import time
from typing import Callable, Optional
import websockets
import config


class WebSocketHandler:
    """
    معالج WebSocket
    الاتصال الفوري بتدفق بيانات الصفقات
    """
    
    def __init__(self, on_trade_callback: Callable, symbols: list[str]):
        """
        Args:
            on_trade_callback: دالة يتم استدعاؤها عند استقبال صفقة جديدة
                              يجب أن تكون async وتقبل (symbol, price, timestamp)
        """
        self.ws_url = config.MEXC_WS_URL
        self.on_trade = on_trade_callback
        self.symbols = symbols # قائمة الرموز الديناميكية
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
    
    async def connect(self):
        """
        الاتصال بـ WebSocket والاشتراك في القنوات
        """
        try:
            print(f"🔌 جاري الاتصال بـ {self.ws_url}")
            self.websocket = await websockets.connect(self.ws_url)
            self.running = True
            print("✅ تم الاتصال بنجاح")
            
            # الاشتراك في قنوات الصفقات لجميع العملات التي تم جلبها
            print(f"📡 جاري الاشتراك في {len(self.symbols)} قنوات...")
            for symbol in self.symbols:
                subscribe_message = {
                    "method": "SUBSCRIPTION",
                    "params": [
                        f"spot@public.deals.v3.api@{symbol}"
                    ]
                }
                await self.websocket.send(json.dumps(subscribe_message))
            
            print("✅ تم الاشتراك بنجاح")
            
        except Exception as e:
            print(f"❌ فشل الاتصال: {e}")
            self.running = False
    
    async def listen(self):
        """
        الاستماع للرسالل الواردة من WebSocket
        """
        if not self.websocket:
            print("❌ WebSocket غير متصل")
            return
        
        print("📡 بدء الاستماع للرسالل...")
        try:
            async for message in self.websocket:
                if not self.running:
                    break
                
                try:
                    data = json.loads(message)
                    
                    # معالجة رسالل الصفقات
                    if 'c' in data and 'd' in data:
                        channel = data['c']
                        deals = data['d'].get('deals', [])
                        
                        # استخراج رمز العملة من اسم القناة
                        # مثال: "spot@public.deals.v3.api@BTCUSDT"
                        if 'spot@public.deals.v3.api@' in channel:
                            symbol = channel.split('@')[-1]
                            if deals:
                                print(f"📊 استقبلنا {len(deals)} صفقة لـ {symbol}")
                            
                            # معالجة كل صفقة
                            for deal in deals:
                                price = float(deal['p'])
                                timestamp = float(deal['t']) / 1000  # تحويل من ms إلى seconds
                                
                                # استدعاء callback بشكل غير متزامن
                                # لا ننتظر حتى لا نعرقل استقبال الرسائل التالية
                                asyncio.create_task(
                                    self.on_trade(symbol, price, timestamp)
                                )
                
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"⚠️ خطأ في معالجة الرسالة: {e}")
                    continue
        
        except websockets.exceptions.ConnectionClosed:
            print("⚠️ تم إغلاق اتصال WebSocket")
            self.running = False
        except Exception as e:
            print(f"❌ خطأ في الاستماع: {e}")
            self.running = False
    
    async def disconnect(self):
        """
        قطع الاتصال بـ WebSocket
        """
        self.running = False
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            print("🔌 تم قطع اتصال WebSocket")
    
    async def reconnect(self):
        """
        إعادة الاتصال التلقائي
        """
        while config.AUTO_RECONNECT:
            if not self.running:
                print(f"🔄 محاولة إعادة الاتصال بعد {config.RECONNECT_DELAY} ثانية...")
                await asyncio.sleep(config.RECONNECT_DELAY)
                await self.connect()
                if self.running:
                    asyncio.create_task(self.listen())
            else:
                await asyncio.sleep(1)
    
    async def start(self):
        """
        بدء WebSocket مع إعادة الاتصال التلقائي
        """
        print("🔌 بدء دالة WebSocketHandler.start()")
        await self.connect()
        
        # بدء مهمتين متوازيتين: الاستماع وإعادة الاتصال
        print("📡 بدء مهام الاستماع وإعادة الاتصال...")
        listen_task = asyncio.create_task(self.listen())
        reconnect_task = asyncio.create_task(self.reconnect())
        
        print("⏳ في انتظار مهام WebSocket...")
        await asyncio.gather(listen_task, reconnect_task)
        print("🏁 انتهت مهام WebSocket")

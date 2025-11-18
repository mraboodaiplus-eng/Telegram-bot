"""
Omega Predator - MEXC WebSocket Handler Module
معالج WebSocket لجلب الأسعار في الوقت الحقيقي
"""

import asyncio
import json
import logging
from typing import Callable, List, Optional, Dict
import websockets
import config

logger = logging.getLogger(__name__)

class MEXCWebSocketHandler:
    """
    يتولى الاتصال بـ MEXC WebSocket لجلب بيانات الصفقات (Trades) في الوقت الحقيقي.
    """
    
    def __init__(self, on_trade_callback: Callable, symbols: List[str]):
        self.on_trade_callback = on_trade_callback
        self.symbols = symbols
        self.uri = config.MEXC_WS_URL
        self.connection: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        
    async def connect(self):
        """
        إنشاء اتصال WebSocket وبدء حلقة الاستماع.
        """
        self.running = True
        while self.running:
            try:
                logger.info(f"📡 جاري الاتصال بـ MEXC WebSocket: {self.uri}")
                # استخدام timeout لضمان عدم التعليق
                async with websockets.connect(self.uri, open_timeout=10) as websocket:
                    self.connection = websocket
                    logger.info("✅ تم الاتصال بنجاح. جاري الاشتراك في قنوات الصفقات.")
                    
                    # الاشتراك في قنوات الصفقات لجميع الرموز
                    await self._subscribe_to_trades()
                    
                    # بدء حلقة الاستماع
                    await self._listen_for_messages()
                    
            except websockets.exceptions.ConnectionClosedOK:
                logger.info("🛑 تم إغلاق اتصال WebSocket بشكل طبيعي.")
            except Exception as e:
                logger.error(f"❌ خطأ في اتصال WebSocket: {e}")
                if self.running and config.AUTO_RECONNECT:
                    logger.info(f"🔄 إعادة الاتصال بعد {config.RECONNECT_DELAY} ثوانٍ...")
                    await asyncio.sleep(config.RECONNECT_DELAY)
                else:
                    self.running = False
                    
    async def _subscribe_to_trades(self):
        """
        إرسال رسائل الاشتراك في قنوات الصفقات.
        """
        if not self.connection:
            return
            
        params = [f"spot@public.deals.v3.api@{symbol}" for symbol in self.symbols]
        
        subscribe_message = {
            "method": "SUBSCRIPTION",
            "params": params,
            "id": 1
        }
        
        await self.connection.send(json.dumps(subscribe_message))
        logger.info(f"✅ تم إرسال طلب الاشتراك لـ {len(self.symbols)} رمز.")
        
    async def _listen_for_messages(self):
        """
        الاستماع للرسائل الواردة من WebSocket.
        """
        while self.running:
            try:
                message = await self.connection.recv()
                data = json.loads(message)
                
                # تجاهل رسائل الاشتراك والتأكيد
                if data.get('code') == 0 and data.get('msg') == 'Success':
                    continue
                
                # معالجة بيانات الصفقات
                if data.get('c') == 'spot@public.deals.v3.api':
                    await self._process_trade_data(data)
                
                # معالجة رسائل PING/PONG للحفاظ على الاتصال
                if data.get('ping'):
                    await self.connection.send(json.dumps({"pong": data['ping']}))
                    
            except websockets.exceptions.ConnectionClosed:
                logger.warning("⚠️ تم قطع اتصال WebSocket. جاري محاولة إعادة الاتصال.")
                break
            except Exception as e:
                logger.error(f"❌ خطأ في معالجة رسالة WebSocket: {e}")
                
    async def _process_trade_data(self, data: Dict):
        """
        استخراج بيانات الصفقة (Trade) واستدعاء الـ callback.
        """
        symbol = data['d'].get('symbol')
        deals = data['d'].get('deals', [])
        
        for deal in deals:
            price = float(deal['p'])
            # تحويل الطابع الزمني من ميلي ثانية إلى ثانية
            timestamp = deal['t'] / 1000.0 
            
            # استدعاء الـ callback في main.py
            # لا نستخدم asyncio.create_task هنا لأننا نريد أن يتم معالجة كل صفقة
            # بشكل متسلسل داخل حلقة الاستماع، ولكننا نعتمد على أن on_trade_callback
            # ستقوم بإنشاء مهمة جديدة لـ execute_buy/sell
            await self.on_trade_callback(symbol, price, timestamp)
            
    async def disconnect(self):
        """
        إغلاق الاتصال بشكل آمن.
        """
        self.running = False
        if self.connection:
            try:
                await self.connection.close()
                logger.info("🛑 تم إغلاق اتصال WebSocket بنجاح.")
            except Exception as e:
                logger.error(f"❌ خطأ أثناء إغلاق اتصال WebSocket: {e}")
                
    async def start(self):
        """
        بدء تشغيل المعالج.
        """
        # يتم تشغيل دالة connect في مهمة منفصلة من main.py
        await self.connect()

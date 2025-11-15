import aiohttp
import asyncio
import hmac
import hashlib
import time
import json
from urllib.parse import urlencode

from config import (
    MEXC_API_KEY, MEXC_API_SECRET, MEXC_WS_URL, MEXC_REST_URL,
    WHITELIST_SYMBOLS, RECONNECT_DELAY
)



class MEXCHandler:
    """
    إدارة الاتصال عالي السرعة مع منصة MEXC.
    تطبيق مبدأ السرعة المطلقة باستخدام aiohttp و WebSocket.
    """
    def __init__(self, strategy_queue):
        self.session = None
        self.ws = None
        self.strategy_queue = strategy_queue # قائمة انتظار لتمرير الصفقات إلى محرك الاستراتيجية

    async def _get_signed_headers(self, method, path, params=None):
        """توقيع طلبات REST API (مبدأ الدقة المطلقة)."""
        timestamp = int(time.time() * 1000)
        query_string = urlencode(params) if params else ""
        
        # بناء سلسلة التوقيع
        if method == 'GET':
            sign_payload = f"{MEXC_API_KEY}{timestamp}{query_string}"
        else: # POST, DELETE, PUT
            sign_payload = f"{MEXC_API_KEY}{timestamp}{query_string}"
        
        signature = hmac.new(
            MEXC_API_SECRET.encode('utf-8'),
            sign_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return {
            'ApiKey': MEXC_API_KEY,
            'Request-Time': str(timestamp),
            'Signature': signature,
            'Content-Type': 'application/json'
        }

    async def execute_order(self, symbol: str, side: str, quantity: float):
        """
        تنفيذ أمر شراء/بيع فوري (Market Order) عبر REST API.
        محسّن للسرعة القصوى.
        """
        path = "/api/v3/order"
        url = MEXC_REST_URL + path
        
        # يجب أن يكون الكمية دقيقة لتجنب الأخطاء
        params = {
            "symbol": symbol,
            "side": side.upper(), # BUY أو SELL
            "type": "MARKET",
            "quantity": str(quantity)
        }
        
        headers = await self._get_signed_headers('POST', path, params)
        
        try:
            async with self.session.post(url, headers=headers, json=params) as response:
                if response.status == 200:
                    result = await response.json()
                    # يجب أن يكون الإبلاغ عن التنفيذ سريعًا جدًا
                    print(f"Order Executed: {result}")
                    return result
                else:
                    error_text = await response.text()
                    print(f"Order Execution Failed ({response.status}): {error_text}")
                    return None
        except Exception as e:
            print(f"Network Error during order execution: {e}")
            return None

    async def _subscribe_to_deals(self):
        """إرسال طلب الاشتراك في صفقات WebSocket."""
        if not self.ws:
            return

        # بناء قائمة الاشتراكات
        channels = [f"spot@public.deals.v3.api@{symbol}" for symbol in WHITELIST_SYMBOLS]
        
        # رسالة الاشتراك
        subscribe_message = {
            "method": "SUBSCRIPTION",
            "params": channels
        }
        
        await self.ws.send_json(subscribe_message)
        print(f"Subscribed to: {channels}")

    async def _websocket_listener(self):
        """حلقة الاستماع لرسائل WebSocket (مبدأ الموثوقية الصارمة)."""
        while True:
            try:
                msg = await self.ws.receive_json()
                
                # معالجة الرسالة
                if 'd' in msg and 'deals' in msg['d']:
                    # استخراج الصفقات وتمريرها إلى محرك الاستراتيجية
                    for deal in msg['d']['deals']:
                        symbol = msg['d']['symbol']
                        price = float(deal['p'])
                        timestamp = int(deal['t'])
                        
                        # تمرير البيانات الخام إلى قائمة انتظار الاستراتيجية
                        await self.strategy_queue.put((symbol, price, timestamp))
                        
                elif 'code' in msg and msg['code'] != 0:
                    print(f"MEXC WS Error: {msg}")
                    # قد يتطلب هذا إعادة اتصال فورية أو معالجة خطأ محدد
                    break # الخروج لإعادة الاتصال
                
            except json.JSONDecodeError:
                print("Received non-JSON message.")
            except TypeError:
                print("Received message with unexpected structure.")
            except Exception as e:
                print(f"Error in WS listener: {e}")
                break # الخروج لإعادة الاتصال

    async def connect_and_listen(self):
        """إدارة الاتصال وإعادة الاتصال التلقائي (main loop)."""
        self.session = aiohttp.ClientSession()
        
        while True:
            try:
                print(f"Attempting to connect to MEXC WebSocket at {MEXC_WS_URL}...")
                async with self.session.ws_connect(MEXC_WS_URL) as ws:
                    self.ws = ws
                    print("MEXC WebSocket connected successfully.")
                    
                    await self._subscribe_to_deals()
                    
                    # بدء الاستماع
                    await self._websocket_listener()
                    
            except aiohttp.ClientConnectorError as e:
                print(f"Connection failed: {e}. Retrying in {RECONNECT_DELAY} seconds...")
            except Exception as e:
                print(f"Unexpected error: {e}. Retrying in {RECONNECT_DELAY} seconds...")
            finally:
                # التأكد من إغلاق الاتصال قبل إعادة المحاولة
                if self.ws and not self.ws.closed:
                    await self.ws.close()
                self.ws = None
                await asyncio.sleep(RECONNECT_DELAY)

    async def close(self):
        """إغلاق الجلسة بشكل نظيف."""
        if self.session:
            await self.session.close()

# ملاحظة: وظائف REST API (execute_order) يجب أن تكون متاحة للاستدعاء من strategy.py
# سيتم تمرير مثيل MEXCHandler إلى strategy.py عند التهيئة.

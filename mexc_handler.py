import aiohttp
import asyncio
import json
import time
import hmac
import hashlib
from urllib.parse import urlencode
import config
from strategy import OmegaStrategy
import logging

logger = logging.getLogger("MEXCHandler")

class MEXCHandler:
    def __init__(self, strategy: OmegaStrategy, telegram_callback):
        self.api_key = config.MEXC_API_KEY
        self.api_secret = config.MEXC_API_SECRET
        self.base_url = "https://api.mexc.com"
        self.ws_url = "wss://wbs.mexc.com/ws"
        self.strategy = strategy
        self.telegram_alert = telegram_callback

    def _get_server_time(self):
        return int(time.time() * 1000)

    def _sign(self, query_string):
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def execute_order(self, symbol, side, amount_usd=None):
        """
        تنفيذ فوري للأمر عبر REST API
        Side: 'BUY' or 'SELL'
        """
        async with aiohttp.ClientSession() as session:
            endpoint = "/api/v3/order"
            
            # جلب السعر الحالي لتقدير الكمية (تقريبي للسرعة)
            # ملاحظة: في بيئة الإنتاج الحقيقية يفضل استخدام quoteOrderQty إذا كانت المدعومة، 
            # ولكن هنا سنستخدم المنطق القياسي.
            # للحفاظ على السرعة، نرسل طلب MARKET.
            
            # تحديد الكمية: نحتاج لمعرفة الكمية بناءً على الدولار.
            # بما أننا نريد السرعة، سنعتمد على quoteOrderQty لأوامر الشراء (USDT)
            # ولأوامر البيع نحتاج لبيع كامل الكمية الموجودة (أو تتبع ما تم شراؤه).
            
            params = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "timestamp": self._get_server_time(),
                "recvWindow": 5000
            }

            if side == "BUY":
                # شراء بقيمة محددة من USDT
                params["quoteOrderQty"] = self.strategy.trade_amount_usd
            elif side == "SELL":
                # في حالة البيع، نحتاج لمعرفة الكمية التي نملكها.
                # للسرعة القصوى، سنفترض بيع 99% مما تم شراؤه لتجنب أخطاء الدقة، 
                # أو يجب جلب الرصيد. جلب الرصيد يضيف وقتاً.
                # الحل الأفضل: طلب بيع بقيمة quoteOrderQty تقريبية أو جلب الرصيد بشكل غير متزامن سابقاً.
                # لتنفيذ الأمر بدقة: سنطلب معلومات الحساب بسرعة فائقة.
                account_info = await self._get_account_balance(session, symbol.replace("USDT", ""))
                if account_info:
                     params["quantity"] = account_info # بيع كل الكمية
                else:
                    logger.error("❌ Failed to get balance for sell.")
                    return

            query_string = urlencode(params)
            signature = self._sign(query_string)
            url = f"{self.base_url}{endpoint}?{query_string}&signature={signature}"
            
            headers = {"X-MEXC-APIKEY": self.api_key, "Content-Type": "application/json"}

            try:
                start_t = time.perf_counter()
                async with session.post(url, headers=headers) as response:
                    result = await response.json()
                    end_t = time.perf_counter()
                    latency = (end_t - start_t) * 1000
                    
                    if response.status == 200 and "orderId" in result:
                        log_msg = f"✅ ORDER EXECUTED: {side} {symbol} in {latency:.2f}ms"
                        print(log_msg)
                        await self.telegram_alert(log_msg)
                    else:
                        err_msg = f"❌ ORDER FAILED: {result}"
                        print(err_msg)
                        await self.telegram_alert(err_msg)
            except Exception as e:
                print(f"❌ EXECUTION ERROR: {e}")

    async def _get_account_balance(self, session, asset):
        # وظيفة مساعدة سريعة لجلب الرصيد
        endpoint = "/api/v3/account"
        params = {"timestamp": self._get_server_time()}
        query_string = urlencode(params)
        signature = self._sign(query_string)
        url = f"{self.base_url}{endpoint}?{query_string}&signature={signature}"
        headers = {"X-MEXC-APIKEY": self.api_key}
        
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                for balance in data.get("balances", []):
                    if balance["asset"] == asset:
                        # نستخدم free balance
                        # يمكن استخدام تقريب بسيط لضمان قبول الطلب (math.floor)
                        return float(balance["free"])
        return None

    async def start_websocket(self):
        """
        الاتصال الدائم بـ WebSocket
        """
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url) as ws:
                        print("🔌 WebSocket Connected.")
                        
                        # الاشتراك في القائمة البيضاء
                        topics = [f"spot@public.deals.v3.api@{symbol}" for symbol in config.TARGET_COINS]
                        subscribe_msg = {
                            "method": "SUBSCRIPTION",
                            "params": topics
                        }
                        await ws.send_json(subscribe_msg)
                        print(f"📡 Subscribed to: {config.TARGET_COINS}")

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                
                                # معالجة رسائل الصفقات
                                if "d" in data and "deals" in data["d"]:
                                    deals = data["d"]["deals"]
                                    symbol = data["s"] # رمز العملة
                                    
                                    # التعامل مع آخر صفقة في الحزمة (الأحدث)
                                    latest_deal = deals[-1] 
                                    price = float(latest_deal["p"])
                                    timestamp = int(latest_deal["t"])
                                    
                                    # ⚡ استدعاء الاستراتيجية (Critical Path)
                                    action = self.strategy.process_tick(symbol, price, timestamp)
                                    
                                    if action:
                                        # 🚀 تنفيذ فوري في الخلفية دون انتظار
                                        asyncio.create_task(self.execute_order(symbol, action))
                                        
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                print("⚠️ WebSocket Error.")
                                break
            except Exception as e:
                print(f"❌ WebSocket Disconnected: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
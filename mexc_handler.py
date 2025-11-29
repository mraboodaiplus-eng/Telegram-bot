import aiohttp
import asyncio
import json
import time
import hmac
import hashlib
import logging
from urllib.parse import urlencode
from config import Config

logger = logging.getLogger("MEXCHandler")

class MEXCHandler:
    def __init__(self):
        self.base_url = "https://api.mexc.com"
        self.ws_url = "wss://wbs.mexc.com/ws"
        self.strategy = None
        self.target_symbols = [] 
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Content-Type': 'application/json',
            'X-MEXC-APIKEY': Config.MEXC_API_KEY
        }
        self.last_msg_time = 0

    def set_strategy(self, strategy_instance):
        self.strategy = strategy_instance

    def _generate_signature(self, params_string):
        return hmac.new(
            Config.MEXC_API_SECRET.encode('utf-8'),
            params_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def get_all_pairs(self):
        url = f"{self.base_url}/api/v3/ticker/24hr"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        symbols = []
                        for s in data:
                            name = s['symbol']
                            quote_vol = float(s.get('quoteVolume', 0))
                            if name.endswith('USDT') and quote_vol > 50000: # رفعنا الحد قليلاً لضمان الجودة
                                is_excluded = any(ex in name for ex in Config.EXCLUDED_PATTERNS)
                                if not is_excluded:
                                    symbols.append(name)
                        
                        self.target_symbols = symbols
                        logger.info(f"✅ تم تحميل {len(symbols)} عملة قوية.")
                        return symbols
                    return []
            except Exception as e:
                logger.error(f"Error fetching pairs: {e}")
                return []

    async def place_order(self, symbol, side, quantity=None, quote_qty=None):
        async with aiohttp.ClientSession() as session:
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': symbol,
                'side': side.upper(),
                'type': 'MARKET',
                'timestamp': timestamp,
                'recvWindow': 10000 # زيادة النافذة لتجنب رفض الطلب
            }
            if side.upper() == 'BUY' and quote_qty:
                params['quoteOrderQty'] = str(quote_qty)
            elif side.upper() == 'SELL' and quantity:
                params['quantity'] = f"{quantity:.4f}"
            
            query_string = urlencode(params)
            signature = self._generate_signature(query_string)
            url = f"{self.base_url}/api/v3/order?{query_string}&signature={signature}"
            headers = self.headers.copy()
            headers['X-MEXC-APIKEY'] = Config.MEXC_API_KEY

            try:
                async with session.post(url, headers=headers) as response:
                    resp_json = await response.json()
                    if response.status == 200:
                        logger.info(f"✅ ORDER SUCCESS: {side} {symbol}")
                        return True
                    else:
                        logger.error(f"❌ ORDER FAILED: {resp_json}")
                        return False
            except Exception as e:
                logger.error(f"Order Exception: {e}")
                return False

    async def start_websocket(self):
        if not self.target_symbols:
            await self.get_all_pairs()

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    # 🔥 تفعيل Heartbeat (نبض القلب) لمنع الانقطاع
                    async with session.ws_connect(self.ws_url, heartbeat=15, autoping=True) as ws:
                        logger.info("🌐 WebSocket Connected (Heartbeat Active).")
                        
                        # الاشتراك بدفعات
                        chunk_size = 20
                        for i in range(0, len(self.target_symbols), chunk_size):
                            batch = self.target_symbols[i:i + chunk_size]
                            params = {
                                "method": "SUBSCRIPTION",
                                "params": [f"spot@public.deals.v3.api@{s}" for s in batch]
                            }
                            await ws.send_json(params)
                            await asyncio.sleep(0.1)
                        
                        logger.info("✅ Subscriptions Sent. Listening...")
                        self.last_msg_time = time.time()

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                
                                # فحص الاستجابة
                                if 'd' in data and 'deals' in data['d']:
                                    symbol = data['s']
                                    deal = data['d']['deals'][-1]
                                    
                                    # طباعة رسالة "أنا حي" كل 10 ثواني فقط لنتأكد من تدفق البيانات
                                    if time.time() - self.last_msg_time > 10:
                                        logger.info(f"💓 نبض السوق: استقبلت بيانات {symbol} بسعر {deal['p']}")
                                        self.last_msg_time = time.time()

                                    if self.strategy:
                                        await self.strategy.process_tick(symbol, deal['p'], deal['t'])
                                        
                                elif 'msg' in data and data['msg'] == 'PONG':
                                    logger.debug("Received PONG")

                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error("WebSocket Error received.")
                                break
                                
            except Exception as e:
                logger.error(f"⚠️ Connection Lost: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
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

    def set_strategy(self, strategy_instance):
        self.strategy = strategy_instance

    def _generate_signature(self, params_string):
        return hmac.new(
            Config.MEXC_API_SECRET.encode('utf-8'),
            params_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def get_all_pairs(self):
        """جلب العملات النشطة فقط"""
        url = f"{self.base_url}/api/v3/ticker/24hr"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        symbols = []
                        for s in data:
                            name = s['symbol']
                            quote_volume = float(s.get('quoteVolume', 0))
                            is_usdt = name.endswith('USDT')
                            is_excluded = any(ex in name for ex in ['3L', '3S', '4L', '4S', '5L', '5S']) # استبعاد سريع
                            
                            # نركز على العملات اللي فيها حركة (فوق 50 ألف دولار سيولة)
                            if is_usdt and not is_excluded and quote_volume > 50000:
                                symbols.append(name)
                        
                        self.target_symbols = symbols
                        logger.info(f"✅ تم تجهيز {len(symbols)} عملة (تمت الفلترة).")
                        return symbols
                    return []
            except Exception as e:
                logger.error(f"💥 خطأ اتصال: {e}")
                return []

    async def place_order(self, symbol, side, quantity=None, quote_qty=None):
        async with aiohttp.ClientSession() as session:
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': symbol,
                'side': side.upper(),
                'type': 'MARKET',
                'timestamp': timestamp,
                'recvWindow': 5000
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
                        logger.info(f"✅ Order Executed: {side} {symbol}")
                        return True
                    else:
                        logger.error(f"❌ Order Failed: {resp_json}")
                        return False
            except Exception as e:
                logger.error(f"💥 Order Exception: {e}")
                return False

    async def start_websocket(self):
        if not self.target_symbols:
            await self.get_all_pairs()

        while True:
            try:
                # 🔥 الإضافة السحرية: heartbeat=15
                # هذا يمنع المنصة من قطع الاتصال كل 30 ثانية
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url, heartbeat=15) as ws:
                        logger.info("🌐 WebSocket Connected (Stable Mode).")
                        
                        # نرسل الاشتراكات دفعة واحدة (MEXC تتحمل حتى 3000 في اتصال واحد عادة)
                        # لكن نقسمها لأمان أكثر
                        chunk_size = 30
                        for i in range(0, len(self.target_symbols), chunk_size):
                            batch = self.target_symbols[i:i + chunk_size]
                            params = {
                                "method": "SUBSCRIPTION",
                                "params": [f"spot@public.deals.v3.api@{s}" for s in batch]
                            }
                            await ws.send_json(params)
                            await asyncio.sleep(0.05) # فاصل زمني بسيط جداً
                        
                        logger.info("✅ الاشتراكات مفعلة - وضع الثبات.")

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                if 'd' in data and 'deals' in data['d']:
                                    symbol = data['s']
                                    deal = data['d']['deals'][-1]
                                    # إرسال البيانات للاستراتيجية
                                    if self.strategy:
                                        await self.strategy.process_tick(symbol, deal['p'], deal['t'])
                            
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error("WebSocket Error Frame received.")
                                break
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                logger.warning("WebSocket Closed by Server.")
                                break
                                
            except Exception as e:
                logger.error(f"⚠️ Connection Drop: {e}. Reconnecting in 3s...")
                await asyncio.sleep(3)
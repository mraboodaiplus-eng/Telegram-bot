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

    def set_strategy(self, strategy_instance):
        self.strategy = strategy_instance

    def _generate_signature(self, params_string):
        return hmac.new(
            Config.MEXC_API_SECRET.encode('utf-8'),
            params_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def get_all_pairs(self):
        """جلب العملات مع تخفيف القيود وطباعة عينة للتشخيص"""
        url = f"{self.base_url}/api/v3/exchangeInfo"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # --- Debug Start: طباعة عينة من البيانات القادمة ---
                        if 'symbols' in data and len(data['symbols']) > 0:
                            logger.info(f"🔍 DEBUG: Sample Data from MEXC: {data['symbols'][0]}")
                        else:
                            logger.error("⚠️ API returned empty symbols list! Check Server Region.")
                        # ----------------------------------------------------

                        symbols = []
                        for s in data.get('symbols', []):
                            name = s['symbol']
                            
                            # التعديل: إزالة شرط 'status' الصارم مؤقتاً لضمان الجلب
                            # والاكتفاء بأن العملة تنتهي بـ USDT وليست محظورة
                            if (name.endswith('USDT') and 
                                not any(ex in name for ex in Config.EXCLUDED_PATTERNS)):
                                symbols.append(name)
                        
                        self.target_symbols = symbols
                        
                        if len(symbols) > 0:
                            logger.info(f"✅ تم تجهيز {len(symbols)} عملة للمراقبة.")
                        else:
                            logger.warning("⚠️ تم الاتصال ولكن لم يتم العثور على أزواج USDT! قد يكون IP محظوراً.")
                            
                        return symbols
                    else:
                        logger.error(f"❌ فشل جلب العملات. Status: {response.status}")
                        return []
            except Exception as e:
                logger.error(f"💥 خطأ اتصال HTTP: {e}")
                return []

    async def place_order(self, symbol, side, quantity=None, quote_qty=None):
        """إرسال أوامر السوق"""
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
            headers = {'X-MEXC-APIKEY': Config.MEXC_API_KEY, 'Content-Type': 'application/json'}

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
        """اتصال دائم"""
        if not self.target_symbols:
            await self.get_all_pairs()

        # إذا فشل في جلب العملات، حاول مرة أخرى كل 10 ثواني
        while not self.target_symbols:
            logger.warning("⚠️ No symbols found. Retrying in 10s...")
            await asyncio.sleep(10)
            await self.get_all_pairs()

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url) as ws:
                        logger.info(f"🌐 WebSocket Connected. Subscribing to {len(self.target_symbols)} pairs...")
                        
                        # تقسيم الاشتراكات لدفعات (Batches)
                        chunk_size = 30
                        for i in range(0, len(self.target_symbols), chunk_size):
                            batch = self.target_symbols[i:i + chunk_size]
                            params = {
                                "method": "SUBSCRIPTION",
                                "params": [f"spot@public.deals.v3.api@{s}" for s in batch]
                            }
                            await ws.send_json(params)
                            await asyncio.sleep(0.1) 
                        
                        logger.info("✅ All subscriptions sent.")

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                if 'd' in data and 'deals' in data['d']:
                                    symbol = data['s']
                                    for deal in data['d']['deals']:
                                        if self.strategy:
                                            await self.strategy.process_tick(symbol, deal['p'], deal['t'])
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                break
            except Exception as e:
                logger.error(f"⚠️ WebSocket Crash: {e}. Restarting in 5s...")
                await asyncio.sleep(5)
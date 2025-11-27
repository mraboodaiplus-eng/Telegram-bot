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
        # ... (نفس دالة الجلب السابقة، لا تغيير هنا) ...
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
                            if name.endswith('USDT') and quote_volume > 10000 and not any(ex in name for ex in Config.EXCLUDED_PATTERNS):
                                symbols.append(name)
                        self.target_symbols = symbols
                        logger.info(f"✅ تم تجهيز {len(symbols)} عملة. سيتم توزيعها على قنوات متعددة.")
                        return symbols
                    return []
            except Exception:
                return []

    async def place_order(self, symbol, side, quantity=None, quote_qty=None):
        # ... (نفس دالة الطلب السابقة) ...
        async with aiohttp.ClientSession() as session:
            timestamp = int(time.time() * 1000)
            params = { 'symbol': symbol, 'side': side.upper(), 'type': 'MARKET', 'timestamp': timestamp, 'recvWindow': 5000 }
            if side.upper() == 'BUY' and quote_qty: params['quoteOrderQty'] = str(quote_qty)
            elif side.upper() == 'SELL' and quantity: params['quantity'] = f"{quantity:.4f}"
            
            query_string = urlencode(params)
            signature = self._generate_signature(query_string)
            url = f"{self.base_url}/api/v3/order?{query_string}&signature={signature}"
            headers = self.headers.copy()
            headers['X-MEXC-APIKEY'] = Config.MEXC_API_KEY
            try:
                async with session.post(url, headers=headers) as response:
                    return response.status == 200
            except:
                return False

    async def _socket_worker(self, worker_id, symbols_batch):
        """عامل واحد مسؤول عن مجموعة محددة من العملات"""
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url, heartbeat=15) as ws:
                        logger.info(f"🚀 Worker {worker_id}: Connected. Handling {len(symbols_batch)} coins.")
                        
                        # اشتراك سريع (Batch واحد لأن العدد قليل لكل عامل)
                        params = {
                            "method": "SUBSCRIPTION",
                            "params": [f"spot@public.deals.v3.api@{s}" for s in symbols_batch]
                        }
                        await ws.send_json(params)
                        
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                if 'd' in data and 'deals' in data['d']:
                                    # معالجة فورية
                                    symbol = data['s']
                                    deal = data['d']['deals'][-1]
                                    if self.strategy:
                                        await self.strategy.process_tick(symbol, deal['p'], deal['t'])
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                break
            except Exception as e:
                logger.warning(f"⚠️ Worker {worker_id} disconnected. Reconnecting...")
                await asyncio.sleep(2)

    async def start_multiplex_sockets(self):
        """المايسترو: يوزع العملات على 5 عمال"""
        if not self.target_symbols:
            await self.get_all_pairs()

        total_coins = len(self.target_symbols)
        num_workers = 5 # خمسة اتصالات متوازية
        chunk_size = total_coins // num_workers + 1

        tasks = []
        for i in range(num_workers):
            start = i * chunk_size
            end = start + chunk_size
            batch = self.target_symbols[start:end]
            
            if batch:
                # تشغيل كل عامل في عملية منفصلة (Concurrent Task)
                tasks.append(asyncio.create_task(self._socket_worker(i+1, batch)))
        
        logger.info(f"🔥 Multiplexing Active: {num_workers} parallel sockets launched.")
        await asyncio.gather(*tasks)
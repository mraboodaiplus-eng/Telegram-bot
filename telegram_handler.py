"""
Omega Predator - Telegram Handler Module
معالج Telegram للتحكم والإشعارات
"""

import asyncio
from typing import Optional, Callable
import aiohttp
import config


class TelegramHandler:
    """
    معالج Telegram Bot
    التحكم بالبوت وإرسال الإشعارات
    """
    
    def __init__(self):
        self.bot_token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        self.on_amount_set: Optional[Callable] = None
        self.waiting_for_amount = False
    
    async def init_session(self):
        """تهيئة جلسة HTTP غير متزامنة"""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close_session(self):
        """إغلاق جلسة HTTP"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def send_message(self, text: str) -> bool:
        """
        إرسال رسالة عبر Telegram
        
        Args:
            text: نص الرسالة
            
        Returns:
            True إذا تم الإرسال بنجاح
        """
        await self.init_session()
        
        try:
            url = f"{self.base_url}/sendMessage"
            params = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }
            
            async with self.session.post(url, json=params) as response:
                return response.status == 200
        
        except Exception as e:
            print(f"❌ فشل إرسال رسالة Telegram: {e}")
            return False
    
    async def send_welcome_message(self):
        """
        إرسال رسالة ترحيب فخمة مع قائمة الأوامر
        """
        message = (
            "👑 <b>مرحباً بك سيدي مارك في منظومة Omega Predator</b> 👑\n\n"
            "أنا CodeMaestro، سلاحك الرقمي عالي السرعة في سوق MEXC.\n"
            "لقد تم تفعيل البوت بنجاح، وهو الآن في وضع الاستعداد لتلقي الأوامر.\n\n"
            "⚙️ <b>قائمة الأوامر السيادية:</b>\n"
            "• <code>/start</code> - <i>إعادة تشغيل البوت وطلب تحديد مبلغ الصفقة.</i>\n"
            "• <code>/amount [مبلغ]</code> - <i>تحديد مبلغ الشراء بالدولار لكل صفقة.</i>\n"
            "• <code>/status</code> - <i>الحصول على حالة البوت الحالية والصفقات المفتوحة.</i>\n"
            "• <code>/stop</code> - <i>إيقاف البوت بشكل آمن (غير مبرمج حاليًا).</i>\n\n"
            "<b>العملات المراقبة:</b> <code>" + ", ".join(config.WHITELIST) + "</code>\n"
            "<b>عتبة الشراء:</b> <code>" + str(config.BUY_THRESHOLD * 100) + "%</code>\n"
            "<b>عتبة البيع:</b> <code>" + str(config.SELL_THRESHOLD * 100) + "%</code>\n\n"
            "<b>يرجى إرسال الأمر <code>/amount [مبلغ]</code> لبدء التداول.</b>\n"
            "مثال: <code>/amount 100</code>"
        )
        await self.send_message(message)

    async def request_trade_amount(self) -> float:
        """
        طلب مبلغ الصفقة من المستخدم
        
        Returns:
            مبلغ الصفقة بالدولار
        """
        self.waiting_for_amount = True
        
        await self.send_message(
            "💰 <b>تحديد مبلغ الصفقة</b>\n\n"
            "يرجى تحديد مبلغ الشراء بالدولار (USD) لكل صفقة.\n"
            "مثال: <code>100</code>"
        )
        
        # انتظار الرد
        amount = 0.0
        timeout = 300  # 5 دقائق
        start_time = asyncio.get_event_loop().time()
        
        while self.waiting_for_amount:
            if asyncio.get_event_loop().time() - start_time > timeout:
                await self.send_message("⏱️ انتهت مهلة الانتظار. يرجى إعادة تشغيل البوت.")
                return 0.0
            
            await asyncio.sleep(1)
        
        return config.TRADE_AMOUNT_USD
    
    async def confirm_amount(self, amount: float):
        """
        تأكيد استلام مبلغ الصفقة
        
        Args:
            amount: المبلغ المحدد
        """
        await self.send_message(
            f"✅ <b>مفهوم</b>\n\n"
            f"سيتم تنفيذ كل صفقة شراء بمبلغ <b>${amount:.2f}</b>\n\n"
            f"🎯 <b>Omega Predator</b> الآن في وضع الصيد."
        )
    
    async def notify_buy(self, symbol: str, price: float, quantity: float, amount: float):
        """
        إشعار بتنفيذ أمر شراء
        
        Args:
            symbol: رمز العملة
            price: سعر الشراء
            quantity: الكمية
            amount: المبلغ الإجمالي
        """
        await self.send_message(
            f"🟢 <b>تم تنفيذ أمر شراء</b>\n\n"
            f"العملة: <code>{symbol}</code>\n"
            f"السعر: <code>${price:.8f}</code>\n"
            f"الكمية: <code>{quantity:.6f}</code>\n"
            f"المبلغ: <code>${amount:.2f}</code>"
        )
    
    async def notify_sell(self, symbol: str, buy_price: float, sell_price: float, 
                         quantity: float, profit_loss: float, profit_percent: float):
        """
        إشعار بتنفيذ أمر بيع
        
        Args:
            symbol: رمز العملة
            buy_price: سعر الشراء
            sell_price: سعر البيع
            quantity: الكمية
            profit_loss: الربح/الخسارة بالدولار
            profit_percent: نسبة الربح/الخسارة
        """
        emoji = "🟢" if profit_loss >= 0 else "🔴"
        status = "ربح" if profit_loss >= 0 else "خسارة"
        
        await self.send_message(
            f"{emoji} <b>تم تنفيذ أمر بيع</b>\n\n"
            f"العملة: <code>{symbol}</code>\n"
            f"سعر الشراء: <code>${buy_price:.8f}</code>\n"
            f"سعر البيع: <code>${sell_price:.8f}</code>\n"
            f"الكمية: <code>{quantity:.6f}</code>\n"
            f"النتيجة: <b>{status} ${abs(profit_loss):.2f} ({profit_percent:+.2f}%)</b>"
        )
    
    async def notify_error(self, error_message: str):
        """
        إشعار بحدوث خطأ
        
        Args:
            error_message: رسالة الخطأ
        """
        await self.send_message(f"❌ <b>خطأ</b>\n\n{error_message}")
    
    async def get_updates(self, offset: int = 0) -> list:
        """
        الحصول على التحديثات من Telegram
        
        Args:
            offset: معرف آخر تحديث
            
        Returns:
            قائمة التحديثات
        """
        await self.init_session()
        
        try:
            url = f"{self.base_url}/getUpdates"
            params = {
                'offset': offset,
                'timeout': 30
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('result', [])
        
        except Exception as e:
            print(f"⚠️ خطأ في الحصول على التحديثات: {e}")
        
        return []
    
    async def listen_for_commands(self):
        """
        الاستماع لأوامر Telegram
        """
        self.running = True
        offset = 0
        
        while self.running:
            try:
                updates = await self.get_updates(offset)
                
                for update in updates:
                    offset = update['update_id'] + 1
                    
                    if 'message' not in update:
                        continue
                    
                    message = update['message']
                    text = message.get('text', '')
                    
                    # معالجة الأوامر
                    if text.startswith('/start'):
                        await self.send_welcome_message()
                    
                    elif text.startswith('/amount'):
                        try:
                            # استخراج المبلغ من الأمر
                            parts = text.split()
                            if len(parts) == 2:
                                amount = float(parts[1])
                                if amount > 0:
                                    config.TRADE_AMOUNT_USD = amount
                                    self.waiting_for_amount = False
                                    await self.confirm_amount(amount)
                                    
                                    if self.on_amount_set:
                                        await self.on_amount_set(amount)
                                else:
                                    await self.send_message("⚠️ يجب أن يكون المبلغ أكبر من صفر.")
                            else:
                                await self.send_message("⚠️ صيغة الأمر غير صحيحة. استخدم: <code>/amount [مبلغ]</code>")
                        except ValueError:
                            await self.send_message("⚠️ يرجى إدخال رقم صحيح بعد الأمر /amount")
                    
                    # معالجة إدخال المبلغ (في حال كان المستخدم يرسل الرقم مباشرة)
                    elif self.waiting_for_amount:
                        try:
                            amount = float(text)
                            if amount > 0:
                                config.TRADE_AMOUNT_USD = amount
                                self.waiting_for_amount = False
                                await self.confirm_amount(amount)
                                
                                if self.on_amount_set:
                                    await self.on_amount_set(amount)
                        except ValueError:
                            await self.send_message("⚠️ يرجى إدخال رقم صحيح")
                
                await asyncio.sleep(1)
            
            except Exception as e:
                print(f"⚠️ خطأ في الاستماع للأوامر: {e}")
                await asyncio.sleep(5)
    
    async def stop(self):
        """إيقاف الاستماع"""
        self.running = False
        await self.close_session()

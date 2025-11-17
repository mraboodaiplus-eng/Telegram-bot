"""
Omega Predator - Telegram Handler Module
معالج Telegram للتحكم والإشعارات باستخدام Webhook
"""

import asyncio
import logging
from typing import Optional, Callable, Dict, Any
import aiohttp
import config
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TelegramHandler:
    """
    معالج Telegram Bot
    التحكم بالبوت وإرسال الإشعارات
    """
    
    def __init__(self, application: Application):
        self.application = application
        self.bot: Bot = application.bot
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.on_amount_set: Optional[Callable] = None
        self.waiting_for_amount = False
        
        # إضافة معالجات الأوامر
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("amount", self.amount_command))
        self.application.add_handler(CommandHandler("report_weekly", self.report_weekly_command)) # أمر جديد
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))
        
    async def send_message(self, text: str) -> bool:
        """
        إرسال رسالة عبر Telegram، مع تقسيمها إذا كانت طويلة جداً.
        
        Args:
            text: نص الرسالة
            
        Returns:
            True إذا تم الإرسال بنجاح
        """
        # الحد الأقصى لرسالة Telegram هو 4096 حرفاً، نستخدم 3500 كحد آمن
        MAX_MESSAGE_LENGTH = 3500
        
        # تقسيم الرسالة إلى أجزاء مع معالجة وسم <code>
        messages = []
        current_index = 0
        
        while current_index < len(text):
            end_index = min(current_index + MAX_MESSAGE_LENGTH, len(text))
            chunk = text[current_index:end_index]
            
            # إذا كان الجزء ينتهي في منتصف وسم <code>، نبحث عن أقرب فاصل آمن (نهاية سطر)
            if chunk.count('<code>') != chunk.count('</code>'):
                # نبحث عن آخر نهاية سطر آمنة قبل نهاية الجزء
                safe_end = chunk.rfind('\n')
                
                if safe_end != -1 and safe_end > MAX_MESSAGE_LENGTH - 500:
                    end_index = current_index + safe_end
                    chunk = text[current_index:end_index]
                
                # إذا كان الجزء لا يزال غير متوازن، نقوم بإغلاق الوسم وفتحه في الجزء التالي
                if chunk.count('<code>') > chunk.count('</code>'):
                    chunk += '</code>'
                    messages.append(chunk)
                    current_index = end_index
                    
                    # الجزء التالي يجب أن يبدأ بفتح الوسم
                    if current_index < len(text):
                        messages.append('<code>' + text[current_index:])
                        current_index = len(text)
                    break
                
            messages.append(chunk)
            current_index = end_index
            
        success = True
        for msg in messages:
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=msg,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"❌ فشل إرسال رسالة Telegram: {e}")
                success = False
                
        return success

    async def send_welcome_message(self):
        """
        إرسال رسالة ترحيب فخمة مع قائمة الأوامر
        """
        message = (
            "أيها المدير العام 🫡\n\n"            "تم تفعيل منظومة 'Omega Predator'.\n"            "النظام الآن يراقب جميع أزواج التداول على منصة MEXC.\n\n"            "⚙️ <b>قائمة الأوامر:</b>\n"            "• /start - عرض هذه الرسالة وتأكيد حالة التشغيل.\n"            "• /amount [المبلغ] - تحديد مبلغ الشراء بالدولار لكل صفقة.\n"            "• /report_weekly - طلب تقرير بأداء الصفقات لآخر 7 أيام.\n\n"            "في انتظار أوامرك."
        )
        await self.send_message(message)

    async def confirm_amount(self, amount: float):
        """
        تأكيد استلام مبلغ الصفقة
        """
        await self.send_message(
            f"✅ <b>مفهوم</b>\n\n"
            f"سيتم تنفيذ كل صفقة شراء بمبلغ <b>${amount:.2f}</b>\n\n"
            f"🎯 <b>Omega Predator</b> الآن في وضع الصيد."
        )

    # --- معالجات الأوامر ---
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالجة أمر /start"""
        if str(update.effective_chat.id) != self.chat_id:
            await update.message.reply_text("❌ غير مصرح لك باستخدام هذا البوت.")
            return
        await self.send_welcome_message()

    async def amount_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالجة أمر /amount"""
        if str(update.effective_chat.id) != self.chat_id:
            await update.message.reply_text("❌ غير مصرح لك باستخدام هذا البوت.")
            return
            
        try:
            if not context.args:
                await update.message.reply_text("⚠️ يرجى تحديد المبلغ. مثال: <code>/amount 100</code>", parse_mode='HTML')
                return
                
            amount = float(context.args[0])
            if amount > 0:
                config.TRADE_AMOUNT_USD = amount
                await self.confirm_amount(amount)
                
                if self.on_amount_set:
                    await self.on_amount_set(amount)
            else:
                await update.message.reply_text("⚠️ يجب أن يكون المبلغ أكبر من صفر.")
        except ValueError:
            await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح بعد الأمر /amount")
        except Exception as e:
            logger.error(f"خطأ في معالجة أمر /amount: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء معالجة الأمر.")

        async def report_weekly_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            """معالجة أمر /report_weekly"""
            if str(update.effective_chat.id) != self.chat_id:
                await update.message.reply_text("❌ غير مصرح لك باستخدام هذا البوت.")
                return
            
            # هذا الأمر غير مبرمج حالياً، يتم إرسال رسالة توضيحية
            await update.message.reply_text("⚠️ <b>الأمر قيد التنفيذ.</b>\n\n"
                                            "سيتم تفعيل وظيفة تقرير الأداء الأسبوعي في الإصدارات القادمة.", parse_mode='HTML')
    
        async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            """معالجة الرسائل النصية غير الأوامر"""
            if str(update.effective_chat.id) != self.chat_id:
                return
            
            # يمكن إضافة منطق إضافي هنا لمعالجة الرسائل النصية إذا لزم الأمر
            await update.message.reply_text("⚠️ أمر غير معروف. يرجى استخدام الأوامر المتاحة.")
    
        # --- وظائف الإشعارات (تبقى كما هي) ---
        async def notify_buy(self, symbol: str, price: float, quantity: float, amount: float):
        """إشعار بتنفيذ أمر شراء"""
        await self.send_message(
            f"🟢 <b>تم تنفيذ أمر شراء</b>\n\n"
            f"العملة: <code>{symbol}</code>\n"
            f"السعر: <code>${price:.8f}</code>\n"
            f"الكمية: <code>{quantity:.6f}</code>\n"
            f"المبلغ: <code>${amount:.2f}</code>"
        )
    
    async def notify_sell(self, symbol: str, buy_price: float, sell_price: float, 
                         quantity: float, profit_loss: float, profit_percent: float):
        """إشعار بتنفيذ أمر بيع"""
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
        """إشعار بحدوث خطأ"""
        await self.send_message(f"❌ <b>خطأ</b>\n\n{error_message}")

        # دالة وهمية للحفاظ على التوافق مع main.py
        async def stop(self):
            pass

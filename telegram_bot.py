import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import config
from strategy import OmegaStrategy

logger = logging.getLogger("TelegramBot")

class TelegramBot:
    def __init__(self, strategy: OmegaStrategy):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.allowed_chat_id = str(config.TELEGRAM_CHAT_ID)
        self.strategy = strategy
        self.app = ApplicationBuilder().token(self.token).build()

    async def _check_auth(self, update: Update):
        if str(update.effective_chat.id) != self.allowed_chat_id:
            await update.message.reply_text("⛔ Access Denied.")
            return False
        return True

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        
        await update.message.reply_text(
            "🦅 <b>OMEGA PREDATOR ONLINE</b>\n"
            "سيدي مارك، تم تفعيل 'Omega Predator'.\n"
            "⚠️ <b>مطلوب إجراء فوري:</b> يرجى تحديد مبلغ الشراء بالدولار (USD) لكل صفقة (أرسل الرقم فقط).",
            parse_mode="HTML"
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        
        text = update.message.text
        
        # إذا كانت الاستراتيجية غير مفعلة، نتوقع رقم المبلغ
        if not self.strategy.active:
            try:
                amount = float(text)
                self.strategy.set_trade_amount(amount)
                await update.message.reply_text(
                    f"🫡 مفهوم. سيتم تنفيذ كل صفقة شراء بمبلغ <b>{amount}$</b>.\n"
                    "🌪️ 'Omega Predator' الآن في وضع الصيد.",
                    parse_mode="HTML"
                )
            except ValueError:
                await update.message.reply_text("❌ الرجاء إرسال رقم صحيح للمبلغ.")
        else:
            await update.message.reply_text("🤖 النظام يعمل. استخدم /status للتقرير.")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update): return
        
        status_msg = "📊 <b>STATUS REPORT</b>\n"
        for symbol, state in self.strategy.trade_state.items():
            status_msg += f"🔸 {symbol}: {state['status']}"
            if state['status'] == 'HOLDING':
                status_msg += f" (Peak: {state['peak_price']})"
            status_msg += "\n"
        
        if not self.strategy.trade_state:
            status_msg += "No active tracking yet."

        await update.message.reply_text(status_msg, parse_mode="HTML")

    async def send_notification(self, message):
        """إرسال إشعار غير متزامن للسيد مارك"""
        try:
            await self.app.bot.send_message(chat_id=self.allowed_chat_id, text=message)
        except Exception as e:
            print(f"Failed to send telegram alert: {e}")

    def run(self):
        # تسجيل المعالجات
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_message))
        
        # ملاحظة: سيتم تشغيل البوت داخل Main Loop باستخدام initialize و start/stop
        return self.app
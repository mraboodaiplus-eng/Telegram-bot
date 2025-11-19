from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from config import Config
import logging

logger = logging.getLogger("TelegramBot")

class OmegaBot:
    def __init__(self, strategy_instance):
        self.strategy = strategy_instance
        self.application = ApplicationBuilder().token(Config.TELEGRAM_BOT_TOKEN).build()
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_message))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != Config.TELEGRAM_CHAT_ID: return
        await update.message.reply_text("أوميغا جاهز. أرسل مبلغ التداول بالدولار للبدء (مثال: 50).")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != Config.TELEGRAM_CHAT_ID: return
        text = update.message.text.strip()
        
        if not self.strategy.is_running:
            try:
                amount = float(text)
                self.strategy.set_trade_amount(amount)
                await update.message.reply_text(f"تم. سيتم الدخول بـ {amount}$ لكل صفقة. المسح الشامل بدأ 🦅.")
            except ValueError:
                await update.message.reply_text("رقم غير صحيح.")
        else:
            await update.message.reply_text("النظام يعمل. استخدم /status.")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != Config.TELEGRAM_CHAT_ID: return
        count = len(self.strategy.active_trades)
        trades_list = "\n".join([f"- {s}: Peak {d['peak_price']}" for s, d in self.strategy.active_trades.items()])
        await update.message.reply_text(f"📊 الحالة: نشط\nالصفقات المفتوحة: {count}\n{trades_list}")

    async def send_message(self, text):
        try:
            await self.application.bot.send_message(chat_id=Config.TELEGRAM_CHAT_ID, text=text)
        except:
            pass

    async def start(self):
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
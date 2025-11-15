import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WHITELIST_SYMBOLS

# حالة البوت (يجب أن يتم تحديثها من main.py)
BOT_STATUS = {"running": False, "start_time": None, "usdt_amount": 10.0} # قيمة افتراضية 10 USDT

class TelegramBot:
    """
    واجهة تحكم آمنة ومباشرة للسيد مارك عبر Telegram.
    تطبيق مبدأ الشك الصفري: تجاهل أي أوامر من مستخدمين غير مصرح لهم.
    """
    def __init__(self, telegram_queue: asyncio.Queue):
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.telegram_queue = telegram_queue
        
        # إضافة المعالجات للأوامر الإلزامية
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("report_daily", self.report_daily_command))
        self.application.add_handler(CommandHandler("report_weekly", self.report_weekly_command))
        self.application.add_handler(CommandHandler("set_usdt_amount", self.set_usdt_amount_command))

    def _is_authorized(self, update: Update) -> bool:
        """التحقق من أن الأمر يأتي من TELEGRAM_CHAT_ID المحدد."""
        # يجب أن يكون TELEGRAM_CHAT_ID سلسلة نصية تمثل ID
        return str(update.effective_chat.id) == TELEGRAM_CHAT_ID

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """بدء تشغيل البوت."""
        if not self._is_authorized(update):
            return
        
        if BOT_STATUS["running"]:
            await update.message.reply_text("Omega Predator يعمل بالفعل.")
        else:
            # في بيئة الإنتاج، يجب أن يتم إرسال إشارة إلى main.py لبدء التشغيل
            # لغرض هذا الكود، سنفترض أن main.py هو من يتحكم في حالة التشغيل
            BOT_STATUS["running"] = True
            await update.message.reply_text("Omega Predator: تم تفعيل وضع التشغيل (Running).")

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """إيقاف تشغيل البوت."""
        if not self._is_authorized(update):
            return
        
        if not BOT_STATUS["running"]:
            await update.message.reply_text("Omega Predator متوقف بالفعل.")
        else:
            # في بيئة الإنتاج، يجب أن يتم إرسال إشارة إلى main.py لإيقاف التشغيل
            BOT_STATUS["running"] = False
            await update.message.reply_text("Omega Predator: تم تفعيل وضع الإيقاف (Stopped).")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """عرض حالة البوت."""
        if not self._is_authorized(update):
            return
        
        status_text = "✅ Running" if BOT_STATUS["running"] else "❌ Stopped"
        
        # يجب أن يتم استرداد هذه المعلومات من StrategyEngine في بيئة الإنتاج
        # لغرض هذا الكود، سنكتفي بعرض الحالة الأساسية
        message = (
            f"**Omega Predator Status**\n"
            f"Status: {status_text}\n"
            f"MEXC Symbols: {', '.join(WHITELIST_SYMBOLS)}\n"
            f"Strategy: 5% Rise (20s) -> BUY | 3% Drawdown -> SELL\n"
            f"USDT Amount per Trade: ${BOT_STATUS['usdt_amount']:.2f}"
        )
        await update.message.reply_text(message, parse_mode='Markdown')

    async def report_daily_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """تقرير الأداء اليومي."""
        if not self._is_authorized(update):
            return
        
        # يجب أن يتم استرداد هذا التقرير من StrategyEngine
        await update.message.reply_text("تقرير الأداء اليومي: (قيد التنفيذ - سيتم تفعيله عند دمج StrategyEngine)")

    async def report_weekly_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """تقرير الأداء الأسبوعي."""
        if not self._is_authorized(update):
            return
        
        # يجب أن يتم استرداد هذا التقرير من StrategyEngine
        await update.message.reply_text("تقرير الأداء الأسبوعي: (قيد التنفيذ - سيتم تفعيله عند دمج StrategyEngine)")

    async def set_usdt_amount_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """تحديد حجم الصفقة بالدولار الأمريكي (USDT)."""
        if not self._is_authorized(update):
            return

        try:
            if not context.args or len(context.args) != 1:
                await update.message.reply_text(
                    "الاستخدام: /set_usdt_amount <المبلغ_بالدولار>\n"
                    "مثال: /set_usdt_amount 10"
                )
                return

            new_amount = float(context.args[0])
            if new_amount <= 0:
                await update.message.reply_text("يجب أن يكون المبلغ أكبر من الصفر.")
                return

            BOT_STATUS["usdt_amount"] = new_amount
            await update.message.reply_text(
                f"تم تحديث حجم الصفقة بنجاح.\n"
                f"حجم الصفقة الحالي: ${new_amount:.2f}"
            )
        except ValueError:
            await update.message.reply_text("خطأ: يرجى إدخال رقم صحيح للمبلغ.")

    async def send_message_task(self):
        """مهمة غير متزامنة لإرسال الرسائل من قائمة الانتظار."""
        while True:
            message = await self.telegram_queue.get()
            try:
                await self.application.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
            except Exception as e:
                print(f"Error sending Telegram message: {e}")
            finally:
                self.telegram_queue.task_done()

    async def run(self):
        """تشغيل البوت بشكل غير متزامن."""
        # استخدام start/stop/update_queue بشكل صريح لتجنب تضارب حلقات asyncio
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(poll_interval=1)

    async def stop(self):
        """إيقاف تشغيل البوت بشكل غير متزامن."""
        await self.application.updater.stop()
        await self.application.stop()

# ملاحظة: سيتم تشغيل run_polling و send_message_task في main.py بشكل متزامن.

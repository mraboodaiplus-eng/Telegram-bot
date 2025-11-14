import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
    
# إعداد تسجيل الأحداث الأساسي
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
    
# دالة لمعالجة أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ترسل رسالة ترحيب عند إرسال أمر /start."""
    user = update.effective_user
    welcome_message = (
        f" مرحباً {user.mention_html()}!\n\n"
        "أنا بوت Alpha Predator، في مرحلة الإعداد الأولي.\n"
        "الاتصال ناجح!"
    )
    await update.message.reply_html(welcome_message)
    logger.info(f"المستخدم {user.id} بدأ استخدام البوت.")
    
def main() -> None:
    """تبدأ تشغيل البوت."""
    # الحصول على توكن البوت من متغيرات البيئة
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN:
        logger.error("خطأ: متغير البيئة TELEGRAM_TOKEN غير موجود!")
        return
    
    # إنشاء التطبيق وتمرير توكن البوت إليه
    application = Application.builder().token(TOKEN).build()
    
# تسجيل معالج أمر /start
    application.add_handler(CommandHandler("start", start))
    
# بدء تشغيل البوت
    logger.info("...جاري بدء تشغيل البوت")
    application.run_polling()
    
if __name__ == '__main__':
    main()

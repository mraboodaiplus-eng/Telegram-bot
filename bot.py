'''
# -*- coding: utf-8 -*-
# Standard Library
import asyncio
import os
import sys
import datetime
import logging
import math

# Third-party Libraries
import ccxt.async_support as ccxt
from flask import Flask
from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    ConversationHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    filters
)

# Local Imports
from database import (
    init_db, 
    get_user, 
    add_new_user, 
    update_subscription_status, 
    is_subscription_active, 
    setup_vip_api_keys, 
    update_api_keys
)

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Flask App (for Keep-Alive on Render.com) ---
app = Flask(__name__)

# --- CONFIGURATION AND CONSTANTS ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- User & Admin IDs ---
OWNER_ID = 7281928709
ABOOD_ID = 5991392622
WHITELISTED_USERS = [OWNER_ID, ABOOD_ID]
ADMIN_CHAT_ID = OWNER_ID
ADMIN_TITLE = "المدير العام"

# --- Subscription Details ---
USDT_ADDRESS = "0xb85f1c645dbb80f2617823c069dcb038a9f79895"
SUBSCRIPTION_PRICE = "10$ شهرياً (BEP20)"

# --- Conversation States ---
(AMOUNT, SYMBOL, PROFIT_PERCENT, USE_STOP_LOSS, STOP_LOSS_PERCENT, 
 WAITING_FOR_SCREENSHOT, API_KEY_STATE, API_SECRET_STATE) = range(8)

# ====================================================================
# BINGX TRADING LOGIC
# ====================================================================

def initialize_exchange(user_id, api_key, api_secret):
    if user_id == OWNER_ID:
        api_key = os.environ.get("BINGX_API_KEY")
        api_secret = os.environ.get("BINGX_API_SECRET")

    if not api_key or not api_secret:
        raise ValueError("لم يتم العثور على مفاتيح API. يرجى إعدادها أولاً باستخدام /set_api.")

    return ccxt.bingx({
        'apiKey': api_key,
        'secret': api_secret,
        'options': {'defaultType': 'spot'},
        'enableRateLimit': True,
    })

async def wait_for_listing(update: Update, context: ContextTypes.DEFAULT_TYPE, exchange, symbol):
    await update.message.reply_text(f"⏳ **[قيد القنص]** جاري البحث عن إدراج العملة **{symbol}**...")
    
    SNIPING_DELAY = 0.03  # Increased delay to 30ms to mitigate rate limit risks
    MAX_ATTEMPTS_BEFORE_RELOAD = 50 # Reload markets every 50 attempts (1.5 seconds)
    attempts = 0

    while True:
        attempts += 1
        try:
            # Periodically reload markets to get the absolute newest listings
            if attempts % MAX_ATTEMPTS_BEFORE_RELOAD == 0:
                logger.info(f"Reloading markets to find {symbol}...")
                await exchange.load_markets(reload=True)

            # Check if the symbol is now in the loaded markets
            if symbol in exchange.markets:
                # Fetch ticker to ensure it has a price
                ticker = await exchange.fetch_ticker(symbol)
                if ticker and ticker.get('last') is not None and ticker['last'] > 0:
                    await update.message.reply_text(f"✅ **[تم الإدراج بنجاح]**\n\nالعملة: **{symbol}** متاحة الآن للتداول!\nالسعر الحالي: **{ticker['last']} USDT**")
                    return True # Success

        except ccxt.BadSymbol:
            # This is expected, the symbol is not listed yet.
            pass
        except Exception as e:
            logger.error(f"Error during sniping wait for {symbol}: {e}")
            await asyncio.sleep(1) # Longer sleep on unexpected error
            
        await asyncio.sleep(SNIPING_DELAY)

async def execute_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    params = context.user_data
    
    # Fetch user from DB to get API keys
    user_record = await get_user(user_id)
    if not user_record or not user_record.get('api_key') or not user_record.get('api_secret'):
        await update.message.reply_text("🚨 **[خطأ فادح]** لم يتم العثور على مفاتيح API الخاصة بك. يرجى إدخالها أولاً باستخدام /set_api.")
        return ConversationHandler.END

    try:
        exchange = initialize_exchange(user_id, user_record['api_key'], user_record['api_secret'])
    except ValueError as e:
        await update.message.reply_text(f"🚨 **[خطأ في الاتصال]** {e}")
        return ConversationHandler.END

    symbol = params['symbol']
    amount_usdt = params['amount']
    profit_percent = params['profit_percent']
    stop_loss_percent = params.get('stop_loss_percent')

    try:
        await exchange.load_markets()
        await update.message.reply_text("🔗 **[معلومة]** تم تحميل الأسواق بنجاح.")
        await update.message.reply_text(f"🛒 **[الخطوة 1/3]** جاري وضع أمر شراء Market لـ **{symbol}** بقيمة **{amount_usdt} USDT**...")

        market_buy_order = await exchange.create_order(symbol=symbol, type='market', side='buy', amount=None, params={'cost': amount_usdt})
        await update.message.reply_text(f"👍 **[نجاح]** تم وضع أمر الشراء. المعرف: `{market_buy_order['id']}`")

        await update.message.reply_text("🔍 **[الخطوة 2/3]** في انتظار تفاصيل التنفيذ...")
        await asyncio.sleep(3) # Wait for the order to be filled

        order_details = await exchange.fetch_order(market_buy_order['id'], symbol)

        if order_details.get('status') not in ['closed', 'filled'] or not order_details.get('average'):
            raise ccxt.ExchangeError("لم يتم تنفيذ أمر الشراء أو الحصول على تفاصيله. يرجى التحقق من حسابك في BingX.")

        avg_price = float(order_details['average'])
        filled_amount = float(order_details['filled'])

        await update.message.reply_text(f"📊 **[تفاصيل]** متوسط السعر: `{avg_price:.6f}`, الكمية: `{filled_amount:.6f}`")

        # --- STEP 3: Take Profit Limit Sell ---
        target_sell_price = avg_price * (1 + profit_percent / 100)
        await update.message.reply_text(f"🎯 **[الخطوة 3/3]** جاري وضع أمر بيع Limit لجني الأرباح (+{profit_percent}%) عند سعر **{target_sell_price:.6f}**...")
        
        # Ensure precision is correct
        market = exchange.markets[symbol]
        precision = market['precision']['amount']
        filled_amount_precise = math.floor(filled_amount * (10**precision)) / (10**precision)

        limit_sell_order = await exchange.create_limit_sell_order(symbol, filled_amount_precise, target_sell_price)
        await update.message.reply_text(f"📈 **[نجاح]** تم وضع أمر جني الأرباح. المعرف: `{limit_sell_order['id']}`")

        # --- OPTIONAL: Stop Loss Order ---
        if stop_loss_percent:
            stop_loss_price = avg_price * (1 - stop_loss_percent / 100)
            await update.message.reply_text(f"🛡️ **[إضافي]** جاري وضع أمر وقف الخسارة (-{stop_loss_percent}%) عند **{stop_loss_price:.6f}**...")
            stop_order = await exchange.create_order(symbol=symbol, type='stop_market', side='sell', amount=filled_amount_precise, params={'stopPrice': stop_loss_price})
            await update.message.reply_text(f"📉 **[نجاح]** تم وضع أمر وقف الخسارة. المعرف: `{stop_order['id']}`")
            await update.message.reply_text("‼️ **تحذير:** لديك أمران مفتوحان. قم بإلغاء الآخر يدويًا إذا تم تنفيذ أحدهما.")

    except ccxt.ExchangeError as e:
        await update.message.reply_text(f"🚨 **[خطأ من المنصة]** {e}")
    except Exception as e:
        await update.message.reply_text(f"🚨 **[خطأ حرج]** {type(e).__name__}: {e}")
    finally:
        if 'exchange' in locals():
            await exchange.close()
            await update.message.reply_text("🔌 **[معلومة]** تم إغلاق الاتصال بالمنصة.")
    
    context.user_data.clear()
    return ConversationHandler.END

# ====================================================================
# TELEGRAM HANDLERS & CONVERSATIONS
# ====================================================================

# --- Subscription Check & Start Command ---
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id in WHITELISTED_USERS:
        return True
        
    user_record = await get_user(user_id)
    if user_record and is_subscription_active(user_record):
        return True
    
    keyboard = [[InlineKeyboardButton(f"🚀 اشترك الآن ({SUBSCRIPTION_PRICE})", callback_data='subscribe_now')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔒 **الوصول مقيد.**\n\nهذه الخدمة متاحة فقط للمشتركين. حالة اشتراكك: **غير فعال** أو **منتهي**.",
        reply_markup=reply_markup
    )
    return False

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    await add_new_user(user_id) # Add user to DB if not exists

    if user_id == ABOOD_ID:
        await setup_vip_api_keys(ABOOD_ID, os.environ.get("ABOOD_API_KEY"), os.environ.get("ABOOD_API_SECRET"))
        
    if user_id == OWNER_ID:
            welcome_message = (
                f"👑 **أهلاً بك يا سيدي المدير العام ({username})!** 👑\n\n"
                "البوت تحت إمرتك. جميع الصلاحيات مفعلة.\n"
                "**الأوامر المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة البوت\n"
                "**أوامر الإدارة:**\n"
                "/approve [user_id] - ✅ تفعيل اشتراك مستخدم"
            )
        elif user_id == ABOOD_ID:
            welcome_message = (
                f"👋 **مرحباً بك يا {username} (المستخدم المميز)!** 👋\n\n"
                "أنت ضمن القائمة البيضاء، جميع الصلاحيات مفعلة.\n"
                "**الأوامر المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة البوت"
            )
    else:
        # Standard user
        user_record = await get_user(user_id)
        if user_record and is_subscription_active(user_record):
            end_date = user_record['subscription_end_date']
            welcome_message = (
                f"👋 مرحباً بك يا {username}!\n\n"
                f"حالة اشتراكك: **نشط** (ينتهي في: {end_date})\n\n"
                "**الأوامر المتاحة:** /trade, /sniping, /set_api, /status, /cancel"
            )
        else:
            keyboard = [[InlineKeyboardButton(f"🚀 اشترك الآن ({SUBSCRIPTION_PRICE})", callback_data='subscribe_now')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"👋 مرحباً بك يا {username}!\n\nأهلاً بك في خدمة **LiveSniperBot**. للاستفادة من خدمات التداول والقنص، يرجى الاشتراك.",
                reply_markup=reply_markup
            )
            return

    await update.message.reply_text(welcome_message)

# --- Trade & Sniping Conversation ---
async def trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_subscription(update, context):
        return ConversationHandler.END
    context.user_data['is_sniping'] = False
    await update.message.reply_text("📈 **بدء التداول**\n\n1. 💰 أدخل المبلغ (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

async def sniping_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_subscription(update, context):
        return ConversationHandler.END
    context.user_data['is_sniping'] = True
    await update.message.reply_text("⚡️ **بدء القنص**\n\n1. 💰 أدخل المبلغ (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data['amount'] = float(update.message.text)
        await update.message.reply_text("2. 🪙 أدخل رمز العملة (مثال: BTC/USDT):", reply_markup=ForceReply(selective=True))
        return SYMBOL
    except ValueError:
        await update.message.reply_text("❌ إدخال خاطئ. يرجى إدخال رقم.")
        return AMOUNT

async def get_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    symbol = update.message.text.strip().upper()
    if '/' not in symbol:
        symbol += '/USDT'
    context.user_data['symbol'] = symbol
    await update.message.reply_text("3. 📈 أدخل نسبة الربح المستهدفة (%):", reply_markup=ForceReply(selective=True))
    return PROFIT_PERCENT

async def get_profit_percent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data['profit_percent'] = float(update.message.text)
        keyboard = [[InlineKeyboardButton("✅ نعم", callback_data='sl_yes'), InlineKeyboardButton("❌ لا", callback_data='sl_no')]]
        await update.message.reply_text("4. 🛡️ هل تريد استخدام وقف الخسارة؟", reply_markup=InlineKeyboardMarkup(keyboard))
        return USE_STOP_LOSS
    except ValueError:
        await update.message.reply_text("❌ إدخال خاطئ. يرجى إدخال رقم.")
        return PROFIT_PERCENT

async def get_stop_loss_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'sl_yes':
        await query.edit_message_text("5. 📉 أدخل نسبة وقف الخسارة (%):")
        return STOP_LOSS_PERCENT
    else:
        context.user_data['stop_loss_percent'] = None
        await query.edit_message_text("✅ تم جمع البيانات. جاري تنفيذ العملية...")
        
        # Determine which update object to pass (original message or callback query)
        # For simplicity and to avoid passing a query object to a function expecting an update message:
        # We will re-fetch the message update object if needed, but for now, pass the current update.
        
        if context.user_data.get('is_sniping'):
            asyncio.create_task(run_sniping_flow(update, context))
        else:
            asyncio.create_task(execute_trade(update, context))
            
        return ConversationHandler.END

async def get_stop_loss_percent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data['stop_loss_percent'] = float(update.message.text)
        await update.message.reply_text("✅ تم جمع البيانات. جاري تنفيذ العملية...")
        if context.user_data.get('is_sniping'):
            asyncio.create_task(run_sniping_flow(update, context))
        else:
            asyncio.create_task(execute_trade(update, context))
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ إدخال خاطئ. يرجى إدخال رقم.")
        return STOP_LOSS_PERCENT

async def run_sniping_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Use a temporary exchange for sniping check to avoid auth issues
    temp_exchange = ccxt.bingx()
    try:
        is_listed = await wait_for_listing(update, context, temp_exchange, context.user_data['symbol'])
    finally:
        await temp_exchange.close()
    
    if is_listed:
        # Now execute the trade with user's authenticated exchange
        await execute_trade(update, context)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text('❌ تم إلغاء العملية.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- API Key Conversation ---
async def set_api_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("🔑 **إعداد مفاتيح API**\n\n1. أرسل **API Key**:", reply_markup=ForceReply(selective=True))
    return API_KEY_STATE

async def get_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['api_key'] = update.message.text.strip()
    await update.message.reply_text("2. أرسل **API Secret**:", reply_markup=ForceReply(selective=True))
    return API_SECRET_STATE

async def get_api_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    api_secret = update.message.text.strip()
    api_key = context.user_data['api_key']
    await update_api_keys(update.effective_user.id, api_key, api_secret)
    await update.message.reply_text("✅ **تم حفظ مفاتيح API بنجاح!**")
    context.user_data.clear()
    return ConversationHandler.END

# --- Subscription Conversation ---
async def subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"💳 **تفاصيل الاشتراك - {SUBSCRIPTION_PRICE}**\n\n"
        f"للاشتراك، حول **{SUBSCRIPTION_PRICE}** إلى العنوان التالي:\n"
        f"**العنوان (USDT - BEP20):**\n`{USDT_ADDRESS}`\n\n"
        "بعد التحويل، أرسل **لقطة شاشة** كإثبات."
    )
    return WAITING_FOR_SCREENSHOT

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not update.message.photo:
        await update.message.reply_text("❌ لم يتم إرسال صورة. يرجى إرسال لقطة شاشة.")
        return WAITING_FOR_SCREENSHOT

    photo_file_id = update.message.photo[-1].file_id
    keyboard = [[InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f'approve_{user.id}')]]
    admin_message = (
        f"🔔 **طلب اشتراك جديد للمراجعة** 🔔\n"
        f"**العميل:** {user.first_name} (@{user.username or 'N/A'})\n"
        f"**معرف العميل:** `{user.id}`"
    )
    
    await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=photo_file_id, caption=admin_message, reply_markup=InlineKeyboardMarkup(keyboard))
    await update.message.reply_text("✅ **تم استلام الإثبات!** جاري المراجعة من قبل المدير.")
    return ConversationHandler.END

# --- Admin & Status Commands ---
async def approve_subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ الاستخدام: /approve [user_id]")
        return
    
    target_user_id = int(context.args[0])
    end_date = datetime.datetime.now() + datetime.timedelta(days=30)
    await update_subscription_status(target_user_id, status='active', end_date=end_date.strftime("%Y-%m-%d"))
    
    await context.bot.send_message(chat_id=target_user_id, text="🎉 **تهانينا! تم تفعيل اشتراكك بنجاح!**")
    await update.message.reply_text(f"✅ تم تفعيل اشتراك المستخدم `{target_user_id}` بنجاح.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in WHITELISTED_USERS:
        status_text = "👑 **حالة المستخدم:** القائمة البيضاء (وصول كامل ودائم)."
    else:
        user_record = await get_user(user_id)
        if user_record and is_subscription_active(user_record):
            status_text = f"✅ **حالة الاشتراك:** نشط (ينتهي في: {user_record['subscription_end_date']})"
        else:
            status_text = "❌ **حالة الاشتراك:** غير فعال."
    await update.message.reply_text(status_text)

# ====================================================================
# MAIN FUNCTION & BOT SETUP
# ====================================================================

def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("FATAL ERROR: TELEGRAM_BOT_TOKEN is not set.")
        sys.exit(1)

    # Initialize Database
    asyncio.run(init_db())

    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # --- Conversation Handlers ---
    trade_conv = ConversationHandler(
        entry_points=[CommandHandler("trade", trade_start), CommandHandler("sniping", sniping_start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_symbol)],
            PROFIT_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_profit_percent)],
            USE_STOP_LOSS: [CallbackQueryHandler(get_stop_loss_choice)],
            STOP_LOSS_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stop_loss_percent)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        per_message=False
    )

    api_conv = ConversationHandler(
        entry_points=[CommandHandler("set_api", set_api_start)],
        states={
            API_KEY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_api_key)],
            API_SECRET_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_api_secret)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    sub_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(subscribe_callback, pattern='^subscribe_now$')],
        states={
            WAITING_FOR_SCREENSHOT: [MessageHandler(filters.PHOTO, receive_screenshot)]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    # --- Add handlers to application ---
    application.add_handler(trade_conv)
    application.add_handler(api_conv)
    application.add_handler(sub_conv)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("approve", approve_subscription_command))
    application.add_handler(CommandHandler("cancel", cancel_command)) # Global cancel

    # --- Start Bot ---
    logger.info("Bot is starting in Polling mode...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
'''

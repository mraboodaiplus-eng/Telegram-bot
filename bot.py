# -*- coding: utf-8 -*-
from flask import Flask
from threading import Thread
import ccxt.async_support as ccxt
import asyncio
import os
import sys
import datetime
from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters

# --- NEW IMPORTS ---
# Assuming database.py is available and contains the required functions
from database import init_db, get_user, add_new_user, update_subscription_status, is_subscription_active, setup_vip_api_keys

# === WEB SERVER SETUP FOR RENDER.COM (Kept for compatibility) ===
app = Flask(__name__)

@app.route('/')
def home():
    return "I'm alive and running!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def start_web_server_thread():
    web_thread = Thread(target=run_web_server)
    web_thread.start()
# ========================================

# --- CONFIGURATION AND CONSTANTS (Reverted to placeholders for secure delivery) ---
# --- CONFIGURATION AND CONSTANTS (Updated with real values) ---
# NOTE: The user must set TELEGRAM_BOT_TOKEN environment variable before running the bot
TELEGRAM_BOT_TOKEN = "8282457564:AAE0hzkFVdLrhU3426iJDUr0JMG5DkloEFE"

# Owner's Real Information (Hardcoded for simplicity as requested by user)
OWNER_ID = 7281928709
BINGX_API_KEY = "M1OSlqx9F5TQD7eBxmitch4NLw9ZPpD9Xng28REiwDJe9bunCp8mPvu5GoV9QLJ3NIAO2b0YZu8GszVlIcaxw"
BINGX_API_SECRET = "ybuQhV2CzYrvJx9wnAH4gq01z25b2FZDtZguc89zCKaOfHO4NT9IlGxaPsDmgsbVvjl4M1ammvBOVHJ4fIaw"

# ABOOD's Real Information (Hardcoded for simplicity as requested by user)
ABOOD_ID = 5991392622
ABOOD_API_KEY = "bg_ec710cae5f25832f2476b517b605bb4a"
ABOOD_API_SECRET = "faca6ac6f1060c0c0a362a361af42c50b0b052a81572e248311047b4dc53870cd"

# Whitelisted users (Owner and friends)
WHITELISTED_USERS = [OWNER_ID, ABOOD_ID]
# Admin Chat ID (Where approval requests are sent) - Owner is the admin
ADMIN_CHAT_ID = OWNER_ID 
ADMIN_TITLE = "المدير العام" # Title for the Admin

# Payment Details (Updated to real BEP20 address)
USDT_ADDRESS = "0xb85f1c645dbb80f2617823c069dcb038a9f79895"
SUBSCRIPTION_PRICE = "10$ شهرياً (BEP20)"

# The old environment variables are no longer used for these values
ALLOWED_USER_ID = str(OWNER_ID) # Kept for compatibility with old code logic if any


# Conversation States
AMOUNT, SYMBOL, PROFIT_PERCENT, USE_STOP_LOSS, STOP_LOSS_PERCENT = range(5)
# NEW Conversation States for Subscription
WAITING_FOR_SCREENSHOT = 50

# BINGX TRADING LOGIC
def initialize_exchange(user_id, api_key, api_secret):
    """Initializes the BingX exchange object with provided API keys."""

    # Special case: If user is the OWNER, use the hardcoded keys
    if user_id == OWNER_ID:
        api_key = BINGX_API_KEY
        api_secret = BINGX_API_SECRET
        
    if not api_key or not api_secret:
        raise ValueError("API Key or Secret is missing. Please use /set_api.")
        
    return ccxt.bingx({
        'apiKey': api_key,
        'secret': api_secret,
        'options': {'defaultType': 'spot'},
        'enableRateLimit': True,
    })

async def wait_for_listing(update: Update, context: ContextTypes.DEFAULT_TYPE, exchange, symbol):
    await update.message.reply_text(f"⏳ [SNIPING MODE] جاري انتظار إدراج العملة {symbol}...")
    SNIPING_DELAY = 0.03
    while True:
        try:
            ticker = await exchange.fetch_ticker(symbol)
            if ticker:
                await update.message.reply_text(f"✅ [SUCCESS] {symbol} is now listed! Current price: {ticker['last']}")
                return
        except ccxt.BadSymbol:
            await asyncio.sleep(SNIPING_DELAY)
        except Exception as e:
            await update.message.reply_text(f"⚠️ [WARNING] Sniping Error: {type(e).__name__}: {e}")
            await asyncio.sleep(5)

async def execute_trade(update: Update, context: ContextTypes.DEFAULT_TYPE, params):
    user_id = update.effective_user.id
    user_record = await get_user(user_id)
    
    if not user_record or not user_record['api_key'] or not user_record['api_secret']:
        await update.message.reply_text("🚨 [ERROR] لم يتم العثور على مفاتيح API الخاصة بك. يرجى إدخالها أولاً.")
        return

    try:
        # Pass user_id to initialize_exchange to handle the OWNER_ID case
        exchange = initialize_exchange(user_id, user_record['api_key'], user_record['api_secret'])
    except ValueError as e:
        await update.message.reply_text(f"🚨 [ERROR] خطأ في تهيئة الاتصال: {e}")
        return
        
    symbol = params['symbol']
    amount_usdt = params['amount']
    profit_percent = params['profit_percent']
    stop_loss_percent = params['stop_loss_percent']
        
    try:
        await exchange.load_markets()
        await update.message.reply_text("🔗 [INFO] Markets loaded successfully.")
        await update.message.reply_text(f"🛒 [STEP 1/3] Placing Market Buy Order for {symbol} with cost {amount_usdt} USDT...")
        
        market_buy_order = await exchange.create_order(
            symbol=symbol,
            type='market',
            side='buy',
            amount=None,
            price=None,
            params={'cost': amount_usdt}
        )
        
        await update.message.reply_text(f"👍 [SUCCESS] Buy Order placed. ID: {market_buy_order['id']}")
        
        # --- FIX 2: Better order detail fetching and handling ---
        await update.message.reply_text("🔍 [STEP 2/3] Waiting for execution details...")
        await asyncio.sleep(2) 
        
        order_details = await exchange.fetch_order(market_buy_order['id'], symbol)
        
        if order_details.get('status') not in ['closed', 'filled']:
            trades = await exchange.fetch_my_trades(symbol, since=None, limit=None, params={'order': market_buy_order['id']})
            
            if not trades:
                 raise ccxt.ExchangeError("Market order was not filled and no trades were found.")
            
            filled_amount = sum(float(trade['amount']) for trade in trades)
            total_cost = sum(float(trade['cost']) for trade in trades)
            avg_price = total_cost / filled_amount if filled_amount else 0
            
            if not avg_price or not filled_amount:
                raise ccxt.ExchangeError("Failed to get execution details from order or trades.")
            
        else:
            avg_price = float(order_details['average'])
            filled_amount = float(order_details['filled'])

            if not avg_price or not filled_amount:
                raise ccxt.ExchangeError("Failed to get execution details.")
        
        await update.message.reply_text(f"📊 [DETAILS] Avg Price: {avg_price:.6f}, Quantity: {filled_amount:.6f}")
        
        # --- STEP 3: Take Profit Limit Sell ---
        target_sell_price = avg_price * (1 + profit_percent / 100)
        await update.message.reply_text(f"🎯 [STEP 3/3] Placing Take Profit Limit Sell (+{profit_percent}%) at {target_sell_price:.6f}...")
        
        if symbol not in exchange.markets:
            raise ccxt.BadSymbol(f"Symbol {symbol} is not available on {exchange.id}.")
            
        market = exchange.markets[symbol]
        precision = market['precision']['amount']
        
        import math
        filled_amount_precise = math.floor(filled_amount * (10**precision)) / (10**precision)
        
        limit_sell_order = await exchange.create_limit_sell_order(symbol, filled_amount_precise, target_sell_price)
        await update.message.reply_text(f"📈 [SUCCESS] Take Profit Order placed. ID: {limit_sell_order['id']}")
        
        # --- OPTIONAL: Stop Loss Order ---
        if params['use_stop_loss']:
            stop_loss_price = avg_price * (1 - stop_loss_percent / 100)
            await update.message.reply_text(f"🛡️ [OPTIONAL] Placing Stop Loss Order (-{stop_loss_percent}%) at {stop_loss_price:.6f}...")
            
            stop_order = await exchange.create_order(
                symbol=symbol,
                type='stop_market',
                side='sell',
                amount=filled_amount_precise,
                price=None,
                params={'stopPrice': stop_loss_price}
            )
            
            await update.message.reply_text(f"📉 [SUCCESS] Stop Loss Order placed. ID: {stop_order['id']}")
            await update.message.reply_text("‼️ WARNING: TWO OPEN ORDERS ‼️\nManually cancel the other order if one executes. (Take Profit is Limit, Stop Loss is Market Stop)")
            
    except ccxt.ExchangeError as e:
        await update.message.reply_text(f"🚨 [EXCHANGE ERROR] {type(e).__name__}: {e}")
    except ccxt.NetworkError as e:
        await update.message.reply_text(f"🚨 [NETWORK ERROR] {type(e).__name__}: {e}")
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] {type(e).__name__}: {e}")
    finally:
        if 'exchange' in locals():
            await exchange.close()
            await update.message.reply_text("🔌 [INFO] Connection closed.")

async def sniping_and_trade(update: Update, context: ContextTypes.DEFAULT_TYPE, params):
    await update.message.reply_text("⚡️ [SNIPING MODE] Starting Sniping process...")
    
    temp_exchange = ccxt.bingx({'enableRateLimit': True})
    
    # 1. Wait for listing (Sniping)
    try:
        await wait_for_listing(update, context, temp_exchange, params['symbol'])
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] Failed during sniping wait: {e}")
        await temp_exchange.close()
        return
    finally:
        await temp_exchange.close()

    # 2. Execute trade (This will initialize a new exchange with user's keys)
    await execute_trade(update, context, params) 

# --- NEW: Subscription Check Decorator/Function ---
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks if the user is whitelisted or has an active subscription."""
    user_id = update.effective_user.id
    
    # 1. Check Whitelist
    if user_id in WHITELISTED_USERS:
        return True
        
    # 2. Check Database Subscription Status
    user_record = await get_user(user_id)
    
    if user_record and is_subscription_active(user_record):
        return True
    
    # 3. Deny Access
    keyboard = [[InlineKeyboardButton("🚀 اشترك الآن ({})".format(SUBSCRIPTION_PRICE), callback_data='subscribe_now')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔒 **الوصول مقيد.**\n\n"
        "هذه الخدمة متاحة فقط للمشتركين النشطين.\n"
        "حالة اشتراكك: **غير فعال** أو **منتهي**.\n\n"
        "يرجى الاشتراك لتتمكن من استخدام أوامر التداول.",
        reply_markup=reply_markup
    )
    return False

# --- TELEGRAM HANDLERS (Modified) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    # Ensure user is in DB (for all non-whitelisted users)
    await add_new_user(user_id)
    
    # --- NEW: Auto-setup VIP API Keys for ABOOD ---
    if user_id == ABOOD_ID:
        await setup_vip_api_keys(ABOOD_ID, ABOOD_API_KEY, ABOOD_API_SECRET)
        
    # 1. Check Whitelist
    if user_id in WHITELISTED_USERS:
        # Custom Welcome Logic
        if user_id == OWNER_ID:
            welcome_message = (
                f"👑 أهلاً بك يا سيدي المدير العام ({username})! 👑\n\n"
                "البوت تحت إمرتك. جميع الصلاحيات مفعلة.\n"
                "**الأوامر المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة البوت"
            )
        elif user_id == ABOOD_ID:
            welcome_message = (
                f"👋 مرحباً بك يا Abood ({username})! 👋\n\n"
                "أنت ضمن القائمة البيضاء، جميع الصلاحيات مفعلة.\n"
                "**الأوامر المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة البوت"
            )
        else:
            # Fallback for any other whitelisted user if the list is expanded
            welcome_message = (
                f"👋 مرحباً بك يا {username} (المستخدم المميز)!\n\n"
                "**الأوامر المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة الاشتراك"
            )
        
        await update.message.reply_text(welcome_message)
        return
        
    # 2. Check Subscription Status for Clients
    user_record = await get_user(user_id)
    
    if user_record and is_subscription_active(user_record):
        # Active Client
        await update.message.reply_text(
            f"👋 مرحباً بك يا {username} (العميل المشترك)!\n\n"
            f"حالة اشتراكك: **نشط**، ينتهي في: {user_record['subscription_end_date']}\n\n"
            "**الأوامر المتاحة:**\n"
            "/trade - 📈 تداول عادي (شراء وبيع)\n"
            "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
            "/cancel - ❌ إلغاء العملية الحالية\n"
            "/set_api - 🔑 إعداد مفاتيح API\n"
            "/status - ℹ️ عرض حالة الاشتراك"
        )
    else:
        # Inactive Client - Show Subscription Button
        keyboard = [[InlineKeyboardButton("🚀 اشترك الآن ({})".format(SUBSCRIPTION_PRICE), callback_data='subscribe_now')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👋 مرحباً بك يا {username}!\n\n"
            "أهلاً بك في خدمة **LiveSniperBot** المتميزة.\n"
            "للاستفادة من خدمات التداول والقنص الآلي، يرجى الاشتراك في الخدمة.\n\n"
            "حالة اشتراكك: **غير فعال**.",
            reply_markup=reply_markup
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_record = await get_user(user_id)
    
    if user_id in WHITELISTED_USERS:
        await update.message.reply_text("ℹ️ **حالة المستخدم:**\n\n"
                                        "نوع المستخدم: **مميز (Whitelist)**\n"
                                        "حالة الاشتراك: **نشط دائماً**")
        return
        
    if not user_record:
        await update.message.reply_text("ℹ️ **حالة المستخدم:**\n\n"
                                        "لم يتم العثور على سجل لك. يرجى إرسال /start.")
        return
        
    status = "نشط" if is_subscription_active(user_record) else "غير فعال"
    end_date = user_record['subscription_end_date'] or "غير محدد"
    
    await update.message.reply_text(f"ℹ️ **حالة المستخدم:**\n\n"
                                    f"نوع المستخدم: **عميل**\n"
                                    f"حالة الاشتراك: **{status}**\n"
                                    f"تاريخ الانتهاء: **{end_date}**\n"
                                    f"مفاتيح API: **{'موجودة' if user_record['api_key'] else 'غير موجودة'}**")

async def trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check subscription before starting conversation
    if not await check_subscription(update, context):
        return ConversationHandler.END


        
    context.user_data['is_sniping'] = False
    await update.message.reply_text("1. 💰 أدخل مبلغ الشراء بالدولار الأمريكي (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

async def sniping_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check subscription before starting conversation
    if not await check_subscription(update, context):
        return ConversationHandler.END


        
    context.user_data['is_sniping'] = True
    await update.message.reply_text("1. ⚡️ أدخل مبلغ القنص بالدولار الأمريكي (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

# --- NEW: API Key Setting Conversation ---
async def set_api_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

        
    await update.message.reply_text("🔑 **إعداد مفاتيح API**\n\n"
                                    "1. يرجى إرسال **API Key** الخاص بك:", reply_markup=ForceReply(selective=True))
    return 1 # State for API Key

async def set_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['temp_api_key'] = update.message.text.strip()
    await update.message.reply_text("2. يرجى إرسال **API Secret** الخاص بك:", reply_markup=ForceReply(selective=True))
    return 2 # State for API Secret

async def set_api_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    api_secret = update.message.text.strip()
    api_key = context.user_data['temp_api_key']
    user_id = update.effective_user.id
    
    await update_api_keys(user_id, api_key, api_secret)
    
    await update.message.reply_text("✅ **تم حفظ مفاتيح API بنجاح!**\n"
                                    "يمكنك الآن استخدام أوامر التداول: /trade أو /sniping.")
    
    return ConversationHandler.END

# --- NEW: Subscription Handlers ---

async def subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'subscribe_now':
        await query.edit_message_text(
            "💳 **تفاصيل الاشتراك - {}**\n\n"
            "للاشتراك، يرجى تحويل مبلغ **{}** إلى العنوان التالي:\n\n"
            "**العنوان (USDT - BEP20):**\n"
            "`{}`\n\n"
            "بعد التحويل، يرجى **إرسال لقطة شاشة** (صورة) لعملية التحويل كإثبات للدفع. سيتم تفعيل اشتراكك يدوياً بعد المراجعة.".format(
                SUBSCRIPTION_PRICE, SUBSCRIPTION_PRICE, USDT_ADDRESS
            )
        )
        return WAITING_FOR_SCREENSHOT
        
    return ConversationHandler.END

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    photo_file = update.message.photo[-1].file_id
    
    # Get the file object
    file = await context.bot.get_file(photo_file)
    
    # Create the approval button
    keyboard = [[InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f'approve_subscription_{user.id}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # --- MODIFIED: Personalized Admin Message ---
    admin_message = (
        f"🔔 **رسالة إلى {ADMIN_TITLE}**\n\n"
        "**طلب اشتراك جديد للمراجعة**\n\n"
        f"**اسم العميل:** {user.first_name} (@{user.username or 'N/A'})\n"
        f"**معرف العميل (ID):** `{user.id}`\n"
        "**الإثبات:** (مرفق بالصورة أعلاه)"
    )
    
    await context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=photo_file,
        caption=admin_message,
        reply_markup=reply_markup
    )
    
    await update.message.reply_text(
        "✅ **تم استلام إثبات الدفع بنجاح!**\n"
        "جاري مراجعة الدفع من قبل المدير. سيتم إخطارك فور تفعيل اشتراكك."
    )
    
    return ConversationHandler.END

async def approve_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    admin_id = query.from_user.id
    
    # Check if the user pressing the button is the Admin
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("❌ أنت لست المدير المخول لإجراء هذه العملية.", show_alert=True)
        return

    await query.answer("جاري تفعيل الاشتراك...", show_alert=False)
    
    # Extract user_id from callback_data (e.g., 'approve_subscription_123456')
    try:
        target_user_id = int(query.data.split('_')[-1])
    except ValueError:
        await query.edit_message_caption(query.message.caption + "\n\n🚨 **خطأ:** لم يتم التعرف على معرف المستخدم.", reply_markup=None)
        return
        
    # 1. Update DB
    end_date = datetime.datetime.now() + datetime.timedelta(days=30)
    end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S')
    
    await update_subscription_status(target_user_id, 'active', end_date_str)
    
    # 2. Notify Client
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text="🎉 **تهانينا! تم تفعيل اشتراكك بنجاح!**\n\n"
                 f"حالة الاشتراك: **نشط**.\n"
                 f"تاريخ الانتهاء: **{end_date_str}**.\n\n"
                 "يمكنك الآن البدء في استخدام البوت.\n"
                 "**الخطوة التالية:** يرجى إعداد مفاتيح API الخاصة بك باستخدام الأمر /set_api للبدء في التداول."
        )
        
        # 3. Update Admin Message
        await query.edit_message_caption(
            query.message.caption + 
            f"\n\n✅ **تم التفعيل بنجاح!**\n"
            f"تم تفعيل الاشتراك للمستخدم {target_user_id} حتى {end_date_str}.\n"
            f"تم الإخطار بواسطة: {query.from_user.first_name}",
            reply_markup=None # Remove button after action
        )
        
    except Exception as e:
        await query.edit_message_caption(
            query.message.caption + 
            f"\n\n⚠️ **فشل الإخطار!**\n"
            f"تم تفعيل الاشتراك في قاعدة البيانات، لكن فشل إرسال رسالة للمستخدم: {e}",
            reply_markup=None
        )

# --- Original Handlers (Kept) ---
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text('❌ تم إلغاء العملية.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def simple_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A simple cancel command that does not end a conversation (used for general command handling)."""
    await update.message.reply_text("❌ Operation cancelled.")

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("❌ Invalid input. The amount must be a positive number.")
            return AMOUNT
            
        context.user_data['amount'] = amount
        await update.message.reply_text("2. 🪙 أدخل رمز العملة (مثال: BTC/USDT):", reply_markup=ForceReply(selective=True))
        return SYMBOL
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return AMOUNT

async def get_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    symbol_input = update.message.text.strip().upper()
    if not symbol_input.endswith('/USDT'):
        symbol_input = f"{symbol_input}/USDT"
        
    context.user_data['symbol'] = symbol_input
    await update.message.reply_text("3. 📈 أدخل نسبة الربح المستهدفة (%) (مثال: 5):", reply_markup=ForceReply(selective=True))
    return PROFIT_PERCENT

async def get_profit_percent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        profit_percent = float(update.message.text)
        if profit_percent <= 0:
            await update.message.reply_text("❌ Invalid input. Profit percentage must be a positive number.")
            return PROFIT_PERCENT
            
        context.user_data['profit_percent'] = profit_percent
        await update.message.reply_text("4. 🛡️ هل تريد استخدام وقف الخسارة (Stop Loss)؟ (نعم/لا):", reply_markup=ForceReply(selective=True))
        return USE_STOP_LOSS
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return PROFIT_PERCENT

async def get_use_stop_loss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    response = update.message.text.lower()
    if response in ['yes', 'نعم', 'y', 'ن']:
        context.user_data['use_stop_loss'] = True
        await update.message.reply_text("5. 📉 أدخل نسبة وقف الخسارة (%):", reply_markup=ForceReply(selective=True))
        return STOP_LOSS_PERCENT
    else:
        context.user_data['use_stop_loss'] = False
        context.user_data['stop_loss_percent'] = 0.0
        await update.message.reply_text("✅ All data collected. Executing Trade...")
        asyncio.create_task(sniping_and_trade(update, context, context.user_data)) if context.user_data.get('is_sniping') else asyncio.create_task(execute_trade(update, context, context.user_data))
        return ConversationHandler.END

async def get_stop_loss_percent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        stop_loss_percent = float(update.message.text)
        if stop_loss_percent <= 0:
            await update.message.reply_text("❌ Invalid input. Stop Loss percentage must be a positive number.")
            return STOP_LOSS_PERCENT
            
        context.user_data['stop_loss_percent'] = stop_loss_percent
        await update.message.reply_text("✅ All data collected. Executing Trade...")
        asyncio.create_task(sniping_and_trade(update, context, context.user_data)) if context.user_data.get('is_sniping') else asyncio.create_task(execute_trade(update, context, context.user_data))
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return STOP_LOSS_PERCENT

# MAIN FUNCTION
def main() -> None:
    # --- FIX 3: Check all required environment variables ---
    # Only check for the token, as other values are hardcoded
    if not TELEGRAM_BOT_TOKEN:
        print("FATAL ERROR: TELEGRAM_BOT_TOKEN is not set.")
        sys.exit(1)
        
    # --- NEW: Run DB initialization synchronously ---
    asyncio.run(init_db())
        
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # --- NEW: Subscription Conversation Handler ---
    subscription_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(subscribe_callback, pattern='^subscribe_now$')],
        states={
            WAITING_FOR_SCREENSHOT: [MessageHandler(filters.PHOTO & ~filters.COMMAND, receive_screenshot)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True
    )
    
    # --- NEW: API Key Conversation Handler ---
    api_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("set_api", set_api_start)],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_api_key)],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_api_secret)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True
    )
    
    # Conversation Handler Setup (Trade/Sniping)
    trade_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", trade_start), CommandHandler("sniping", sniping_start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_symbol)],
            PROFIT_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_profit_percent)],
            USE_STOP_LOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_use_stop_loss)],
            STOP_LOSS_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stop_loss_percent)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("cancel", simple_cancel_command))
    application.add_handler(CallbackQueryHandler(approve_subscription_callback, pattern='^approve_subscription_'))
    
    application.add_handler(subscription_conv_handler)
    application.add_handler(api_conv_handler)
    application.add_handler(trade_conv_handler)
    
    print("Bot is running... Send /start to the bot on Telegram.")
    application.run_polling(poll_interval=1.0, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # 1. Start the web server in a background thread
    start_web_server_thread()
    
    # 2. Start the main bot logic
    main()

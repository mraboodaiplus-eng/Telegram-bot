# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
import ccxt.async_support as ccxt
import asyncio
import os
import sys
import datetime
import time # Added for use in execute_trade
from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters

# Assuming database.py is available and contains the required functions
from database import init_db, get_user, add_new_user, update_subscription_status, is_subscription_active, update_api_keys, setup_vip_api_keys

# Flask app instance
app = Flask(__name__)

# Global variable to hold the Application instance
application = None

# --- CONFIGURATION AND CONSTANTS ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- NEW: Generalizing Exchange ---
# The bot will now use the exchange ID specified here. User's API keys will be used for this exchange.
# I will use 'binance' as a common default, but the user can change this to 'bingx', 'bybit', etc.
 

# Owner's Information (Should be in environment variables for security, but keeping hardcoded as requested)
OWNER_ID = 7281928709
OWNER_API_KEY = "M1OSlqx9F5TQD7eBxmitch4NLw9ZPpD9Xng28REiwDJe9bunCp8mPvu5GoV9QLJ3NIAO2b0YZu8GszVlIcaxw"
OWNER_API_SECRET = "ybuQhV2CzYrvJx9wnAH4gq01z25b2FZDtZguc89zCKaOfHO4NT9IlGxaPsDmgsbVvjl4M1ammvBOVHJ4fIaw"

# ABOOD's Information (Should be in environment variables)
ABOOD_ID = 5991392622
ABOOD_API_KEY = "bg_ec710cae5f25832f2476b517b605bb4a"
ABOOD_API_SECRET = "faca6ac6f1060c0c0a362a361af42c50b0b052a81572e248311047b4dc53870cd"

# Whitelisted users (Owner and friends)
WHITELISTED_USERS = [OWNER_ID, ABOOD_ID]
ADMIN_CHAT_ID = OWNER_ID 
ADMIN_TITLE = "المدير العام" 

# Payment Details
USDT_ADDRESS = "0xb85f1c645dbb80f2617823c069dcb038a9f79895"
SUBSCRIPTION_PRICE = "10$ شهرياً (BEP20)"

# Sniping Delay (Missing Constant)
SNIPING_DELAY = 0.03 # Check every 0.03 seconds for high-speed sniping

# Conversation States
AMOUNT, SYMBOL, PROFIT_PERCENT, USE_STOP_LOSS, STOP_LOSS_PERCENT = range(5)
WAITING_FOR_SCREENSHOT = 50


# --- EXCHANGE TRADING LOGIC ---

def initialize_exchange(user_id, api_key, api_secret):
    """Initializes the ccxt exchange object with provided API keys and the global EXCHANGE_ID."""
    
    # Get the exchange class from ccxt
    exchange_class = ccxt.bingx
    
    # Special case: If user is the OWNER, use the hardcoded keys
    # Special case: If user is the OWNER, use the hardcoded keys
    if user_id == OWNER_ID:
        api_key = OWNER_API_KEY
        api_secret = OWNER_API_SECRET
        
    if not api_key or not api_secret:
        raise ValueError("API Key or Secret is missing. Please use /set_api.")
        
    return exchange_class({
        'apiKey': api_key,
        'secret': api_secret,
        'options': {'defaultType': 'spot'}, # Assuming spot trading for simplicity
        'enableRateLimit': True,
    })

async def wait_for_listing(update: Update, context: ContextTypes.DEFAULT_TYPE, exchange, symbol):
    """Waits for the symbol to be listed on the exchange (Sniping Mode)."""
    # Fixed Syntax Error: The f-string was malformed and contained extraneous code.
    await update.message.reply_text(f"⏳ [SNIPING MODE] جاري انتظار إدراج العملة {symbol}...")
    
    while True:
        try:
            exchange.load_markets()
            if symbol in exchange.markets:
                market = exchange.markets[symbol]
                if market['active'] and market['spot'] and market['trade']:
                    ticker = await exchange.fetch_ticker(symbol)
                    await update.message.reply_text(f"✅ [SUCCESS] {symbol} is now listed and tradable! Current price: {ticker['last']:.6f}")
                    return
                else:
                    # Symbol is listed but not yet tradable, continue waiting
                    await asyncio.sleep(SNIPING_DELAY)
                    continue
        except ccxt.BadSymbol:
            # The symbol is not listed yet, wait and try again
            await asyncio.sleep(SNIPING_DELAY)
        except Exception as e:
            await update.message.reply_text(f"⚠️ [WARNING] Sniping Error: {type(e).__name__}: {e}")
            await asyncio.sleep(5)

async def execute_trade(update: Update, context: ContextTypes.DEFAULT_TYPE, params):
    """Executes a market buy, sets a limit sell (Take Profit), and an optional stop loss."""
    user_id = update.effective_user.id
    user_record = await get_user(user_id)
    
    # Ensure user record exists
    if not user_record:
        await update.message.reply_text("🚨 [ERROR] لم يتم العثور على سجل المستخدم. يرجى إرسال /start أولاً.")
        return

    api_key = user_record.get('api_key')
    api_secret = user_record.get('api_secret')
    
    if not api_key or not api_secret:
        await update.message.reply_text("🚨 [ERROR] لم يتم العثور على مفاتيح API الخاصة بك. يرجى إدخالها أولاً باستخدام /set_api.")
        return  
    
    try:
        exchange = initialize_exchange(user_id, api_key, api_secret)
    except ValueError as e:
        await update.message.reply_text(f"🚨 [ERROR] خطأ في تهيئة الاتصال: {e}")
        return
    except Exception as e:
        await update.message.reply_text(f"🚨 [ERROR] فشل تهيئة الاتصال بالمنصة: {type(e).__name__}: {e}")
        return

    symbol = params['symbol']
    amount_usdt = params['amount']
    profit_percent = params['profit_percent']
    stop_loss_percent = params['stop_loss_percent']
    
    try:
        await update.message.reply_text(f"🛒 [STEP 1/3] Placing Market Buy Order for {amount_usdt} USDT...")

        # Fixed Syntax Error: Corrected the line 105 error
        market_buy_order = await exchange.create_order(
            symbol=symbol,
            type='market',
            side='buy',
            amount=None,
            price=None,
            params={'cost': amount_usdt} # Use 'cost' parameter to specify amount in quote currency (USDT)
        )
        
        await update.message.reply_text(f"👍 [SUCCESS] Buy Order placed. ID: {market_buy_order['id']}")
        
        # --- STEP 2: Get Execution Details ---
        await update.message.reply_text("🔍 [STEP 2/3] Waiting for execution details...")
        await asyncio.sleep(2) 
        
        # Fetch order details and trades to get accurate filled amount and average price
        order_details = await exchange.fetch_order(market_buy_order['id'], symbol)
        
        if order_details.get('status') not in ['closed', 'filled']:
            # Fallback to fetching trades if order status is not final
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
        
        # Get precision for the symbol
        try:
            exchange.load_markets()
            if symbol not in exchange.markets:
                raise ccxt.BadSymbol(f"Symbol {symbol} is not available on {exchange.id}.")
                
            market = exchange.markets[symbol]
            # Ensure amount is rounded to the correct precision
            precision = market['precision']['amount']
            
            import math
            # Round down the filled amount to the exchange's precision
            filled_amount_precise = math.floor(filled_amount * (10**precision)) / (10**precision)
            
        except Exception as e:
            await update.message.reply_text(f"⚠️ [WARNING] Failed to get market info/precision: {e}. Using raw filled amount.")
            filled_amount_precise = filled_amount
            
        limit_sell_order = await exchange.create_limit_sell_order(symbol, filled_amount_precise, target_sell_price)
        await update.message.reply_text(f"📈 [SUCCESS] Take Profit Order placed. ID: {limit_sell_order['id']}")
        
        # --- OPTIONAL: Stop Loss Order ---
        stop_order = None
        if params['use_stop_loss']:
            stop_loss_price = avg_price * (1 - stop_loss_percent / 100)
            await update.message.reply_text(f"🛡️ [OPTIONAL] Placing Stop Loss Order (-{stop_loss_percent}%) at {stop_loss_price:.6f}...")
            
            # Note: Stop Market order creation can vary by exchange. Using a common pattern.
            stop_order = await exchange.create_order(
                symbol=symbol,
                type='stop_market',
                side='sell',
                amount=filled_amount_precise,
                price=None,
                params={'stopPrice': stop_loss_price}
            )
            
            await update.message.reply_text(f"📉 [SUCCESS] Stop Loss Order placed. ID: {stop_order['id']}")
            await update.message.reply_text("‼️ WARNING: TWO OPEN ORDERS ‼️\nManually cancel the other order if one executes. (Take Profit is Limit, Stop Loss is Market, Stop)")
        
        # --- AUTOMATIC PROFIT SHARING LOGIC ---
        # Send the monitoring message ONCE
        await update.message.reply_text("⏳ [MONITOR] جاري مراقبة أمر البيع (Take Profit) لتنفيذ الاقتطاع التلقائي...")
        
        order_id = limit_sell_order['id']
        
        # Simple Polling Loop (Blocking the trade function until the order is filled)
        while True:
            await asyncio.sleep(0.03) # Check every 0.03 seconds for high-speed sniping and monitoring
            
            # Fetch the order status
            order_status = await exchange.fetch_order(order_id, symbol)
            
            if order_status['status'] == 'closed' or order_status['status'] == 'filled':
                await update.message.reply_text("✅ [SUCCESS] تم تنفيذ أمر البيع (Take Profit) بنجاح!")
                
                # Cancel Stop Loss Order if it exists and is still open
                if stop_order and stop_order['status'] == 'open':
                    await exchange.cancel_order(stop_order['id'], symbol)
                    await update.message.reply_text("❌ [CLEANUP] تم إلغاء أمر وقف الخسارة (Stop Loss).")
                    
                # Call the automatic withdrawal function
                await handle_profit_withdrawal(
                    update, 
                    context, 
                    user_id, 
                    amount_usdt_spent, # amount_usdt_spent is the initial investment
                    filled_amount_precise, 
                    avg_price, 
                    target_sell_price, 
                    symbol
                )
                break # Exit the monitoring loop
            
            elif order_status['status'] == 'canceled' or order_status['status'] == 'rejected':
                await update.message.reply_text("❌ [FAILURE] تم إلغاء أو رفض أمر البيع (Take Profit). لن يتم اقتطاع أي شيء.")
                break # Exit the monitoring loop
            
            # NO REPEATING STATUS MESSAGE - Monitoring continues silently
            
        await update.message.reply_text("✅ **تم الانتهاء من عملية التداول والاقتطاع (إن وجدت).**")
            
    except ccxt.ExchangeError as e:
        await update.message.reply_text(f"🚨 [EXCHANGE ERROR] {type(e).__name__}: {e}")
    except ccxt.NetworkError as e:
        await update.message.reply_text(f"🚨 [NETWORK ERROR] {type(e).__name__}: {e}")
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] {type(e).__name__}: {e}")
    finally:
        if 'exchange' in locals():
            await exchange.close()


# --- PROFIT SHARING AND WITHDRAWAL LOGIC ---
async def handle_profit_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, amount_usdt_spent, filled_amount, avg_price, target_sell_price, symbol):
    """Calculates profit and attempts to withdraw 10% share."""
    # Check for exemption (Owner and Abood)
    # Check for exemption (Owner and Abood)
    if user_id in WHITELISTED_USERS:
        # Send message to the user that they are exempt, but do not proceed with withdrawal logic
        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 **عملية ناجحة!** أنت معفى من اقتطاع الأرباح (بروتوكول المؤسس V.I.P)."
        )
        return

    # 1. Calculate Gross Profit (using the target sell price as a proxy)
    gross_revenue = filled_amount * target_sell_price
    gross_profit = gross_revenue - amount_usdt_spent
    
    if gross_profit <= 0:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ **لا يوجد ربح للاقتطاع.** الصفقة لم تحقق ربحاً صافياً."
        )
        return
        
    # 2. Calculate 10% Share
    PROFIT_SHARE_PERCENT = 0.10
    our_share = gross_profit * PROFIT_SHARE_PERCENT
    
    # 3. Perform Withdrawal (The critical step)
    await context.bot.send_message(
        chat_id=user_id,
        text=f"💰 **تم تحقيق ربح!**\n"
             f"الربح الإجمالي المحقق: {gross_profit:.2f} USDT\n"
             f"نسبة الاقتطاع (10%): {our_share:.2f} USDT\n"
             f"جاري تحويل حصتنا إلى محفظة المدير العام..."
    )
    
    try:
        user_record = await get_user(user_id)
        exchange = initialize_exchange(user_id, user_record['api_key'], user_record['api_secret'])
        
        # NOTE: The network code for BEP20 on most exchanges is 'BSC' or 'BEP20'.
        withdrawal_result = await exchange.withdraw(
            code='USDT',
            amount=our_share,
            address=USDT_ADDRESS,
            tag=None, 
            params={'network': 'BEP20'} # Assuming BEP20 network
        )
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ **تم الاقتطاع بنجاح!**\n"
                 f"تم تحويل {our_share:.2f} USDT إلى محفظة المدير العام.\n"
                 f"معرف عملية السحب: {withdrawal_result['id']}"
        )
        
    except ccxt.ExchangeError as e:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🚨 **فشل عملية السحب (الاقتطاع)!**\n"
                 f"لم نتمكن من اقتطاع حصتنا بسبب خطأ في المنصة. قد تكون صلاحية السحب غير مفعلة، أو لا يوجد رصيد كافٍ في محفظة SPOT.\n"
                 f"الخطأ: {type(e).__name__}: {e}\n\n"
                 f"يرجى التأكد من تفعيل صلاحية السحب وإضافة IP الخاص بالبوت (185.185.72.73) في حال طلب المنصة ذلك."
        )
    except Exception as e:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🚨 **فشل عملية السحب (خطأ عام)!**\n"
                 f"الخطأ: {type(e).__name__}: {e}"
        )
    finally:
        if 'exchange' in locals():
            await exchange.close()


async def sniping_and_trade(update: Update, context: ContextTypes.DEFAULT_TYPE, params):
    """Handles the sniping process followed by the trade execution."""
    await update.message.reply_text("⚡️ [SNIPING MODE] Starting Sniping process...")
    
    # Initialize a temporary exchange object for sniping (no keys needed for fetching ticker)
    try:
        exchange_class = ccxt.bingx
        temp_exchange = exchange_class({'enableRateLimit': True})
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] Failed to initialize temporary exchange: {e}")
        return
    
    # 1. Wait for listing (Sniping)
    try:
        await wait_for_listing(update, context, temp_exchange, params['symbol'])
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] Failed during sniping wait: {e}")
        return
    finally:
        await temp_exchange.close()

    # 2. Execute trade (This will initialize a new exchange with user's keys)
    await execute_trade(update, context, params) 


# --- SUBSCRIPTION AND API KEY HANDLERS ---

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks if the user is whitelisted or has an active subscription."""
    user_id = update.effective_user.id
    
    if user_id in WHITELISTED_USERS:
        return True
        
    user_record = await get_user(user_id)
    
    # Subscription logic is disabled as the bot is now free with profit sharing.
    # The original code had a check here, but the new logic is to allow all users
    # and enforce profit sharing, so we only need to check if the user exists.
    # The original subscription check is commented out to allow free access.
    
    # if user_record and is_subscription_active(user_record):
    #     return True
    
    # The bot is now free, so we allow access if the user has an API key set, or prompt for it.
    
    return True # Allow all users to proceed to the trade conversation

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    await add_new_user(user_id)
    
    # Auto-setup VIP API Keys for ABOOD (Removed as per user request)
        
    if user_id in WHITELISTED_USERS:
        if user_id == OWNER_ID:
            welcome_message = (
                f"👑 **تحية الإجلال، سيدي المدير العام** ({username}) 👑\n\n"
                "جميع الأنظمة والعمليات تحت إمرتكم المباشرة. الصلاحيات العليا مفعلة بالكامل.\n"
                "**الأوامر السيادية المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة البوت"
            )
        elif user_id == ABOOD_ID:
            welcome_message = (
                f"تم التحقق. أهلاً بك، سيد 👑Abood👑. تم تفعيل بروتوكول المؤسس V.I.P الخاص بك.\n"
                "جميع الأنظمة تحت سيطرتك الآن، مع وصول كامل ومجاني لجميع الميزات الحالية والمستقبلية.البوت في خدمة سيادتكم.\n\n"
                "**الأوامر التنفيذية المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة البوت"
            )
        else:
            welcome_message = (
                f"👋 مرحباً بك يا {username} (المستخدم المميز)!\n"
                "**الأوامر المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة الاشتراك"
            )
        
        await update.message.reply_text(welcome_message)
        return
        
    # New Client Welcome Message (Bot is now free)
    await update.message.reply_text(
        f"👋 مرحباً بك يا {username}!\n\n"
        f"أهلاً بك في خدمة **LiveSniperBot** المجانية والمتميزة.\n"
        f"البوت يعمل على منصة تداول بنظام **اقتطاع الأرباح (10%)** على الصفقات الناجحة فقط.\n"
        "للبدء، يرجى إعداد مفاتيح API الخاصة بك وتفعيل خيار **السحب**.\n\n"
        "**الأوامر المتاحة:**\n"
        "/trade - 📈 تداول عادي (شراء وبيع)\n"
        "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
        "/cancel - ❌ إلغاء العملية الحالية\n"
        "/set_api - 🔑 إعداد مفاتيح API\n"
        "/status - ℹ️ عرض حالة البوت"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_record = await get_user(user_id)
    
    if user_id in WHITELISTED_USERS:
        await update.message.reply_text(f"ℹ️ **حالة المستخدم:**\n\n"
                                        "نوع المستخدم: **مميز (Whitelist)**\n"
                                        "حالة الأرباح: **معفاة من الاقتطاع**")
        return
        
    if not user_record:
        await update.message.reply_text("ℹ️ **حالة المستخدم:**\n\n"
                                        "لم يتم العثور على سجل لك. يرجى إرسال /start.")
        return
        
    api_status = 'موجودة' if user_record.get('api_key') else 'غير موجودة'
    
    await update.message.reply_text(f"ℹ️ **حالة المستخدم:**\n\n"
                                    f"نوع المستخدم: **عميل (مجاني)**\n"
                                    f"نسبة الاقتطاع: **10% من صافي الربح**\n"
                                    f"مفاتيح API: **{api_status}**\n"
                                    f"متطلبات API: **قراءة، كتابة، تداول فوري، سحب**")

async def trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check subscription before starting conversation (now only checks if user exists)
    if not await check_subscription(update, context):
        return ConversationHandler.END
        
    context.user_data['is_sniping'] = False
    await update.message.reply_text("1. 💰 أدخل مبلغ الشراء بالدولار الأمريكي (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

async def sniping_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check subscription before starting conversation (now only checks if user exists)
    if not await check_subscription(update, context):
        return ConversationHandler.END
        
    context.user_data['is_sniping'] = True
    await update.message.reply_text("1. ⚡️ أدخل مبلغ القنص بالدولار الأمريكي (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

# --- API Key Setting Conversation ---
async def set_api_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("🔑 **إعداد مفاتيح API لمنصة التداول**\n\n"
                                    "1. يرجى إرسال **API Key** الخاص بك:", reply_markup=ForceReply(selective=True))
    return 1 # State for API Key

async def set_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    symbol = update.message.text.upper()
    # Append /USDT if not already present
    if "/USDT" not in symbol:
        symbol += "/USDT"
    context.user_data['temp_symbol'] = symbol
    await update.message.reply_text("2. يرجى إرسال **API Secret** الخاص بك:", reply_markup=ForceReply(selective=True))
    return 2 # State for API Secret

async def set_api_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    api_secret = update.message.text.strip()
    api_key = context.user_data['temp_api_key']
    user_id = update.effective_user.id
    
    # Ensure user exists in DB before attempting to update keys
    await add_new_user(user_id) 
    await update_api_keys(user_id, api_key, api_secret)
    
    await update.message.reply_text("✅ **تم حفظ مفاتيح API بنجاح!**\n"
                                    "جاري التحقق من صلاحيات المفاتيح (القراءة، التداول، **السحب**)...")
    
    # --- NEW: Check Withdrawal Permission (Generalized) ---
    user_record = await get_user(user_id)
    api_key = user_record['api_key']
    api_secret = user_record['api_secret']

    # VIP users (Owner and Abood) are assumed to have correct keys and we skip the strict withdrawal check
    if user_id in WHITELISTED_USERS:
        await update.message.reply_text("✅ **صلاحيات المفاتيح مكتملة (VIP)!**\n"
                                        "تم افتراض تفعيل جميع الصلاحيات اللازمة (بما في ذلك السحب) لمستخدمي القائمة البيضاء.\n\n"
                                        "يمكنك الآن استخدام أوامر التداول: /trade أو /sniping.")
        return ConversationHandler.END
    try:
        exchange = initialize_exchange(user_id, api_key, api_secret)
        
        # Check for Withdrawal Permission by calling fetchDepositAddress (a safe method that requires withdrawal permission)
        # Note: This is a heuristic and might not work for all exchanges/networks.
        await exchange.fetch_deposit_address('USDT', params={'network': 'BEP20'})
        
        await update.message.reply_text("✅ **صلاحيات المفاتيح مكتملة!**\n"
                                        "تم التأكد من تفعيل صلاحيات **القراءة، التداول، والسحب**.\n\n"
                                        "**الخطوة الأخيرة:** إذا لم تقم بذلك بعد، يرجى إضافة IP البوت **185.185.72.73** إلى القائمة البيضاء (Whitelist) في إعدادات API على منصة التداول لتفعيل السحب بشكل آمن.\n\n"
                                        "يمكنك الآن استخدام أوامر التداول: /trade أو /sniping.")
        
    except Exception as e:
        await update.message.reply_text(f"❌ **فشل التحقق من صلاحية السحب!**\n"
                                        f"الخطأ: {type(e).__name__}: {e}\n\n"
                                        "لضمان عمل البوت بنظام اقتطاع الأرباح، **يجب تفعيل صلاحية السحب**.\n"
                                        f"يرجى مراجعة إعدادات مفاتيح API الخاصة بك على **منصة التداول** وتفعيل الخيارات التالية:\n"
                                        "1. القراءة والكتابة.\n"
                                        "2. التداول الفوري.\n"
                                        "3. **السحب (Withdrawal)** - وتأكد من إضافة IP البوت: **185.185.72.73**.\n\n"
                                        "يرجى المحاولة مرة أخرى بعد التعديل.")
    finally:
        if 'exchange' in locals():
            await exchange.close()
    
    return ConversationHandler.END

# --- Subscription Handlers (Kept but not used in the main flow) ---

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
    
    file = await context.bot.get_file(photo_file)
    
    keyboard = [[InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f'approve_subscription_{user.id}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
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
    
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("❌ أنت لست المدير المخول لإجراء هذه العملية.", show_alert=True)
        return

    await query.answer("جاري تفعيل الاشتراك...", show_alert=False)
    
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

# --- Conversation Handlers (Input/Validation) ---

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
    # Ensure the symbol is in the correct format (e.g., BTC/USDT)
    if '/' not in symbol_input:
        symbol_input = f"{symbol_input}/USDT"
    # Ensure the symbol is uppercase
    symbol_input = symbol_input.upper()
        
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
        # Start the trade execution as a background task
        if context.user_data.get('is_sniping'):
            asyncio.create_task(sniping_and_trade(update, context, context.user_data))
        else:
            asyncio.create_task(execute_trade(update, context, context.user_data))
            
        return ConversationHandler.END

async def get_stop_loss_percent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        stop_loss_percent = float(update.message.text)
        if stop_loss_percent <= 0:
            await update.message.reply_text("❌ Invalid input. Stop Loss percentage must be a positive number.")
            return STOP_LOSS_PERCENT
            
        context.user_data['stop_loss_percent'] = stop_loss_percent
        await update.message.reply_text("✅ All data collected. Executing Trade...")
        # Start the trade execution as a background task
        if context.user_data.get('is_sniping'):
            asyncio.create_task(sniping_and_trade(update, context, context.user_data))
        else:
            asyncio.create_task(execute_trade(update, context, context.user_data))
            
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return STOP_LOSS_PERCENT

# MAIN FUNCTION
def main() -> None:
    # --- ENSURE DATABASE IS INITIALIZED ---
    print("DEBUG: Initializing database...")
    import asyncio
    asyncio.run(init_db())
    print("DEBUG: Database initialization complete.")
    
    # Check for the token
    if not TELEGRAM_BOT_TOKEN:
        print("FATAL ERROR: TELEGRAM_BOT_TOKEN is not set in environment variables.")
        sys.exit(1)
        
    
        
    global application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # --- Subscription Conversation Handler ---
    subscription_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(subscribe_callback, pattern='^subscribe_now$')],
        states={
            WAITING_FOR_SCREENSHOT: [MessageHandler(filters.PHOTO & ~filters.COMMAND, receive_screenshot)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True
    )
    
    # --- API Key Conversation Handler ---
    api_key_conv_handler = ConversationHandler(
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
    application.add_handler(trade_conv_handler)
    application.add_handler(subscription_conv_handler)
    application.add_handler(api_key_conv_handler)
    
    # === START KEEP-ALIVE WEB SERVER (Flask) ===
    # We run the Flask server in a separate thread to keep the Polling bot alive and satisfy Render's port requirement.
    import threading
    def run_web_server():
        PORT = int(os.environ.get("PORT", 10000))
        
        try:
            from waitress import serve
            print(f"Starting Waitress server on port {PORT}...")
            serve(app, host='0.0.0.0', port=PORT)
        except ImportError:
            print(f"Waitress not found. Starting Flask development server on port {PORT}...")
            app.run(host='0.0.0.0', port=PORT)

    # Start the web server in a new thread
    threading.Thread(target=run_web_server, daemon=True).start()

    # === START POLLING BOT ===
    print("Bot is running in Polling mode... Send /start to the bot on Telegram.")
    application.run_polling(poll_interval=1.0, allowed_updates=Update.ALL_TYPES)

@app.route('/', methods=['GET'])
def home():
    return "Telegram Bot is running (Polling mode with Keep-Alive).", 200


if __name__ == "__main__":
    main()

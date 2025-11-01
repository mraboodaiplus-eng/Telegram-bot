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
from database import init_db, get_user, add_new_user, update_api_keys, is_subscription_active, add_new_grid, get_active_grids, stop_grid, get_user_grids, get_grid_by_id
from decimal import Decimal, ROUND_HALF_UP, getcontext
# Set precision for Decimal calculations
getcontext().prec = 28

# --- GENERAL HANDLERS ---
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text(
        '❌ تم إلغاء العملية الحالية.', reply_markup=ReplyKeyboardRemove()
    )
    # Clear any temporary data
    context.user_data.clear()
    return ConversationHandler.END

# Flask app instance
app = Flask(__name__)

# Global variable to hold the Application instance
application = None

# --- CONFIGURATION AND CONSTANTS ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- NEW: Generalizing Exchange ---
# The bot will now use the exchange ID specified by the user.
# The old EXCHANGE_ID constant is no longer used for trading logic.

# Owner's Information (IDs only, API keys must be set via /set_api)
OWNER_ID = 7281928709

# ABOOD's Information (IDs only, API keys must be set via /set_api)
ABOOD_ID = 5991392622

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
ORDER_TYPE, AMOUNT, SYMBOL, PROFIT_PERCENT, USE_STOP_LOSS, STOP_LOSS_PERCENT, LIMIT_PRICE = range(7)
GRID_SYMBOL, LOWER_BOUND, UPPER_BOUND, NUM_GRIDS, AMOUNT_PER_ORDER, STOP_GRID_ID = range(7, 13)
WAITING_FOR_SCREENSHOT = 50

# New Conversation States for API Setup
SELECT_EXCHANGE, WAITING_FOR_API_KEY, WAITING_FOR_API_SECRET = range(51, 54)


# --- EXCHANGE TRADING LOGIC ---

def initialize_exchange(user_id, exchange_id, api_key, api_secret):
    """Initializes the ccxt exchange object with provided API keys and the user's exchange_id."""
    
    if not exchange_id:
        raise ValueError("Exchange ID is missing. Please use /set_api to select an exchange.")
        
    # Get the exchange class from ccxt dynamically based on the user's exchange_id
    try:
        exchange_class = getattr(ccxt, exchange_id)
    except AttributeError:
        raise ValueError(f"Unsupported exchange: {exchange_id}. Please select a valid exchange.")
        
    # All users, including OWNER and ABOOD, must now use /set_api.
    # The user's API keys and exchange ID are retrieved from the database.
    
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
    # 1. Initial Check: If the symbol is already listed and tradable, proceed immediately.
    try:
        ticker = await exchange.fetch_ticker(symbol)
        if ticker and ticker.get('last') is not None:
            await update.message.reply_text(f"✅ [SUCCESS] {symbol} is already listed and tradable! Current price: {ticker['last']:.6f}")
            return
    except (ccxt.BadSymbol, ccxt.ExchangeError):
        # Ignore initial check errors and proceed to the waiting loop
        pass
        
    # 2. Waiting Loop: If not listed, start the waiting process.
    await update.message.reply_text(f"⏳ [SNIPING MODE] جاري انتظار إدراج العملة {symbol}...")
    
    while True:
        try:
            ticker = await exchange.fetch_ticker(symbol)
            if ticker and ticker.get('last') is not None:
                # AVOID TELEGRAM MESSAGE DELAY: Only return, the main function will handle the success message
                return
        except (ccxt.BadSymbol, ccxt.ExchangeError):
            # The symbol is not listed yet, wait and try again
            await asyncio.sleep(SNIPING_DELAY)
        except Exception as e:
            # Do not send repeated warning messages to the user. Log internally only.
            # print(f"Sniping Error: {type(e).__name__}: {e}") # Log internally
            await asyncio.sleep(SNIPING_DELAY)

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
    exchange_id = user_record.get('exchange_id')
    
    if not exchange_id:
        await update.message.reply_text("🚨 [ERROR] لم يتم اختيار منصة التداول. يرجى اختيارها أولاً باستخدام /set_api.")
        return
        
    if not api_key or not api_secret:
        await update.message.reply_text("🚨 [ERROR] لم يتم العثور على مفاتيح API الخاصة بك. يرجى إدخالها أولاً باستخدام /set_api.")
        return  
    
    try:
        exchange = initialize_exchange(user_id, exchange_id, api_key, api_secret)
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
        # Determine the order type and price for the buy order
        order_type = 'limit' if params['order_type'] == 'limit' else 'market'
        order_price = params.get('limit_price') if order_type == 'limit' else None
        
        if order_type == 'market':
            # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
            # await update.message.reply_text(f"🛒 [STEP 1/3] Placing Market Buy Order for {amount_usdt} USDT...")
            pass
        else:
            # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
            # await update.message.reply_text(f"🛒 [STEP 1/3] Placing Limit Buy Order at {order_price} for {amount_usdt} USDT...")
            pass

        # Fixed Syntax Error: Corrected the line 105 error
        market_buy_order = await exchange.create_order(
            symbol=symbol,
            type=order_type,
            side='buy',
            amount=None,
            price=order_price, # Only used for limit order
            params={'cost': amount_usdt, 'createMarketBuyOrderRequiresPrice': False} # Use 'cost' parameter to specify amount in quote currency (USDT)
        )
        
        # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
        # await update.message.reply_text(f"👍 [SUCCESS] Buy Order placed. ID: {market_buy_order['id']}")
        
        # --- STEP 2: Get Execution Details ---
        # Removed asyncio.sleep(2) to speed up the process
        # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
        # await update.message.reply_text("🔍 [STEP 2/3] Getting execution details...")
        
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
        
        # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
        # await update.message.reply_text(f"📊 [DETAILS] Avg Price: {avg_price:.6f}, Quantity: {filled_amount:.6f}")
        
        # --- STEP 3: Take Profit Limit Sell ---
        target_sell_price = avg_price * (1 + profit_percent / 100)
        # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
        # await update.message.reply_text(f"🎯 [STEP 3/3] Placing Take Profit Limit Sell (+{profit_percent}%) at {target_sell_price:.6f}...")
        
        # Get precision for the symbol
        # Removed any potential sleep/delay here to ensure immediate execution
        try:
            await exchange.load_markets()
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
        # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
        # await update.message.reply_text(f"📈 [SUCCESS] Take Profit Order placed. ID: {limit_sell_order['id']}")
        
        # --- OPTIONAL: Stop Loss Order ---
        stop_order = None
        if params['use_stop_loss']:
            stop_loss_price = avg_price * (1 - stop_loss_percent / 100)
            # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
            # await update.message.reply_text(f"🛡️ [OPTIONAL] Placing Stop Loss Order (-{stop_loss_percent}%) at {stop_loss_price:.6f}...")
            
            # Note: Stop Market order creation can vary by exchange. Using a common pattern.
            stop_order = await exchange.create_order(
                symbol=symbol,
                type='stop_market',
                side='sell',
                amount=filled_amount_precise,
                price=None,
                params={'stopPrice': stop_loss_price}
            )
            
            # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
            # await update.message.reply_text(f"📉 [SUCCESS] Stop Loss Order placed. ID: {stop_order['id']}")
            # await update.message.reply_text("‼️ WARNING: TWO OPEN ORDERS ‼️\nManually cancel the other order if one executes. (Take Profit is Limit, Stop Loss is Market, Stop)")
        
        # --- AUTOMATIC PROFIT SHARING LOGIC ---
        # Send the monitoring message ONCE
        # AVOID TELEGRAM MESSAGE DELAY: Remove unnecessary messages
        # await update.message.reply_text("⏳ [MONITOR] جاري مراقبة أمر البيع (Take Profit) لتنفيذ الاقتطاع التلقائي...")
        
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
        exchange_class = getattr(ccxt, EXCHANGE_ID)
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
    # AVOID TELEGRAM MESSAGE DELAY: Remove the success message here to gain a few milliseconds
    # await update.message.reply_text(f"✅ [SUCCESS] {params['symbol']} is now listed! Proceeding to trade execution...")
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

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message with the support contact information."""
    support_username = "@SYRIATRADE1"
    message = (
        "🤝 **مركز الدعم والمساعدة**\n\n"
        "إذا كان لديك أي **سؤال، اقتراح، أو واجهتك أي مشكلة** في استخدام البوت، يرجى التواصل مباشرة مع فريق الدعم.\n\n"
        f"**مسؤول الدعم:** {support_username}\n\n"
        "نحن هنا لخدمتك على مدار الساعة!"
    )
    await update.message.reply_text(message)

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
                "/grid_trade - 📊 بدء التداول الشبكي (الشبكة الآلية)\n"
                "/stop_grid - 🛑 إيقاف الشبكة الآلية\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة البوت\n"
                "/support - 🤝 مركز الدعم والمساعدة"
            )
        elif user_id == ABOOD_ID:
            welcome_message = (
                f"تم التحقق. أهلاً بك، سيد 👑Abood👑. تم تفعيل بروتوكول المؤسس V.I.P الخاص بك.\n"
                "جميع الأنظمة تحت سيطرتك الآن، مع وصول كامل ومجاني لجميع الميزات الحالية والمستقبلية.البوت في خدمة سيادتكم.\n\n"
                "**الأوامر التنفيذية المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/grid_trade - 📊 بدء التداول الشبكي (الشبكة الآلية)\n"
                "/stop_grid - 🛑 إيقاف الشبكة الآلية\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة البوت\n"
                "/support - 🤝 مركز الدعم والمساعدة"
            )
        else:
            welcome_message = (
                f"👋 مرحباً بك يا {username} (المستخدم المميز)!\n"
                "**الأوامر المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/grid_trade - 📊 بدء التداول الشبكي (الشبكة الآلية)\n"
                "/stop_grid - 🛑 إيقاف الشبكة الآلية\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالة الاشتراك\n"
                "/support - 🤝 مركز الدعم والمساعدة"
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
        "/grid_trade - 📊 بدء التداول الشبكي (الشبكة الآلية)\n"
        "/stop_grid - 🛑 إيقاف الشبكة الآلية\n"
        "/cancel - ❌ إلغاء العملية الحالية\n"
        "/set_api - 🔑 إعداد مفاتيح API\n"
        "/status - ℹ️ عرض حالة البوت\n"
        "/support - 🤝 مركز الدعم والمساعدة"
    )
    
    # Add language selection button
    keyboard = [
        [InlineKeyboardButton("🌐 اختيار اللغة / Select Language", callback_data='select_language')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 مرحباً بك يا {username}!\n\n"
        f"أهلاً بك في خدمة **LiveSniperBot** المجانية والمتميزة.\n"
        f"البوت يعمل على منصة تداول بنظام **اقتطاع الأرباح (10%)** على الصفقات الناجحة فقط.\n"
        "للبدء، يرجى إعداد مفاتيح API الخاصة بك وتفعيل خيار **السحب**.\n\n"
        "**الأوامر المتاحة:**\n"
        "/trade - 📈 تداول عادي (شراء وبيع)\n"
        "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
        "/grid_trade - 📊 بدء التداول الشبكي (الشبكة الآلية)\n"
        "/stop_grid - 🛑 إيقاف الشبكة الآلية\n"
        "/cancel - ❌ إلغاء العملية الحالية\n"
        "/set_api - 🔑 إعداد مفاتيح API\n"
        "/status - ℹ️ عرض حالة البوت\n"
        "/support - 🤝 مركز الدعم والمساعدة",
        reply_markup=reply_markup
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
    """Starts the trade conversation by asking for the order type."""
    
    # Reset is_sniping flag
    context.user_data['is_sniping'] = False
    
    keyboard = [
        [InlineKeyboardButton("1. أمر السوق (Market)", callback_data='order_type_market')],
        [InlineKeyboardButton("2. أمر محدد (Limit)", callback_data='order_type_limit')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "**📈 بدء التداول العادي**\n\n"
        "يرجى اختيار نوع الأمر الذي تريد تنفيذه:",
        reply_markup=reply_markup
    )
    
    return ORDER_TYPE
    # Check subscription before starting conversation (now only checks if user exists)
    if not await check_subscription(update, context):
        return ConversationHandler.END
        
    context.user_data['is_sniping'] = False
    await update.message.reply_text("1. 💰 أدخل مبلغ الشراء بالدولار الأمريكي (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

async def sniping_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the sniping conversation."""
    
    # Set is_sniping flag
    context.user_data['is_sniping'] = True
    
    # Sniping is always a Limit Order (or similar logic)
    context.user_data['order_type'] = 'limit'
    
    await update.message.reply_text("1. 💵 أدخل المبلغ الذي تريد التداول به (بالدولار الأمريكي USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT
    # Check subscription before starting conversation (now only checks if user exists)
    if not await check_subscription(update, context):
        return ConversationHandler.END
        
    context.user_data['is_sniping'] = True
    await update.message.reply_text("1. ⚡️ أدخل مبلغ القنص بالدولار الأمريكي (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

# --- API Key Setting Conversation ---

# --- NEW: Callback Handler for Exchange Selection ---
async def select_exchange_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processes the exchange selection from the inline keyboard."""
    query = update.callback_query
    await query.answer()
    
    # Extract the exchange ID from the callback data (e.g., 'select_exchange_binance')
    exchange_id = query.data.split('_')[-1]
    
    # Store the exchange ID temporarily in user_data
    context.user_data['exchange_id'] = exchange_id
    
    # Edit the original message to show the selection and ask for the API key
    await query.edit_message_text(
        f"✅ [اختيار المنصة] تم اختيار منصة **{exchange_id.upper()}**.\n\n"
        "🛠️ [إعداد API] يرجى إرسال مفتاح API الخاص بك الآن."
    )
    
    return WAITING_FOR_API_KEY

async def set_api_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to select the exchange and set the user's API key and secret."""
    
    # Define the list of supported exchanges (ccxt IDs and display names)
    EXCHANGES = {
        'binance': 'Binance',
        'bingx': 'BingX',
        'bitget': 'Bitget',
        'mexc': 'MEXC',
        'bybit': 'Bybit',
        'coinex': 'CoinEx',
        'okx': 'OKX',
        'kucoin': 'KuCoin',
    }
    
    # Create the inline keyboard buttons
    keyboard = []
    row = []
    for ccxt_id, display_name in EXCHANGES.items():
        # The callback data will be 'select_exchange_{ccxt_id}'
        row.append(InlineKeyboardButton(display_name, callback_data=f"select_exchange_{ccxt_id}"))
        if len(row) == 3: # 3 buttons per row
            keyboard.append(row)
            row = []
    if row: # Add the last row if it's not full
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🛠️ [إعداد API] يرجى اختيار منصة التداول التي تريد ربطها بالبوت:",
        reply_markup=reply_markup
    )
    
    return SELECT_EXCHANGE

async def set_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the API key and asks for the API secret."""
    api_key = update.message.text.strip()
    
    # Store the API key temporarily in user_data
    context.user_data['api_key'] = api_key
    
    await update.message.reply_text(
        "🔑 [إعداد API] تم حفظ مفتاح API. يرجى إرسال مفتاح API السري (API Secret) الآن."
    )
    
    return WAITING_FOR_API_SECRET

async def set_api_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the API secret and saves all data (exchange, key, secret) to the database."""
    from database import get_user_by_api_key # Local import to fix the recurring issue
    
    user_id = update.effective_user.id
    api_secret = update.message.text.strip()
    api_key = context.user_data.get('api_key')
    exchange_id = context.user_data.get('exchange_id')
    
    if not api_key or not exchange_id:
        await update.message.reply_text("🚨 [ERROR] حدث خطأ. يرجى إعادة المحاولة باستخدام /set_api.")
        return ConversationHandler.END
        
    # Ensure user exists in DB before attempting to update keys
    await add_new_user(user_id) 
    
    try:
        # Save to database
        # NOTE: update_api_keys now accepts exchange_id as the second argument
        await update_api_keys(user_id, exchange_id, api_key, api_secret)
        
        await update.message.reply_text(
            f"✅ [نجاح] تم حفظ مفاتيح API لمنصة **{exchange_id.upper()}** بنجاح! جاري التحقق من الصلاحيات..."
        )
        
    except Exception as e:
        await update.message.reply_text(f"🚨 [ERROR] فشل حفظ مفاتيح API في قاعدة البيانات: {e}")
        
    # --- NEW: Check Withdrawal Permission (Generalized) ---
    user_record = await get_user(user_id)
    
    # VIP users (Owner and Abood) are assumed to have correct keys and we skip the strict withdrawal check
    if user_id in WHITELISTED_USERS:
        await update.message.reply_text("✅ **صلاحيات المفاتيح مكتملة (VIP)!**\n"
                                        "تم افتراض تفعيل جميع الصلاحيات اللازمة (بما في ذلك السحب) لمستخدمي القائمة البيضاء.\n\n"
                                        "يمكنك الآن استخدام أوامر التداول: /trade أو /sniping.")
        
    else:
        # The original logic for checking withdrawal permission is complex and relies on the exchange.
        # Since we now support multiple exchanges, we will simplify the message and rely on the user to ensure permissions.
        # The original code had a check_withdrawal_permission function which is not fully provided.
        # We will keep the original logic for non-VIP users but update the message.
        await update.message.reply_text("✅ **تم حفظ مفاتيح API بنجاح!**\n"
                                        "يرجى التأكد من تفعيل صلاحيات **القراءة، التداول، والسحب** على منصة التداول.\n\n"
                                        "يمكنك الآن استخدام أوامر التداول: /trade أو /sniping.")
        
    # Clear temporary data
    context.user_data.pop('api_key', None)
    context.user_data.pop('exchange_id', None)
    
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

# --- Grid Trading Conversation Handlers ---

# Placeholder for the new, robust grid trading logic
async def grid_trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the grid trading conversation."""
    if not await check_subscription(update, context):
        return ConversationHandler.END
        
    await update.message.reply_text("1. 🪙 أدخل رمز العملة للتداول الشبكي (مثال: BTC/USDT):", reply_markup=ForceReply(selective=True))
    return GRID_SYMBOL

async def get_grid_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the symbol and asks for the lower bound."""
    symbol = update.message.text.strip().upper()
    if '/' not in symbol:
        await update.message.reply_text("❌ تنسيق الرمز غير صحيح. يرجى استخدام التنسيق (BASE/QUOTE) مثل BTC/USDT.")
        return GRID_SYMBOL
        
    context.user_data['grid_symbol'] = symbol
    await update.message.reply_text("2. ⬇️ أدخل الحد الأدنى للسعر (Lower Bound):", reply_markup=ForceReply(selective=True))
    return LOWER_BOUND

async def get_lower_bound(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the lower bound and asks for the upper bound."""
    try:
        lower_bound = float(update.message.text)
        if lower_bound <= 0:
            await update.message.reply_text("❌ يجب أن يكون الحد الأدنى للسعر رقماً موجباً (أكبر من صفر).")
            return LOWER_BOUND
            
        context.user_data['lower_bound'] = lower_bound
        await update.message.reply_text("3. ⬆️ أدخل الحد الأعلى للسعر (Upper Bound):", reply_markup=ForceReply(selective=True))
        return UPPER_BOUND
    except ValueError:
        await update.message.reply_text("❌ إدخال غير صحيح. يرجى إدخال رقم.")
        return LOWER_BOUND

async def get_upper_bound(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the upper bound and asks for the number of grids."""
    try:
        upper_bound = float(update.message.text)
        lower_bound = context.user_data['lower_bound']
        
        if upper_bound <= lower_bound:
            await update.message.reply_text("❌ يجب أن يكون الحد الأعلى للسعر أكبر من الحد الأدنى للسعر.")
            return UPPER_BOUND
            
        context.user_data['upper_bound'] = upper_bound
        await update.message.reply_text("4. 🔢 أدخل عدد خطوط الشبكة (Grids) (مثال: 10):", reply_markup=ForceReply(selective=True))
        return NUM_GRIDS
    except ValueError:
        await update.message.reply_text("❌ إدخال غير صحيح. يرجى إدخال رقم.")
        return UPPER_BOUND

async def get_num_grids(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the number of grids and asks for the amount per order."""
    try:
        num_grids = int(update.message.text)
        if num_grids < 2 or num_grids > 50:
            await update.message.reply_text("❌ يجب أن يكون عدد خطوط الشبكة بين 2 و 50.")
            return NUM_GRIDS
            
        context.user_data['num_grids'] = num_grids
        await update.message.reply_text("5. 💵 أدخل مبلغ الشراء/البيع لكل أمر (بالدولار الأمريكي USDT):", reply_markup=ForceReply(selective=True))
        return AMOUNT_PER_ORDER
    except ValueError:
        await update.message.reply_text("❌ إدخال غير صحيح. يرجى إدخال عدد صحيح.")
        return NUM_GRIDS

async def get_amount_per_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the amount per order and starts the grid creation process."""
    try:
        amount_per_order = float(update.message.text)
        if amount_per_order <= 0:
            await update.message.reply_text("❌ يجب أن يكون مبلغ الأمر رقماً موجباً.")
            return AMOUNT_PER_ORDER
            
        context.user_data['amount_per_order'] = amount_per_order
        
        # All data collected, proceed to grid creation
        await create_grid_orders(update, context)
        
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ إدخال غير صحيح. يرجى إدخال رقم.")
        return AMOUNT_PER_ORDER

# --- New Grid Creation Logic ---
async def create_grid_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calculates and places the initial grid orders and saves the grid to the database."""
    user_id = update.effective_user.id
    user_data = context.user_data
    
    symbol = user_data['grid_symbol']
    # Use Decimal for all financial calculations
    try:
        lower_bound = Decimal(str(user_data['lower_bound']))
        upper_bound = Decimal(str(user_data['upper_bound']))
        num_grids = int(user_data['num_grids'])
        amount_per_order = Decimal(str(user_data['amount_per_order']))
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] خطأ في تحويل المدخلات إلى أرقام: {e}")
        return
    
    await update.message.reply_text(
        "✅ **تم استلام جميع مدخلات الشبكة!**\n"
        f"العملة: {symbol}\n"
        f"النطاق: {lower_bound} - {upper_bound}\n"
        f"عدد الخطوط: {num_grids}\n"
        f"مبلغ الأمر: {amount_per_order} USDT\n\n"
        "جاري الآن حساب نقاط الشبكة ووضع الأوامر الأولية..."
    )
    
    # 1. Initialize Exchange
    user_record = await get_user(user_id)
    if not user_record or not user_record.get('api_key'):
        await update.message.reply_text("🚨 [ERROR] لم يتم العثور على مفاتيح API الخاصة بك. يرجى إدخالها أولاً باستخدام /set_api.")
        return

    try:
        exchange = initialize_exchange(user_id, user_record['api_key'], user_record['api_secret'])
        await exchange.load_markets()
        if symbol not in exchange.markets:
            await update.message.reply_text(f"🚨 [ERROR] رمز العملة {symbol} غير متوفر على المنصة.")
            return
            
        market = exchange.markets[symbol]
        # Ensure precision is a non-negative integer
        price_precision = max(0, int(market['precision']['price']))
        amount_precision = max(0, int(market['precision']['amount']))
        
    except Exception as e:
        await update.message.reply_text(f"🚨 [ERROR] فشل تهيئة الاتصال بالمنصة أو جلب معلومات السوق: {type(e).__name__}: {e}")
        return
    
    # 2. Calculate Grid Points using Decimal
    try:
        price_range = upper_bound - lower_bound
        # Ensure num_grids is Decimal for division
        if num_grids == 0:
            await update.message.reply_text(f"🚨 [ERROR] عدد خطوط الشبكة لا يمكن أن يكون صفرًا.")
            return ConversationHandler.END
        grid_step = price_range / Decimal(num_grids)
        
        grid_points = []
        for i in range(num_grids + 1):
            price = lower_bound + Decimal(i) * grid_step
            grid_points.append(price)
        
        # 3. Place Initial Orders (Buy orders at lower points)
        placed_orders = []
        
        # We need num_grids buy orders, placed at grid_points[0] to grid_points[num_grids-1]
        for i in range(num_grids):
            # Round price to exchange precision
            # The precision value from ccxt is an integer (number of decimal places)
            # The round() function in Python takes an integer as the second argument
            # We ensure price_precision is an integer before passing it to round()
            # Use quantize for Decimal rounding to ensure correct behavior, especially for small numbers
            # The precision is determined by the number of decimal places (price_precision)
            # Use quantize for Decimal rounding to ensure correct behavior, especially for small numbers
            # We must use the correct quantizer format which is '0.000...'
            # Handle case where price_precision is 0 (e.g., for BTC/USDT on some exchanges)
            if price_precision > 0:
                quantizer_str = '0.' + '0' * price_precision
                quantizer = Decimal(quantizer_str)
                buy_price = grid_points[i].quantize(quantizer)
            else:
                # If precision is 0, quantize to 1 (no decimal places)
                # Ensure the quantizer is based on the number of decimal places, not the value 1
                # The correct quantizer for 0 decimal places is Decimal('1')
                buy_price = grid_points[i].quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            
            # Calculate amount in base currency (e.g., BTC)
            # amount_per_order is in quote currency (USDT)
            if buy_price == 0:
                # This should not happen with valid inputs, but handle it defensively
                await update.message.reply_text(f"🚨 [ERROR] محاولة القسمة على صفر: سعر الشراء هو صفر. يرجى التحقق من مدخلات النطاق.")
                return ConversationHandler.END
            buy_amount_base = amount_per_order / buy_price
            
            # Round amount to exchange precision
            # We ensure amount_precision is an integer before passing it to round()
            # Use quantize for Decimal rounding
            if amount_precision > 0:
                quantizer_amount_str = '0.' + '0' * amount_precision
                quantizer_amount = Decimal(quantizer_amount_str)
                buy_amount_base = buy_amount_base.quantize(quantizer_amount)
            else:
                buy_amount_base = buy_amount_base.quantize(Decimal('1'))
            
            # --- NEW: Check Minimum Order Amount ---
            min_amount = Decimal(market['limits']['amount']['min']) if market['limits']['amount']['min'] is not None else Decimal('0')
            
            if buy_amount_base < min_amount:
                await update.message.reply_text(
                    f"⚠️ [WARNING] تم تخطي أمر الشراء عند {buy_price:.{int(price_precision)}f} لأن الكمية المحسوبة ({buy_amount_base:.{int(amount_precision)}f}) "
                    f"أقل من الحد الأدنى لحجم الأمر للمنصة ({min_amount:.{int(amount_precision)}f}). يرجى زيادة مبلغ الأمر لكل شبكة."
                )
                continue # Skip placing this order
            
            # --- NEW: Check Minimum Notional Value (Total Order Value) ---
            min_notional = Decimal(market['limits']['cost']['min']) if market['limits']['cost']['min'] is not None else Decimal('0')
            order_notional = buy_amount_base * buy_price
            
            if order_notional < min_notional:
                await update.message.reply_text(
                    f"⚠️ [WARNING] تم تخطي أمر الشراء عند {buy_price:.{int(price_precision)}f} لأن القيمة الإجمالية للأمر ({order_notional:.2f} USDT) "
                    f"أقل من الحد الأدنى للقيمة الإجمالية للمنصة ({min_notional:.2f} USDT). يرجى زيادة مبلغ الأمر لكل شبكة."
                )
                continue # Skip placing this order
            
            # Convert Decimal back to float for ccxt (which expects float/string)
            buy_price_float = float(buy_price)
            buy_amount_float = float(buy_amount_base)
            
            try:
                order = await exchange.create_limit_buy_order(symbol, buy_amount_float, buy_price_float)
                placed_orders.append(order)
                await update.message.reply_text(f"🛒 [BUY] أمر شراء محدد عند: {buy_price_float:.{int(price_precision)}f} بكمية: {buy_amount_float:.{int(amount_precision)}f}")
            except Exception as e:
                await update.message.reply_text(f"⚠️ [WARNING] فشل وضع أمر الشراء عند {buy_price_float}: {e}")
                
        if not placed_orders:
            await update.message.reply_text("🚨 [ERROR] فشل وضع أي أوامر شراء. يرجى التحقق من رصيد USDT الخاص بك.")
            return
            
        # 4. Save Grid to Database
        # Convert Decimal back to float for database storage (assuming DB uses float/real)
        grid_id = await add_new_grid(
            user_id, 
            symbol, 
            float(lower_bound), 
            float(upper_bound), 
            num_grids, 
            float(amount_per_order)
        )
        
        await update.message.reply_text(
            f"✅ **تم إنشاء شبكة التداول بنجاح!**\n"
            f"معرف الشبكة: **{grid_id}**\n"
            f"تم وضع **{len(placed_orders)}** أمر شراء مبدئي.\n\n"
            "**بدء المراقبة:** سيقوم البوت الآن بمراقبة هذه الشبكة. عند تنفيذ أي أمر شراء، سيقوم البوت تلقائياً بوضع أمر بيع محدد (Limit Sell) عند نقطة الشبكة التالية."
        )
        
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] حدث خطأ أثناء إنشاء الشبكة: {type(e).__name__}: {e}")
    finally:
        if 'exchange' in locals():
            await exchange.close()

# --- Grid Stop Conversation Handlers ---


# --- Grid Stop Conversation Handlers ---

async def stop_grid_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the grid stopping conversation."""
    user_id = update.effective_user.id
    user_grids = await get_user_grids(user_id)
    
    if not user_grids:
        await update.message.reply_text("❌ لا توجد لديك أي شبكات تداول مسجلة لإيقافها.")
        return ConversationHandler.END
        
    active_grids = [g for g in user_grids if g['status'] == 'active']
    
    if not active_grids:
        await update.message.reply_text("❌ لا توجد لديك أي شبكات تداول **نشطة** لإيقافها.")
        return ConversationHandler.END
        
    message = "🛑 **إيقاف شبكة التداول**\n\n"
    message += "الشبكات النشطة لديك:\n"
    for grid in active_grids:
        message += f"**ID: {grid['id']}** | {grid['symbol']} | النطاق: {grid['lower_bound']} - {grid['upper_bound']}\n"
        
    message += "\nيرجى إدخال **معرف الشبكة (ID)** الذي تريد إيقافه:"
    
    await update.message.reply_text(message, reply_markup=ForceReply(selective=True))
    return 10 # New state for STOP_GRID_ID

async def get_grid_id_to_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the grid ID and stops the grid."""
    user_id = update.effective_user.id
    
    try:
        grid_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ إدخال غير صحيح. يرجى إدخال رقم صحيح (معرف الشبكة).")
        return 10
        
    # 1. Check if the grid belongs to the user and is active
    user_grids = await get_user_grids(user_id)
    target_grid = next((g for g in user_grids if g['id'] == grid_id and g['status'] == 'active'), None)
    
    if not target_grid:
        await update.message.reply_text(f"❌ لم يتم العثور على شبكة نشطة بالمعرف **{grid_id}** أو أنها لا تخصك.")
        return ConversationHandler.END
        
    # 2. Initialize Exchange and Cancel Orders
    user_record = await get_user(user_id)
    
    try:
        exchange = initialize_exchange(user_id, user_record['api_key'], user_record['api_secret'])
        
        # Fetch all open orders for the symbol
        open_orders = await exchange.fetch_open_orders(target_grid['symbol'])
        
        cancelled_count = 0
        for order in open_orders:
            # A simple check: cancel all open limit orders for the symbol
            if order['type'] == 'limit':
                await exchange.cancel_order(order['id'], target_grid['symbol'])
                cancelled_count += 1
                
        # 3. Stop Grid in Database
        await stop_grid(grid_id)
        
        await update.message.reply_text(
            f"✅ **تم إيقاف شبكة التداول بنجاح!**\n"
            f"معرف الشبكة: **{grid_id}**\n"
            f"العملة: {target_grid['symbol']}\n"
            f"تم إلغاء **{cancelled_count}** أمر مفتوح على المنصة.\n\n"
            "لن يتم مراقبة هذه الشبكة بعد الآن."
        )
        
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] حدث خطأ أثناء إيقاف الشبكة: {type(e).__name__}: {e}")
    finally:
        if 'exchange' in locals():
            await exchange.close()
            
    return ConversationHandler.END


async def get_order_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the order type selection."""
    query = update.callback_query
    await query.answer()
    
    order_type = query.data.split('_')[-1]
    context.user_data['order_type'] = order_type
    
    await query.edit_message_text(f"✅ تم اختيار: **أمر {order_type.capitalize()}**")
    
    if order_type == 'limit':
        await query.message.reply_text("1. 💰 أدخل سعر التنفيذ المحدد (Limit Price):", reply_markup=ForceReply(selective=True))
        return LIMIT_PRICE
    else: # Market
        await query.message.reply_text("1. 💵 أدخل المبلغ الذي تريد التداول به (بالدولار الأمريكي USDT):", reply_markup=ForceReply(selective=True))
        return AMOUNT

async def get_limit_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the limit price for a limit order."""
    try:
        limit_price = float(update.message.text)
        if limit_price <= 0:
            await update.message.reply_text("❌ يجب أن يكون سعر التنفيذ رقماً موجباً.")
            return LIMIT_PRICE
            
        context.user_data['limit_price'] = limit_price
        await update.message.reply_text("2. 💵 أدخل المبلغ الذي تريد التداول به (بالدولار الأمريكي USDT):", reply_markup=ForceReply(selective=True))
        return AMOUNT
    except ValueError:
        await update.message.reply_text("❌ إدخال غير صحيح. يرجى إدخال رقم.")
        return LIMIT_PRICE

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

# --- GRID MONITORING LOOP ---
# --- New Grid Monitoring Logic ---
async def grid_monitoring_loop(application: Application):
    """Continuously monitors active grids and places new orders."""
    while True:
        try:
            active_grids = await get_active_grids()
            if not active_grids:
                # Sleep longer if no active grids
                await asyncio.sleep(60) 
                continue
                
            for grid in active_grids:
                user_id = grid['user_id']
                grid_id = grid['id']
                symbol = grid['symbol']
                
                # Use Decimal for all calculations
                try:
                    lower_bound = Decimal(str(grid['lower_bound']))
                    upper_bound = Decimal(str(grid['upper_bound']))
                    num_grids = int(grid['num_grids'])
                    amount_per_order = Decimal(str(grid['amount_per_order']))
                except Exception as e:
                    print(f"Error converting grid data to Decimal for grid {grid_id}: {e}")
                    continue
                
                user_record = await get_user(user_id)
                if not user_record or not user_record.get('api_key'):
                    # Grid is active but user keys are missing, stop the grid
                    await stop_grid(grid_id)
                    await application.bot.send_message(user_id, f"🚨 **توقف الشبكة {grid_id}**\n\nتم إيقاف شبكة التداول لـ {symbol} بسبب عدم توفر مفاتيح API.")
                    continue
                    
                try:
                    exchange = initialize_exchange(user_id, user_record['api_key'], user_record['api_secret'])
                    await exchange.load_markets()
                    market = exchange.markets[symbol]
                    price_precision = market['precision']['price']
                    amount_precision = market['precision']['amount']
                    
                    # 1. Calculate Grid Points
                    price_range = upper_bound - lower_bound
                    grid_step = price_range / Decimal(num_grids)
                    
                    grid_points = []
                    for i in range(num_grids + 1):
                        price = lower_bound + Decimal(i) * grid_step
                        grid_points.append(price)
                    
                    # 2. Fetch Open Orders
                    open_orders = await exchange.fetch_open_orders(symbol)
                    
                    # 3. Check for Filled Orders (Simplified Logic)
                    
                    # Get the current price to determine which side (Buy/Sell) should be open
                    ticker = await exchange.fetch_ticker(symbol)
                    current_price = Decimal(str(ticker['last']))
                    
                    # Determine the next Buy and Sell points
                    
                    # Find the nearest grid point below the current price for Buy
                    next_buy_price = None
                    for price in sorted(grid_points, reverse=True):
                        if price < current_price:
                            next_buy_price = price
                            break
                            
                    # Find the nearest grid point above the current price for Sell
                    next_sell_price = None
                    for price in sorted(grid_points):
                        if price > current_price:
                            next_sell_price = price
                            break
                            
                    # --- Logic for Buy Order Replacement (If a Buy was filled) ---
                    # Check if the next Buy order is open
                    # We check if an open order exists at the expected next_buy_price
                    buy_order_open = any(
                        order['side'] == 'buy' and 
                        round(Decimal(str(order['price'])), price_precision) == round(next_buy_price, price_precision)
                        for order in open_orders
                    )
                    
                    if next_buy_price and not buy_order_open:
                        # A Buy order was filled (or cancelled), place a new Sell order at the next point up
                        sell_price = next_buy_price + grid_step
                        
                        # Check if the sell price is within the upper bound
                        if sell_price <= upper_bound:
                            # Place the Sell Limit Order
                            sell_amount_base = amount_per_order / sell_price # Approximate amount
                            sell_amount_base = round(sell_amount_base, amount_precision)
                            
                            # Convert Decimal back to float for ccxt
                            sell_price_float = float(round(sell_price, price_precision))
                            sell_amount_float = float(sell_amount_base)
                            
                            try:
                                await exchange.create_limit_sell_order(symbol, sell_amount_float, sell_price_float)
                                await application.bot.send_message(user_id, f"📈 **شبكة {grid_id} (SELL)**\n\nتم تنفيذ أمر شراء، ووضع أمر بيع جديد عند: {sell_price_float:.{price_precision}f}")
                            except Exception as e:
                                await application.bot.send_message(user_id, f"⚠️ **شبكة {grid_id} (ERROR)**\n\nفشل وضع أمر البيع عند {sell_price_float}: {e}")
                                
                        # Also, place a new Buy order at the point below the filled Buy order (if within lower bound)
                        new_buy_price = next_buy_price - grid_step
                        if new_buy_price >= lower_bound:
                            buy_amount_base = amount_per_order / new_buy_price
                            buy_amount_base = round(buy_amount_base, amount_precision)
                            
                            # Convert Decimal back to float for ccxt
                            new_buy_price_float = float(round(new_buy_price, price_precision))
                            buy_amount_float = float(buy_amount_base)
                            
                            try:
                                await exchange.create_limit_buy_order(symbol, buy_amount_float, new_buy_price_float)
                                await application.bot.send_message(user_id, f"🛒 **شبكة {grid_id} (BUY)**\n\nتم وضع أمر شراء جديد عند: {new_buy_price_float:.{price_precision}f}")
                            except Exception as e:
                                await application.bot.send_message(user_id, f"⚠️ **شبكة {grid_id} (ERROR)**\n\nفشل وضع أمر الشراء عند {new_buy_price_float}: {e}")
                                
                    # --- Logic for Sell Order Replacement (If a Sell was filled) ---
                    # Check if the next Sell order is open
                    sell_order_open = any(
                        order['side'] == 'sell' and 
                        round(Decimal(str(order['price'])), price_precision) == round(next_sell_price, price_precision)
                        for order in open_orders
                    )
                    
                    if next_sell_price and not sell_order_open:
                        # A Sell order was filled (or cancelled), place a new Buy order at the next point down
                        buy_price = next_sell_price - grid_step
                        
                        # Check if the buy price is within the lower bound
                        if buy_price >= lower_bound:
                            # Place the Buy Limit Order
                            buy_amount_base = amount_per_order / buy_price
                            buy_amount_base = round(buy_amount_base, amount_precision)
                            
                            # Convert Decimal back to float for ccxt
                            buy_price_float = float(round(buy_price, price_precision))
                            buy_amount_float = float(buy_amount_base)
                            
                            try:
                                await exchange.create_limit_buy_order(symbol, buy_amount_float, buy_price_float)
                                await application.bot.send_message(user_id, f"🛒 **شبكة {grid_id} (BUY)**\n\nتم تنفيذ أمر بيع، ووضع أمر شراء جديد عند: {buy_price_float:.{price_precision}f}")
                            except Exception as e:
                                await application.bot.send_message(user_id, f"⚠️ **شبكة {grid_id} (ERROR)**\n\nفشل وضع أمر الشراء عند {buy_price_float}: {e}")
                                
                        # Also, place a new Sell order at the point above the filled Sell order (if within upper bound)
                        new_sell_price = next_sell_price + grid_step
                        if new_sell_price <= upper_bound:
                            sell_amount_base = amount_per_order / new_sell_price # Approximate amount
                            sell_amount_base = round(sell_amount_base, amount_precision)
                            
                            # Convert Decimal back to float for ccxt
                            new_sell_price_float = float(round(new_sell_price, price_precision))
                            sell_amount_float = float(sell_amount_base)
                            
                            try:
                                await exchange.create_limit_sell_order(symbol, sell_amount_float, new_sell_price_float)
                                await application.bot.send_message(user_id, f"📈 **شبكة {grid_id} (SELL)**\n\nتم وضع أمر بيع جديد عند: {new_sell_price_float:.{price_precision}f}")
                            except Exception as e:
                                await application.bot.send_message(user_id, f"⚠️ **شبكة {grid_id} (ERROR)**\n\nفشل وضع أمر البيع عند {new_sell_price_float}: {e}")
                                
                except Exception as e:
                    print(f"Error monitoring grid {grid_id}: {e}")
                    await application.bot.send_message(user_id, f"🚨 **خطأ فادح في مراقبة الشبكة {grid_id}**\n\nالخطأ: {type(e).__name__}: {e}")
                finally:
                    if 'exchange' in locals():
                        await exchange.close()
                        
            # Sleep for a short interval before checking again
            await asyncio.sleep(5) 
            
        except Exception as e:
            print(f"Global Grid Monitoring Error: {e}")
            await asyncio.sleep(60) # Sleep longer on global error

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
     # API Setup Conversation
    api_setup_handler = ConversationHandler(
        entry_points=[CommandHandler("set_api", set_api_start)],
        states={
            SELECT_EXCHANGE: [CallbackQueryHandler(select_exchange_callback, pattern=r'^select_exchange_')],
            WAITING_FOR_API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_api_key)],
            WAITING_FOR_API_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_api_secret)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(api_setup_handler)    
    # Conversation Handler Setup (Trade/Sniping)
    grid_stop_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("stop_grid", stop_grid_start)],
        states={
            STOP_GRID_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_grid_id_to_stop)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True
    )
    
    grid_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("grid_trade", grid_trade_start)],
        states={
            GRID_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_grid_symbol)],
            LOWER_BOUND: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_lower_bound)],
            UPPER_BOUND: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_upper_bound)],
            NUM_GRIDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_num_grids)],
            AMOUNT_PER_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount_per_order)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True
    )
    
    trade_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", trade_start), CommandHandler("sniping", sniping_start)],
        states={
            ORDER_TYPE: [CallbackQueryHandler(get_order_type, pattern='^order_type_')],
            LIMIT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_limit_price)],
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
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("cancel", simple_cancel_command))
    application.add_handler(CallbackQueryHandler(approve_subscription_callback, pattern='^approve_subscription_'))
    application.add_handler(grid_stop_conv_handler)
    application.add_handler(grid_conv_handler)
    application.add_handler(trade_conv_handler)
    application.add_handler(subscription_conv_handler)
    # application.add_handler(api_key_conv_handler) # This line is a duplicate and uses the wrong name. The correct handler is api_setup_handler, which is already added on line 1522.
    
    # Language Selection Handlers
    application.add_handler(CallbackQueryHandler(language_callback_handler, pattern='^select_language$'))
    application.add_handler(CallbackQueryHandler(set_language, pattern='^set_lang_'))
    
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
    
    # Start the grid monitoring loop after the event loop is running
    async def post_init_callback(application: Application):
        asyncio.create_task(grid_monitoring_loop(application))
        
    # The post_init argument is not supported in this version. We will use the application.post_init hook instead.
    application.post_init = post_init_callback
    
    application.run_polling(poll_interval=1.0, allowed_updates=Update.ALL_TYPES)

@app.route('/', methods=['GET'])
def home():
    return "Telegram Bot is running (Polling mode with Keep-Alive).", 200


if __name__ == "__main__":
    main()

# --- LANGUAGE SELECTION HANDLERS ---

async def language_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'select_language' callback and presents language options."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("العربية 🇸🇦", callback_data='set_lang_ar')],
        [InlineKeyboardButton("English 🇬🇧", callback_data='set_lang_en')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🌐 **اختر لغتك المفضلة / Select your preferred language:**",
        reply_markup=reply_markup
    )

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the language selection callback and updates the user's language in the database."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    callback_data = query.data
    
    if callback_data == 'set_lang_ar':
        language_code = 'ar'
        message_text = "✅ تم اختيار اللغة **العربية** كلغة مفضلة لك."
    elif callback_data == 'set_lang_en':
        language_code = 'en'
        message_text = "✅ Language set to **English**."
    else:
        return # Should not happen

    # Update the language in the database
    from database import update_user_language
    await update_user_language(user_id, language_code)

    await query.edit_message_text(message_text)

# --- END LANGUAGE SELECTION HANDLERS ---

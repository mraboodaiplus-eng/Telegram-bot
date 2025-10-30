# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
import ccxt.async_support as ccxt
import asyncio
import os
import sys
import datetime
from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters

# --- NEW IMPORTS ---
from database import init_db, get_user, add_new_user, update_subscription_status, is_subscription_active, setup_vip_api_keys, update_api_keys

# Flask app instance
app = Flask(__name__)

# Global variable to hold the Application instance
application = None

# --- CONFIGURATION AND CONSTANTS ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Owner's Real Information
OWNER_ID = 7281928709
BINGX_API_KEY = "M1OSlqx9F5TQD7eBxmitch4NLw9ZPpD9Xng28REiwDJe9bunCp8mPvu5GoV9QLJ3NIAO2b0YZu8GszVlIcaxw"
BINGX_API_SECRET = "ybuQhV2CzYrvJx9wnAH4gq01z25b2FZDtZguc89zCKaOfHO4NT9IlGxaPsDmgsbVvjl4M1ammvBOVHJ4fIaw"

# ABOOD's Real Information
ABOOD_ID = 5991392622
ABOOD_API_KEY = "bg_ec710cae5f25832f2476b517b605bb4a"
ABOOD_API_SECRET = "faca6ac6f1060c0c0a362a361af42c50b0b052a81572e248311047b4dc53870cd"

# Whitelisted users (Owner and friends)
WHITELISTED_USERS = [OWNER_ID, ABOOD_ID]
ADMIN_CHAT_ID = OWNER_ID 
ADMIN_TITLE = "المدير العام"

# Payment Details (For debt payment)
USDT_ADDRESS = "0xb85f1c645dbb80f2617823c069dcb038a9f79895"
COMMISSION_RATE = 0.10 # 10% commission

# Conversation States
AMOUNT, SYMBOL, PROFIT_PERCENT, USE_STOP_LOSS, STOP_LOSS_PERCENT = range(5)
WAITING_FOR_DEBT_SCREENSHOT = 51
API_KEY_STATE = 60
API_SECRET_STATE = 61


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
    
    SNIPING_DELAY = 0.01 
    attempts = 0
    MAX_ATTEMPTS_BEFORE_RELOAD = 100 
    
    while True:
        attempts += 1
        try:
            ticker = await exchange.fetch_ticker(symbol)
            
            if ticker and ticker.get('last') is not None:
                if attempts % MAX_ATTEMPTS_BEFORE_RELOAD == 0:
                    await exchange.load_markets(reload=True)
                    if symbol in exchange.markets:
                        await update.message.reply_text(f"✅ [SUCCESS] {symbol} متاح للتداول! السعر الحالي: {ticker['last']}")
                        return
                    else:
                        await update.message.reply_text(f"⚠️ [WARNING] {symbol} ظهر في التيكر لكنه غير متاح في الأسواق. جاري الانتظار...")
                        
                else:
                    await update.message.reply_text(f"✅ [SUCCESS] {symbol} متاح للتداول! السعر الحالي: {ticker['last']}")
                    return
                    
        except ccxt.BadSymbol:
            pass
        except Exception as e:
            await update.message.reply_text(f"⚠️ [WARNING] Sniping Error: {type(e).__name__}: {e}")
            await asyncio.sleep(1)
            
        await asyncio.sleep(SNIPING_DELAY)

async def execute_trade(update: Update, context: ContextTypes.DEFAULT_TYPE, params):
    user_id = update.effective_user.id
    user_record = await get_user(user_id)
    
    if not user_record or not user_record['api_key'] or not user_record['api_secret']:
        await update.message.reply_text("🚨 [ERROR] لم يتم العثور على مفاتيح API الخاصة بك. يرجى إدخالها أولاً.")
        return

    # Check for Smart Freeze (Debt System)
    if user_record.get('is_frozen', 0) == 1:
        await update.message.reply_text(
            f"❌ **حسابك مجمد مؤقتاً.**\n\n"
            f"لديك دين مستحق بقيمة **{user_record.get('debt_amount', 0.0):.2f} USDT**.\n"
            f"يرجى دفع العمولة المستحقة لإلغاء تجميد الحساب واستئناف التداول. استخدم الأمر /pay_debt"
        )
        return

    try:
        exchange = initialize_exchange(user_id, user_record['api_key'], user_record['api_secret'])
    except ValueError as e:
        await update.message.reply_text(f"🚨 [ERROR] خطأ في تهيئة الاتصال: {e}")
        return
        
    symbol = params['symbol']
    amount_usdt = params['amount']
    profit_percent = params['profit_percent']
    stop_loss_percent = params['stop_loss_percent']
    is_sniping = params.get('is_sniping', False)
    
    # Variables to track for commission calculation
    buy_cost = 0.0
    sell_revenue = 0.0
    
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
        
        buy_cost = total_cost if 'total_cost' in locals() else amount_usdt # Actual cost of the buy order
        await update.message.reply_text(f"📊 [DETAILS] Avg Price: {avg_price:.6f}, Quantity: {filled_amount:.6f}, Total Cost: {buy_cost:.2f} USDT")
        
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
            

        
        sell_revenue = filled_amount_precise * target_sell_price
        profit = sell_revenue - buy_cost
        
        # Only apply commission if it's a SNIPING trade AND the profit is positive
        if is_sniping and profit > 0:
            commission_amount = profit * COMMISSION_RATE
            
            # Update user's debt
            user_record = await get_user(user_id) # Re-fetch to ensure latest debt
            current_debt = user_record.get('debt_amount', 0.0)
            new_debt = current_debt + commission_amount
            
            # Freeze the account to force payment
            await update_subscription_status(user_id, debt_amount=new_debt, is_frozen=1)
            
            await update.message.reply_text(
                f"💰 **تم احتساب العمولة!**\n"
                f"الربح المتوقع من هذه الصفقة: {profit:.2f} USDT\n"
                f"عمولة القنص (10%): {commission_amount:.2f} USDT\n"
                f"إجمالي دينك المستحق: {new_debt:.2f} USDT\n\n"
                f"🚨 **تنبيه:** تم تجميد حسابك مؤقتاً حتى يتم سداد العمولة. استخدم الأمر /pay_debt"
            )
        elif is_sniping and profit <= 0:
            await update.message.reply_text("📉 **الصفقة خاسرة أو متعادلة.** لا توجد عمولة مستحقة.")
        
        # If not sniping, no commission is applied (as per user request)
        
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

# --- ACCESS CHECK (Replaces check_subscription) ---
async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if the user is whitelisted."""
    user_id = update.effective_user.id
    
    if user_id in WHITELISTED_USERS:
        return True
    
    await update.message.reply_text(
        "🔒 **الوصول مقيد.**\n\n"
        "هذه الخدمة متاحة فقط للمستخدمين في القائمة البيضاء."
    )
    return False

# --- TELEGRAM HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    await add_new_user(user_id)
    
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
                "/status - ℹ️ عرض حالة البوت\n"
                "**أوامر الإدارة:**\n"
                "/freeze [user_id] - 🥶 تجميد حساب المستخدم\n"
                "/unfreeze [user_id] - ✅ إلغاء تجميد حساب المستخدم\n"
                "/add_debt [user_id] [amount] - 💰 إضافة دين للمستخدم"
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
            welcome_message = (
                f"👋 مرحباً بك يا {username} (المستخدم المميز)!\n\n"
                "**الأوامر المتاحة:**\n"
                "/trade - 📈 تداول عادي (شراء وبيع)\n"
                "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
                "/cancel - ❌ إلغاء العملية الحالية\n"
                "/set_api - 🔑 إعداد مفاتيح API\n"
                "/status - ℹ️ عرض حالتك"
            )
        
        await update.message.reply_text(welcome_message)
        return
        
    # Non-whitelisted users see a simple message
    await update.message.reply_text(
        f"👋 مرحباً بك يا {username}!\n\n"
        "أهلاً بك في خدمة **LiveSniperBot** المتميزة.\n"
        "هذه الخدمة متاحة فقط للمستخدمين في القائمة البيضاء."
    )

# --- ADMIN COMMANDS ---
async def freeze_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to freeze a user's account."""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ هذا الأمر مخصص للمدير فقط.")
        return
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ الاستخدام: /freeze [user_id]")
        return
    
    target_id = int(context.args[0])
    await update_subscription_status(target_id, is_frozen=1)
    await update.message.reply_text(f"🥶 **تم تجميد حساب المستخدم** `{target_id}` بنجاح.")

async def unfreeze_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to unfreeze a user's account."""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ هذا الأمر مخصص للمدير فقط.")
        return
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ الاستخدام: /unfreeze [user_id]")
        return
    
    target_id = int(context.args[0])
    await update_subscription_status(target_id, is_frozen=0)
    await update.message.reply_text(f"✅ **تم إلغاء تجميد حساب المستخدم** `{target_id}` بنجاح.")

async def add_debt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to add debt to a user's account."""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ هذا الأمر مخصص للمدير فقط.")
        return
    
    if len(context.args) != 2 or not context.args[0].isdigit():
        await update.message.reply_text("❌ الاستخدام: /add_debt [user_id] [amount]")
        return
    
    try:
        target_id = int(context.args[0])
        debt_amount = float(context.args[1])
        
        user_record = await get_user(target_id)
        if not user_record:
            await update.message.reply_text(f"❌ المستخدم `{target_id}` غير موجود في قاعدة البيانات.")
            return
            
        new_debt = user_record.get('debt_amount', 0.0) + debt_amount
        await update_subscription_status(target_id, debt_amount=new_debt, is_frozen=1) # Freeze on debt
        
        await update.message.reply_text(f"💰 **تم إضافة دين** بقيمة {debt_amount:.2f} USDT للمستخدم `{target_id}`.\n"
                                        f"إجمالي الدين المستحق: {new_debt:.2f} USDT.\n"
                                        f"🚨 **تنبيه:** تم تجميد الحساب حتى السداد.")
        
    except ValueError:
        await update.message.reply_text("❌ الاستخدام: /add_debt [user_id] [amount]. يجب أن يكون المبلغ رقمًا.")

async def pay_debt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation for a user to pay their debt."""
    user_id = update.effective_user.id
    user_record = await get_user(user_id)
    debt = user_record.get('debt_amount', 0.0) if user_record else 0.0
    
    if debt <= 0:
        await update.message.reply_text("✅ ليس لديك أي ديون مستحقة. شكراً لك!")
        return ConversationHandler.END
        
    await update.message.reply_text(
        "💳 **سداد العمولة المستحقة**\n\n"
        f"دينك الحالي هو: **{debt:.2f} USDT**.\n"
        "يرجى تحويل المبلغ إلى العنوان التالي:\n\n"
        "**العنوان (USDT - BEP20):**\n"
        f"`{USDT_ADDRESS}`\n\n"
        "بعد التحويل، يرجى **إرسال لقطة شاشة** (صورة) لعملية التحويل كإثبات للدفع. سيتم إلغاء تجميد حسابك يدوياً بعد المراجعة."
    )
    return WAITING_FOR_DEBT_SCREENSHOT

async def receive_debt_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the screenshot sent by the user for debt payment."""
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if not update.message.photo:
        await update.message.reply_text("❌ لم يتم إرسال صورة. يرجى إرسال لقطة شاشة (سكرين شوت) لعملية الدفع.")
        return WAITING_FOR_DEBT_SCREENSHOT
        
    # 1. Send the screenshot to the admin
    photo_file_id = update.message.photo[-1].file_id
    caption = (
        f"🚨 **طلب سداد عمولة (Manual Review)** 🚨\n"
        f"المستخدم: @{username} (ID: `{user_id}`)\n"
        f"الرجاء التحقق من السداد وإلغاء تجميد الحساب يدوياً.\n"
        f"الأوامر الإدارية: /unfreeze {user_id} و /add_debt {user_id} -[amount]"
    )
    
    # Create the approval button (for admin to unfreeze)
    keyboard = [[InlineKeyboardButton("✅ إلغاء التجميد وتصفير الدين", callback_data=f'unfreeze_debt_{user_id}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=photo_file_id,
        caption=caption,
        reply_markup=reply_markup
    )
    
    # 2. Inform the user
    await update.message.reply_text(
        "✅ **تم استلام لقطة الشاشة بنجاح.**\n\n"
        "جاري الآن مراجعة عملية الدفع يدوياً من قبل المدير.\n"
        "سيتم إلغاء تجميد حسابك بعد التحقق من السداد.\n"
        "**شكراً لك على سداد العمولة!**"
    )
    
    return ConversationHandler.END

async def unfreeze_debt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    admin_id = query.from_user.id
    
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("❌ أنت لست المدير المخول لإجراء هذه العملية.", show_alert=True)
        return

    await query.answer("جاري إلغاء التجميد وتصفير الدين...", show_alert=False)
    
    try:
        target_user_id = int(query.data.split('_')[-1])
    except ValueError:
        await query.edit_message_caption(query.message.caption + "\n\n🚨 **خطأ:** لم يتم التعرف على معرف المستخدم.", reply_markup=None)
        return
        
    # 1. Update DB: Unfreeze and set debt to 0
    await update_subscription_status(target_user_id, is_frozen=0, debt_amount=0.0)
    
    # 2. Notify Client
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text="🎉 **تم إلغاء تجميد حسابك بنجاح!**\n\n"
                 "تم تصفير الدين المستحق.\n"
                 "يمكنك الآن البدء في استخدام البوت."
        )
        
        # 3. Update Admin Message
        await query.edit_message_caption(
            query.message.caption + 
            f"\n\n✅ **تم إلغاء التجميد وتصفير الدين بنجاح!**\n"
            f"تم الإخطار بواسطة: {query.from_user.first_name}",
            reply_markup=None # Remove button after action
        )
        
    except Exception as e:
        await query.edit_message_caption(
            query.message.caption + 
            f"\n\n⚠️ **فشل الإخطار!**\n"
            f"تم إلغاء التجميد وتصفير الدين في قاعدة البيانات، لكن فشل إرسال رسالة للمستخدم: {e}",
            reply_markup=None
        )

# --- Original Handlers ---

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
        
        keyboard = [
            [InlineKeyboardButton("✅ نعم", callback_data='use_sl_yes')],
            [InlineKeyboardButton("❌ لا", callback_data='use_sl_no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("4. 🛡️ هل تريد استخدام وقف الخسارة (Stop Loss)؟", reply_markup=reply_markup)
        return USE_STOP_LOSS
        
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return PROFIT_PERCENT

async def use_stop_loss_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'use_sl_yes':
        context.user_data['use_stop_loss'] = True
        await query.edit_message_text("5. 📉 أدخل نسبة وقف الخسارة (%):")
        return STOP_LOSS_PERCENT
    else:
        context.user_data['use_stop_loss'] = False
        context.user_data['stop_loss_percent'] = 0.0
        await query.edit_message_text("✅ تم تأكيد جميع البيانات. جاري تنفيذ عملية التداول...")
        
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
        await update.message.reply_text("✅ تم تأكيد جميع البيانات. جاري تنفيذ عملية التداول...")
        
        if context.user_data.get('is_sniping'):
            asyncio.create_task(sniping_and_trade(update, context, context.user_data))
        else:
            asyncio.create_task(execute_trade(update, context, context.user_data))
            
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return STOP_LOSS_PERCENT

# --- API Key Setting Conversation ---
async def set_api_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("🔑 **إعداد مفاتيح API**\n\n"
                                    "1. يرجى إرسال **API Key** الخاص بك:", reply_markup=ForceReply(selective=True))
    return API_KEY_STATE

async def set_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['temp_api_key'] = update.message.text.strip()
    await update.message.reply_text("2. يرجى إرسال **API Secret** الخاص بك:", reply_markup=ForceReply(selective=True))
    return API_SECRET_STATE

async def set_api_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    api_secret = update.message.text.strip()
    api_key = context.user_data['temp_api_key']
    user_id = update.effective_user.id
    
    await update_api_keys(user_id, api_key, api_secret)
    
    await update.message.reply_text("✅ **تم حفظ مفاتيح API بنجاح!**\n"
                                    "يمكنك الآن استخدام أوامر التداول: /trade أو /sniping.")
    
    return ConversationHandler.END

async def trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the trade conversation."""
    if not await check_access(update, context):
        return ConversationHandler.END
        
    context.user_data['is_sniping'] = False
    await update.message.reply_text("📈 **بدء عملية التداول**\n\n"
                                    "1. 💰 أدخل المبلغ الذي تريد التداول به (بالـ USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

async def sniping_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the sniping conversation."""
    if not await check_access(update, context):
        return ConversationHandler.END
        
    context.user_data['is_sniping'] = True
    await update.message.reply_text("⚡️ **بدء عملية القنص**\n\n"
                                    "1. 💰 أدخل المبلغ الذي تريد التداول به (بالـ USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the user's current status and debt."""
    user_id = update.effective_user.id
    user_record = await get_user(user_id)
    
    if user_id in WHITELISTED_USERS:
        await update.message.reply_text("👑 **حالة المستخدم:** القائمة البيضاء (وصول كامل).\n"
                                        "لا تنطبق قيود العمولة أو الديون.")
        return
        
    if not user_record:
        await update.message.reply_text("ℹ️ **حالة المستخدم:** غير مسجل. يرجى استخدام /start.")
        return
        
    debt = user_record.get('debt_amount', 0.0)
    is_frozen = user_record.get('is_frozen', 0)
    
    status_text = "ℹ️ **حالة حسابك**\n\n"
    status_text += f"**حالة التجميد:** {'🥶 مجمد' if is_frozen else '✅ نشط'}\n"
    status_text += f"**الدين المستحق:** {debt:.2f} USDT\n"
    
    if is_frozen:
        status_text += "\n❌ **الوصول مقيد.** يرجى سداد الدين باستخدام الأمر /pay_debt."
    elif debt > 0:
        status_text += "\n⚠️ **لديك دين مستحق.** يرجى سداده لتجنب التجميد الوشيك باستخدام الأمر /pay_debt."
    else:
        status_text += "\n✅ **حسابك في وضع جيد.**"
        
    await update.message.reply_text(status_text)


# MAIN FUNCTION
def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("FATAL ERROR: TELEGRAM_BOT_TOKEN is not set in environment variables.")
        sys.exit(1)
        
    asyncio.run(init_db())
    
    global application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Conversation Handler for Debt Payment Screenshot
    debt_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("pay_debt", pay_debt_command)],
        states={
            WAITING_FOR_DEBT_SCREENSHOT: [MessageHandler(filters.PHOTO & ~filters.COMMAND, receive_debt_screenshot)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True
    )
    
    # Conversation Handler for API Key Setup
    api_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("set_api", set_api_start)],
        states={
            API_KEY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_api_key, pass_user_data=True)],
            API_SECRET_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_api_secret, pass_user_data=True)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    
    # Conversation Handler for Trading and Sniping
    trade_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", trade_start), CommandHandler("sniping", sniping_start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_symbol)],
            PROFIT_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_profit_percent)],
            USE_STOP_LOSS: [CallbackQueryHandler(use_stop_loss_callback)],
            STOP_LOSS_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stop_loss_percent)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True
    )
    
    # Add all handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("cancel", simple_cancel_command))
    application.add_handler(CallbackQueryHandler(unfreeze_debt_callback, pattern='^unfreeze_debt_'))
    
    application.add_handler(debt_conv_handler)
    application.add_handler(api_conv_handler)
    application.add_handler(trade_conv_handler)
    
    # --- ADMIN COMMANDS ---
    application.add_handler(CommandHandler("freeze", freeze_user_command))
    application.add_handler(CommandHandler("unfreeze", unfreeze_user_command))
    application.add_handler(CommandHandler("add_debt", add_debt_command))
    
    # === START KEEP-ALIVE WEB SERVER (Flask) ===
    import threading
    def run_web_server():
        PORT = int(os.environ.get("PORT", 8080))
        app.run(host='0.0.0.0', port=PORT)

    threading.Thread(target=run_web_server, daemon=True).start()

    # === START POLLING BOT ===
    print("Bot is running in Polling mode... Send /start to the bot on Telegram.")
    application.run_polling(poll_interval=1.0, allowed_updates=Update.ALL_TYPES)

@app.route('/', methods=['GET'])
def home():
    return "Telegram Bot is running (Polling mode with Keep-Alive).", 200


if __name__ == "__main__":
    main()

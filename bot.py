# -*- coding: utf-8 -*-
from flask import Flask
from threading import Thread
import ccxt.async_support as ccxt
import asyncio
import os
import sys
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

# CONFIGURATION (Now using Environment Variables for Security)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
BINGX_API_KEY = os.environ.get("BINGX_API_KEY")
BINGX_API_SECRET = os.environ.get("BINGX_API_SECRET")
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID") # Allowed user ID as a string

# Conversation States
AMOUNT, SYMBOL, PROFIT_PERCENT, USE_STOP_LOSS, STOP_LOSS_PERCENT = range(5)

# BINGX TRADING LOGIC
def initialize_exchange():
    # Check if a specific CCXT class method for order creation is supported
    # create_market_buy_order_with_cost is a custom method, not standard CCXT
    # We will use the standard create_order with 'market' type and 'cost' param if supported by ccxt.bingx
    return ccxt.bingx({
        'apiKey': BINGX_API_KEY,
        'secret': BINGX_API_SECRET,
        'options': {'defaultType': 'spot'},
        'enableRateLimit': True,
    })

async def wait_for_listing(update: Update, context: ContextTypes.DEFAULT_TYPE, exchange, symbol):
    await update.message.reply_text(f"⏳ [SNIPING MODE] جاري انتظار إدراج العملة {symbol}...")
    SNIPING_DELAY = 0.03
    while True:
        try:
            # Use fetch_ticker to check for symbol existence
            ticker = await exchange.fetch_ticker(symbol)
            if ticker:
                await update.message.reply_text(f"✅ [SUCCESS] {symbol} is now listed! Current price: {ticker['last']}")
                return
        except ccxt.BadSymbol:
            # Symbol not found, continue waiting
            await asyncio.sleep(SNIPING_DELAY)
        except Exception as e:
            # Log other errors but continue sniping
            await update.message.reply_text(f"⚠️ [WARNING] Sniping Error: {type(e).__name__}: {e}")
            await asyncio.sleep(5)

async def execute_trade(update: Update, context: ContextTypes.DEFAULT_TYPE, params):
    exchange = initialize_exchange()
    symbol = params['symbol']
    amount_usdt = params['amount']
    profit_percent = params['profit_percent']
    stop_loss_percent = params['stop_loss_percent']
        
    try:
        await exchange.load_markets()
        
        # --- FIX 1: Use standard CCXT method for market buy with cost ---
        # The original code used a non-standard method: create_market_buy_order_with_cost
        # We use create_order with 'market' type and 'cost' parameter.
        await update.message.reply_text("🔗 [INFO] Markets loaded successfully.")
        await update.message.reply_text(f"🛒 [STEP 1/3] Placing Market Buy Order for {symbol} with cost {amount_usdt} USDT...")
        
        # The 'cost' parameter in CCXT is used to specify the amount in the quote currency (USDT in this case).
        # The 'amount' parameter is for the base currency amount.
        # We assume the user wants to spend 'amount_usdt' USDT.
        market_buy_order = await exchange.create_order(
            symbol=symbol,
            type='market',
            side='buy',
            amount=None, # Let the exchange calculate the amount
            price=None,
            params={'cost': amount_usdt} # Pass cost as a parameter
        )
        
        await update.message.reply_text(f"👍 [SUCCESS] Buy Order placed. ID: {market_buy_order['id']}")
        
        # --- FIX 2: Better order detail fetching and handling ---
        await update.message.reply_text("🔍 [STEP 2/3] Waiting for execution details...")
        
        # Wait a bit for the market order to fill
        await asyncio.sleep(2) 
        
        # Fetch the order details to get average price and filled amount
        order_details = await exchange.fetch_order(market_buy_order['id'], symbol)
        
        # Check if the order was filled
        if order_details.get('status') not in ['closed', 'filled']:
            # If not filled, try to fetch the trades associated with the order
            trades = await exchange.fetch_my_trades(symbol, since=None, limit=None, params={'order': market_buy_order['id']})
            
            if not trades:
                 raise ccxt.ExchangeError("Market order was not filled and no trades were found.")
            
            # Recalculate avg_price and filled_amount from trades if order status is not final
            filled_amount = sum(float(trade['amount']) for trade in trades)
            total_cost = sum(float(trade['cost']) for trade in trades)
            avg_price = total_cost / filled_amount if filled_amount else 0
            
            if not avg_price or not filled_amount:
                raise ccxt.ExchangeError("Failed to get execution details from order or trades.")
            
        else:
            # If status is closed/filled, use the details from the order object
            avg_price = float(order_details['average'])
            filled_amount = float(order_details['filled'])

            if not avg_price or not filled_amount:
                raise ccxt.ExchangeError("Failed to get execution details.")
        
        await update.message.reply_text(f"📊 [DETAILS] Avg Price: {avg_price:.6f}, Quantity: {filled_amount:.6f}")
        
        # --- STEP 3: Take Profit Limit Sell ---
        target_sell_price = avg_price * (1 + profit_percent / 100)
        await update.message.reply_text(f"🎯 [STEP 3/3] Placing Take Profit Limit Sell (+{profit_percent}%) at {target_sell_price:.6f}...")
        
        # Check if the symbol is tradable
        if symbol not in exchange.markets:
            raise ccxt.BadSymbol(f"Symbol {symbol} is not available on {exchange.id}.")
            
        # Adjust amount to market precision
        market = exchange.markets[symbol]
        precision = market['precision']['amount']
        
        # Use a safe method to round down to the required precision
        import math
        filled_amount_precise = math.floor(filled_amount * (10**precision)) / (10**precision)
        
        limit_sell_order = await exchange.create_limit_sell_order(symbol, filled_amount_precise, target_sell_price)
        await update.message.reply_text(f"📈 [SUCCESS] Take Profit Order placed. ID: {limit_sell_order['id']}")
        
        # --- OPTIONAL: Stop Loss Order ---
        if params['use_stop_loss']:
            stop_loss_price = avg_price * (1 - stop_loss_percent / 100)
            await update.message.reply_text(f"🛡️ [OPTIONAL] Placing Stop Loss Order (-{stop_loss_percent}%) at {stop_loss_price:.6f}...")
            
            # Use create_stop_loss_order which is not always supported or might require specific params
            # A safer approach is to use create_order with type='stop_loss' if supported, or a limit sell order as a stop-limit
            # Given the original code used create_stop_loss_order, we'll keep it but note it might fail on some exchanges.
            # We will assume BingX supports it as a market stop loss, or a stop limit with price as stop price.
            # The original code did not specify a limit price, which is common for a market stop loss.
            stop_order = await exchange.create_order(
                symbol=symbol,
                type='stop_market', # Assuming stop_market for simplicity and direct execution
                side='sell',
                amount=filled_amount_precise,
                price=None, # No limit price for market stop
                params={'stopPrice': stop_loss_price} # Pass stop price as a parameter
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
        await exchange.close()
        await update.message.reply_text("🔌 [INFO] Connection closed.")

async def sniping_and_trade(update: Update, context: ContextTypes.DEFAULT_TYPE, params):
    exchange = initialize_exchange()
    symbol = params['symbol']
    
    # 1. Wait for listing (Sniping)
    try:
        await wait_for_listing(update, context, exchange, symbol)
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] Failed during sniping wait: {e}")
        await exchange.close()
        return

    # 2. Execute trade
    # We pass the exchange object to avoid re-initialization and potential connection issues
    await execute_trade(update, context, params) # execute_trade will re-initialize and close, so we don't need to pass 'exchange'

# TELEGRAM HANDLERS (No changes needed here, logic is sound)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("Sorry, you are not authorized.")
        return
    await update.message.reply_text(
        "👋 Welcome to LiveSniperBot!\n\n"
        "**الأوامر المتاحة:**\n\n"
        "/trade - 📈 تداول عادي (شراء وبيع)\n"
        "/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)\n"
        "/cancel - ❌ إلغاء العملية الحالية"
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def simple_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("❌ Operation cancelled.")

async def trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if str(update.effective_user.id) != ALLOWED_USER_ID: return ConversationHandler.END
    context.user_data['is_sniping'] = False
    await update.message.reply_text("1. 💰 أدخل مبلغ الشراء بالدولار الأمريكي (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

async def sniping_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if str(update.effective_user.id) != ALLOWED_USER_ID: return ConversationHandler.END
    context.user_data['is_sniping'] = True
    await update.message.reply_text("1. ⚡️ أدخل مبلغ القنص بالدولار الأمريكي (USDT):", reply_markup=ForceReply(selective=True))
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data['amount'] = float(update.message.text)
        await update.message.reply_text("2. 🪙 أدخل رمز العملة (مثال: BTC):", reply_markup=ForceReply(selective=True))
        return SYMBOL
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return AMOUNT

async def get_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Ensure symbol is in correct format (e.g., BTC/USDT)
    symbol_input = update.message.text.strip().upper()
    if not symbol_input.endswith('/USDT'):
        symbol_input = f"{symbol_input}/USDT"
        
    context.user_data['symbol'] = symbol_input
    await update.message.reply_text("3. 🎯 أدخل نسبة الربح المستهدفة (%):", reply_markup=ForceReply(selective=True))
    return PROFIT_PERCENT

async def get_profit_percent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data['profit_percent'] = float(update.message.text)
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
        # Use asyncio.create_task to run the trade logic concurrently
        asyncio.create_task(sniping_and_trade(update, context, context.user_data)) if context.user_data.get('is_sniping') else asyncio.create_task(execute_trade(update, context, context.user_data))
        return ConversationHandler.END

async def get_stop_loss_percent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data['stop_loss_percent'] = float(update.message.text)
        await update.message.reply_text("✅ All data collected. Executing Trade...")
        # Use asyncio.create_task to run the trade logic concurrently
        asyncio.create_task(sniping_and_trade(update, context, context.user_data)) if context.user_data.get('is_sniping') else asyncio.create_task(execute_trade(update, context, context.user_data))
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Invalid input. Please enter a number.")
        return STOP_LOSS_PERCENT

# MAIN FUNCTION
# FLASK WEB SERVER FOR HOSTING PLATFORM
app = Flask(__name__)

@app.route('/')
def home():
    return "I'm alive"

def run_flask_app():
    app.run(host='0.0.0.0', port=8080)

# MAIN FUNCTION
def main() -> None:
    # --- FIX 3: Check all required environment variables ---
    if not all([TELEGRAM_BOT_TOKEN, BINGX_API_KEY, BINGX_API_SECRET, ALLOWED_USER_ID]):
        print("FATAL ERROR: One or more environment variables are not set.")
        sys.exit(1)
        
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Conversation Handler Setup
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", trade_start), CommandHandler("sniping", sniping_start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_symbol)],
            PROFIT_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_profit_percent)],
            USE_STOP_LOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_use_stop_loss)],
            STOP_LOSS_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stop_loss_percent)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cancel", simple_cancel_command))
    application.add_handler(conv_handler)
    
    print("Bot is running... Send /start to the bot on Telegram.")
    application.run_polling(poll_interval=1.0) # Added poll_interval for better control

if __name__ == "__main__":
    # Start the Flask web server in a separate thread
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    
    # Start the Telegram bot main function
    main()

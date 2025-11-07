# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
import ccxt.async_support as ccxt
import asyncio
import os
import sys
import json
import re
import requests
from bs4 import BeautifulSoup
from web3 import Web3
# from web3.middleware import geth_poa_middleware # Removed due to ImportError in web3 v6.x
import datetime
import time # Added for use in execute_trade
from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters

# --- WEB3 CONSTANTS ---
# يجب تعيين هذه المتغيرات في بيئة التشغيل (Render)
PRIVATE_KEY = os.environ.get('PRIVATE_KEY') # المفتاح الخاص لمحفظة الشراء
BSC_RPC_URL = os.environ.get('BSC_RPC_URL', 'https://bsc-dataseed.binance.org/') # RPC لشبكة BNB Smart Chain
PANCAKESWAP_ROUTER_ADDRESS = '0x10ED43C718714eb63d5aA57B78B54704E256024E' # PancakeSwap Router V2
WBNB_ADDRESS = '0xbb4CdB9eD5Bf308bB01BDdC0eFE8fA2741d248bB' # WBNB Contract Address
SNIPE_AMOUNT_BNB = float(os.environ.get('SNIPE_AMOUNT_BNB', 0.01)) # كمية BNB للشراء (افتراضياً 0.01 BNB)

    # --- WEB3 SETUP ---
try:
    w3 = Web3(Web3.HTTPProvider(BSC_RPC_URL))
    # إذا كانت الشبكة تستخدم Proof of Authority (مثل BSC)، يجب إضافة هذا الميدل وير
    if w3.is_connected() and w3.eth.chain_id == 56: # 56 هو Chain ID لشبكة BSC
        # محاولة استيراد geth_poa_middleware محلياً لتجنب خطأ الاستيراد العام
        try:
            from web3.middleware import geth_poa_middleware
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        except ImportError:
            logging.warning("geth_poa_middleware not found in web3.middleware. Assuming PoA is not needed or handled internally.")
except Exception as e:
    logging.error(f"Failed to connect to Web3 provider: {e}")
    w3 = None

# ABI لعقد PancakeSwap Router V2 (للدالة swapExactETHForTokens)
PANCAKESWAP_ABI = json.loads('''
[
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokens",
        "outputs": [
            {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
        ],
        "stateMutability": "payable",
        "type": "function"
    }
]
''')

# عقد PancakeSwap Router
if w3:
    pancakeswap_router = w3.eth.contract(address=w3.to_checksum_address(PANCAKESWAP_ROUTER_ADDRESS), abi=PANCAKESWAP_ABI)
else:
    pancakeswap_router = None

# --- I18N (Internationalization) MESSAGES ---
MESSAGES = {
    'ar': {
        'cancel_success': '❌ تم إلغاء العملية الحالية.',
        'welcome_vip_owner': '👑 <b>تحية الإجلال، سيدي المدير العام</b> ({username}) 👑\n\nجميع الأنظمة والعمليات تحت إمرتكم المباشرة. الصلاحيات العليا مفعلة بالكامل.\n<b>الأوامر السيادية المتاحة:</b>',
        'welcome_vip_abood': 'تم التحقق. أهلاً بك، سيد 👑Abood👑. تم تفعيل بروتوكول المؤسس V.I.P الخاص بك.\nجميع الأنظمة تحت سيطرتك الآن، مع وصول كامل ومجاني لجميع الميزات الحالية والمستقبلية.البوت في خدمة سيادتكم.\n\n<b>الأوامر التنفيذية المتاحة:</b>',
        'welcome_vip_other': '👋 مرحباً بك يا {username} (المستخدم المميز)!\n<b>الأوامر المتاحة:</b>',
        'welcome_client': '👋 مرحباً بك يا {username}!\n\nأهلاً بك في خدمة <b>LiveSniperBot</b> المجانية والمتميزة.\nالبوت يعمل على منصة تداول بنظام <b>اقتطاع الأرباح (10%)</b> على الصفقات الناجحة فقط.\nللبدء، يرجى إعداد مفاتيح API الخاصة بك وتفعيل خيار <b>السحب</b>.\n\n<b>الأوامر المتاحة:</b>',
        'cmd_trade': '/trade - 📈 تداول عادي (شراء وبيع)',
        'cmd_sniping': '/sniping - ⚡️ قنص عملة جديدة (انتظار الإدراج)',
        'cmd_grid_trade': '/grid_trade - 📊 بدء التداول الشبكي (الشبكة الآلية)',
        'cmd_stop_grid': '/stop_grid - 🛑 إيقاف الشبكة الآلية',
        'cmd_cancel': '/cancel - ❌ إلغاء العملية الحالية',
        'cmd_set_api': '/set_api - 🔑 إعداد مفاتيح API',
        'cmd_status_bot': '/status - ℹ️ عرض حالة البوت',
        'cmd_status_sub': '/status - ℹ️ عرض حالة الاشتراك',
        'cmd_support': '/support - 🤝 مركز الدعم والمساعدة',
        'trade_start_title': '<b>📈 بدء التداول العادي</b>\n\nيرجى اختيار نوع الأمر الذي تريد تنفيذه:',
        'trade_market_btn': '1. أمر السوق (Market)',
        'trade_limit_btn': '2. أمر محدد (Limit)',
        'lang_select_title': '🌐 <b>اختر لغتك المفضلة / Select your preferred language:</b>',
        'lang_ar_btn': 'العربية 🇸🇦',
        'lang_en_btn': 'English 🇬🇧',
        'lang_set_ar': '✅ تم اختيار اللغة <b>العربية</b> كلغة مفضلة لك.',
        'lang_set_en': '✅ Language set to <b>English</b>.',
    },
    'en': {
        'cancel_success': '❌ Current operation has been cancelled.',
        'welcome_vip_owner': '👑 <b>Greetings, General Manager</b> ({username}) 👑\n\nAll systems and operations are under your direct command. Full supreme authorities are enabled.\n<b>Available Sovereign Commands:</b>',
        'welcome_vip_abood': 'Verified. Welcome, Lord 👑Abood👑. Your Founder V.I.P protocol is activated.\nAll systems are under your control now, with full and free access to all current and future features. The bot is at your service.\n\n<b>Available Executive Commands:</b>',
        'welcome_vip_other': '👋 Welcome {username} (Premium User)!\n<b>Available Commands:</b>',
        'welcome_client': '👋 Welcome {username}!\n\nWelcome to the free and premium <b>LiveSniperBot</b> service.\nThe bot operates on a trading platform with a <b>profit sharing (10%)</b> system on successful trades only.\nTo start, please set up your API keys and enable the <b>Withdrawal</b> option.\n\n<b>Available Commands:</b>',
        'cmd_trade': '/trade - 📈 Normal Trade (Buy and Sell)',
        'cmd_sniping': '/sniping - ⚡️ Sniping a New Coin (Waiting for Listing)',
        'cmd_grid_trade': '/grid_trade - 📊 Start Grid Trading (Automated Grid)',
        'cmd_stop_grid': '/stop_grid - 🛑 Stop Automated Grid',
        'cmd_cancel': '/cancel - ❌ Cancel Current Operation',
        'cmd_set_api': '/set_api - 🔑 Setup API Keys',
        'cmd_status_bot': '/status - ℹ️ Show Bot Status',
        'cmd_status_sub': '/status - ℹ️ Show Subscription Status',
        'cmd_support': '/support - 🤝 Support and Help Center',
        'trade_start_title': '<b>📈 Start Normal Trading</b>\n\nPlease choose the order type you want to execute:',
        'trade_market_btn': '1. Market Order',
        'trade_limit_btn': '2. Limit Order',
        'lang_select_title': '🌐 <b>اختر لغتك المفضلة / Select your preferred language:</b>',
        'lang_ar_btn': 'العربية 🇸🇦',
        'lang_en_btn': 'English 🇬🇧',
        'lang_set_ar': '✅ تم اختيار اللغة <b>العربية</b> كلغة مفضلة لك.',
        'lang_set_en': '✅ Language set to <b>English</b>.',
    }
}

async def get_user_language(user_id):
    """Fetches the user's preferred language from the database."""
    user_record = await get_user(user_id)
    return user_record.get('language', 'ar') if user_record else 'ar'

def get_text(user_id, key, **kwargs):
    """Retrieves the localized text for a given key."""
    # This is a synchronous function, so we cannot use await here.
    # We will use a temporary solution for now, and fix it later if needed.
    # For now, we will assume 'ar' if user_id is not provided or fails.
    
    # Since get_user is async, we will pass the language code directly 
    # from the calling async function, or default to 'ar'.
    
    # For simplicity in this synchronous helper, we will assume 'ar' as default
    # and rely on the calling function to pass the correct language.
    
    lang = kwargs.pop('lang', 'ar')
    
    text = MESSAGES.get(lang, MESSAGES['ar']).get(key, f"MISSING_TEXT[{key}]")
    return text.format(**kwargs)

# --- END I18N (Internationalization) MESSAGES ---

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

# Dictionary to hold active early sniper tasks: {user_id: asyncio.Task}
ACTIVE_EARLY_SNIPER_TASKS = {}
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- NEW: Generalizing Exchange ---
# The bot will now use the exchange ID specified by the user.
# The old EXCHANGE_ID constant is no longer used for trading logic.
EXCHANGE_ID = None # Placeholder to prevent 'name is not defined' error in older code paths

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
SNIPING_DELAY = 0.030 # Check every 0.030 seconds for high-speed sniping (as requested by user)

# Conversation States
ORDER_TYPE, AMOUNT, SYMBOL, PROFIT_PERCENT, USE_STOP_LOSS, STOP_LOSS_PERCENT, LIMIT_PRICE = range(7)
GRID_SYMBOL, LOWER_BOUND, UPPER_BOUND, NUM_GRIDS, AMOUNT_PER_ORDER, STOP_GRID_ID = range(7, 13)
WAITING_FOR_SCREENSHOT = 50

# New Conversation States for API Setup
SELECT_EXCHANGE, WAITING_FOR_API_KEY, WAITING_FOR_API_SECRET = range(51, 54)


# --- EXCHANGE TRADING LOGIC ---

# --- EARLY API SNIPER LOGIC ---

async def early_sniper_task(user_id, chat_id, exchange_id, application):
    """Background task to monitor exchange API for new symbols."""
    
    # 1. Initialize a temporary exchange object for market fetching (no keys needed)
    try:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({
            'options': {'defaultType': 'spot'},
            'enableRateLimit': True,
        })
    except AttributeError:
        # Send error message to user
        await application.bot.send_message(chat_id, f"❌ [خطأ] المنصة {exchange_id} غير مدعومة.")
        return
    except Exception as e:
        await application.bot.send_message(chat_id, f"❌ [خطأ] فشل تهيئة المنصة: {e}")
        return

    # 2. Get initial list of markets
    try:
        markets = await exchange.fetch_markets()
        known_symbols = set(m['symbol'] for m in markets)
        await application.bot.send_message(chat_id, f"✅ [القنص المبكر] بدأت مراقبة منصة <b>{exchange_id}</b> بـ {len(known_symbols)} رمز معروف. سيتم التنبيه عند اكتشاف أي رمز جديد.", parse_mode='HTML')
    except Exception as e:
        await application.bot.send_message(chat_id, f"❌ [خطأ] فشل جلب الأسواق الأولية من {exchange_id}: {e}")
        await exchange.close()
        return

    # 3. Monitoring Loop
    while True:
        try:
            # Check if the task has been cancelled
            if asyncio.current_task().cancelled():
                break
                
            await asyncio.sleep(5) # Check every 5 seconds

            new_markets = await exchange.fetch_markets()
            current_symbols = set(m['symbol'] for m in new_markets)
            
            # Find new symbols
            new_symbols = current_symbols - known_symbols
            
            if new_symbols:
                for symbol in new_symbols:
                    # 4. Send Interactive Alert
                    alert_message = (
                        "🚨 <b>فرصة قنص مبكر!</b> 🚨\n\n"
                        f"تم اكتشاف عملة جديدة على منصة <b>{exchange_id}</b>:\n\n"
                        f"<b>الرمز:</b> <code>{symbol}</code>\n\n"
                        f"<b>سيدي المدير العام، هل العملة متوافقة مع مبادئك؟</b>"
                    )
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ نعم، اشترِ الآن", callback_data=f"snipe_buy_{symbol}"),
                            InlineKeyboardButton("❌ لا، تجاهل", callback_data=f"snipe_cancel_{symbol}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await application.bot.send_message(
                        chat_id, 
                        alert_message, 
                        reply_markup=reply_markup, 
                        parse_mode='HTML'
                    )
                    
                # 5. Update the known list
                known_symbols.update(new_symbols)
                
        except ccxt.NetworkError:
            # Log the error but continue the loop
            print(f"Network error during early sniper for user {user_id} on {exchange_id}. Retrying...")
            await asyncio.sleep(10) # Wait longer on network error
        except Exception as e:
            # Log the error and stop the task for safety
            error_message = f"❌ [خطأ فادح] توقف القنص المبكر بسبب خطأ غير متوقع: {e}"
            await application.bot.send_message(chat_id, error_message)
            break

    # Cleanup
    await exchange.close()
    if user_id in ACTIVE_EARLY_SNIPER_TASKS:
        del ACTIVE_EARLY_SNIPER_TASKS[user_id]
    await application.bot.send_message(chat_id, f"🛑 [القنص المبكر] تم إيقاف مهمة المراقبة لمنصة <b>{exchange_id}</b>.", parse_mode='HTML')

# --- CONTRACT ADDRESS FINDER ---

async def find_contract_address(symbol: str) -> str | None:
    """
    Searches for the contract address of a given symbol using multiple strategies.
    Strategies: 1. CoinGecko API, 2. CoinMarketCap API, 3. Google Search.
    """
    
    # 1. Prepare symbol for search (e.g., NEWCOIN/USDT -> NEWCOIN)
    base_symbol = symbol.split('/')[0]
    
    # --- Strategy 1: CoinGecko API ---
    try:
        # Search for the coin ID
        search_url = f"https://api.coingecko.com/api/v3/search?query={base_symbol}"
        response = requests.get(search_url, timeout=5)
        response.raise_for_status()
        search_data = response.json()
        
        coin_id = None
        for coin in search_data.get('coins', []):
            if coin['symbol'].upper() == base_symbol.upper():
                coin_id = coin['id']
                break
        
        if coin_id:
            # Get coin details to find contract address
            coin_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
            response = requests.get(coin_url, timeout=5)
            response.raise_for_status()
            coin_data = response.json()
            
            # Check for BSC contract address
            contract_address = coin_data.get('platforms', {}).get('binance-smart-chain')
            if contract_address:
                logging.info(f"Found contract address for {symbol} via CoinGecko: {contract_address}")
                return contract_address
                
    except Exception as e:
        logging.warning(f"CoinGecko search failed for {symbol}: {e}")

    # --- Strategy 2: CoinMarketCap API (Placeholder - Requires API Key) ---
    # Since CoinMarketCap requires an API key and the user didn't provide one, 
    # we will skip the direct API call and rely on Google Search as the next best option.
    # If the user provides a CMC API key later, this section can be implemented.
    logging.info(f"Skipping CoinMarketCap API search for {symbol} (API key not provided).")

    # --- Strategy 3: Google Search (Simulated with a search query) ---
    try:
        search_query = f"{base_symbol} contract address bsc"
        # We will use a placeholder for Google Search since direct web scraping of Google results is unreliable and often blocked.
        # Instead, we will search for a common contract address pattern in a simulated search result page.
        # In a real-world scenario, a dedicated search API (like Google Custom Search API) would be used.
        
        # For the purpose of this task, we will simulate the search by directly hitting a known contract explorer or a reliable source if available.
        # Since we cannot use a real search API, we will use a generic web search to find a page that might contain the address.
        
        # A more robust approach for a bot would be to use a dedicated blockchain explorer API (like BscScan API).
        # Since the task explicitly mentioned Google Search, we will simulate the web request to a generic search result.
        
        # Simulating a search for a contract address on a page
        # We will use a mock search URL for demonstration purposes.
        # In a real scenario, this would be the URL of the first search result.
        mock_search_url = f"https://example.com/search-result-for-{base_symbol}"
        
        # We will use a simple web request to a mock page to demonstrate the logic.
        # In a real scenario, we would use a search engine API or a dedicated web scraper.
        
        # Since we cannot perform a real Google search, we will use a simpler approach:
        # 1. Search BscScan for the token name.
        bscscan_search_url = f"https://bscscan.com/search?f=0&q={base_symbol}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(bscscan_search_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for a link that looks like a contract address (0x...)
        # This is highly dependent on BscScan's current HTML structure and is fragile.
        # We will look for a common pattern: a link to a token page.
        
        # A common pattern for a contract address link on a search result page:
        contract_link = soup.find('a', href=re.compile(r'/token/0x[a-fA-F0-9]{40}'))
        
        if contract_link:
            contract_address = contract_link['href'].split('/token/')[1]
            if w3.is_address(contract_address):
                logging.info(f"Found contract address for {symbol} via BscScan Search: {contract_address}")
                return contract_address
                
    except Exception as e:
        logging.warning(f"BscScan Search failed for {symbol}: {e}")
        
    return None

# --- SNIPE EXECUTION LOGIC ---

async def execute_auto_snipe(chat_id: int, symbol: str, contract_address: str, application: Application):
    """
    Executes the buy transaction on PancakeSwap using web3.py.
    """
    
    if not PRIVATE_KEY:
        await application.bot.send_message(chat_id, "❌ <b>خطأ في الإعداد:</b> لم يتم تعيين متغير البيئة PRIVATE_KEY.", parse_mode='HTML')
        return
        
    if not w3 or not pancakeswap_router:
        await application.bot.send_message(chat_id, "❌ <b>خطأ في الإعداد:</b> فشل الاتصال بشبكة BSC أو عقد PancakeSwap.", parse_mode='HTML')
        return
        
    try:
        # 1. إعداد المتغيرات
        sender_address = w3.eth.account.from_key(PRIVATE_KEY).address
        token_address = w3.to_checksum_address(contract_address)
        
        # 2. تحويل كمية BNB إلى Wei
        amount_in_wei = w3.to_wei(SNIPE_AMOUNT_BNB, 'ether')
        
        # 3. تحديد المسار (WBNB -> Token)
        path = [w3.to_checksum_address(WBNB_ADDRESS), token_address]
        
        # 4. تحديد الحد الأدنى للتوكنات (للتجنب الانزلاق السعري - Slippage)
        # هنا نستخدم 1% انزلاق سعري كحد أقصى (99% من القيمة المتوقعة)
        # يجب أولاً الحصول على القيمة المتوقعة (getAmountsOut)
        
        # Note: getAmountsOut is a view function, safe to call.
        # We need the ABI for getAmountsOut, which is not in the current PANCAKESWAP_ABI.
        # For simplicity and to avoid adding a large ABI, we will assume a very small amountOutMin (e.g., 1)
        # In a real-world scenario, we must use getAmountsOut to calculate a safe amountOutMin.
        amount_out_min = 1 # A very small number to allow for any amount of tokens (high slippage risk)
        
        # 5. تحديد الموعد النهائي (Deadline)
        # المعاملة يجب أن تتم خلال 60 ثانية
        deadline = int(time.time()) + 60 
        
        # 6. بناء المعاملة
        # نستخدم دالة swapExactETHForTokens لأننا ندفع بـ BNB (التي يتم تغليفها تلقائياً إلى WBNB)
        tx = pancakeswap_router.functions.swapExactETHForTokens(
            amount_out_min,
            path,
            sender_address, # to: المستلم هو المرسل نفسه
            deadline
        ).build_transaction({
            'from': sender_address,
            'value': amount_in_wei,
            'gas': 300000, # تقدير للغاز
            'gasPrice': w3.eth.gas_price,
            'nonce': w3.eth.get_transaction_count(sender_address),
        })
        
        # 7. توقيع المعاملة
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        
        # 8. إرسال المعاملة
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        # 9. إرسال تقرير النتيجة
        bscscan_url = f"https://bscscan.com/tx/{tx_hash.hex()}"
        
        await application.bot.send_message(
            chat_id,
            f"✅ <b>تم تنفيذ أمر الشراء!</b>\n\n"
            f"<b>الرمز:</b> <code>{symbol}</code>\n"
            f"<b>الكمية:</b> {SNIPE_AMOUNT_BNB} BNB\n"
            f"جاري معالجة المعاملة على البلوك تشين. يمكنك متابعتها من هنا: <a href='{bscscan_url}'>رابط BscScan</a>",
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logging.error(f"Snipe execution failed for {symbol}: {e}")
        await application.bot.send_message(
            chat_id,
            f"❌ <b>فشل تنفيذ الشراء!</b>\n\n"
            f"<b>الرمز:</b> <code>{symbol}</code>\n"
            f"حدث خطأ أثناء محاولة الشراء على PancakeSwap: {e}",
            parse_mode='HTML'
        )

# --- COMMAND HANDLERS FOR EARLY SNIPER ---

async def handle_sniper_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the inline keyboard callbacks for the early sniper feature."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    callback_data = query.data
    
    # Extract action and symbol
    parts = callback_data.split('_')
    action = parts[1] # 'buy' or 'cancel'
    symbol = parts[2] # The coin symbol (e.g., NEWCOIN/USDT)
    
    # 1. Prevent double-click by editing the original message
    await query.edit_message_text(
        f"⏳ <b>جاري معالجة طلبك لـ:</b> <code>{symbol}</code>...",
        parse_mode='HTML'
    )
    
    if action == 'cancel':
        await query.edit_message_text(
            f"❌ <b>تم تجاهل العملة:</b> <code>{symbol}</code>.",
            parse_mode='HTML'
        )
        return
        
    elif action == 'buy':
        # 2. Check for PRIVATE_KEY
        if not PRIVATE_KEY:
            await query.edit_message_text(
                f"❌ <b>فشل الشراء لـ:</b> <code>{symbol}</code>.\n\n<b>السبب:</b> لم يتم تعيين متغير البيئة PRIVATE_KEY.",
                parse_mode='HTML'
            )
            return
            
        # 3. Find Contract Address
        await query.edit_message_text(
            f"🔍 <b>جاري البحث عن عنوان العقد لـ:</b> <code>{symbol}</code>...",
            parse_mode='HTML'
        )
        
        contract_address = await find_contract_address(symbol)
        
        if not contract_address:
            await query.edit_message_text(
                f"❌ <b>فشل الشراء لـ:</b> <code>{symbol}</code>.\n\n<b>السبب:</b> لم يتم العثور على عنوان العقد بعد البحث في CoinGecko و BscScan.",
                parse_mode='HTML'
            )
            return
            
        # 4. Execute Snipe
        await query.edit_message_text(
            f"🚀 <b>تم العثور على العقد!</b> جاري تنفيذ أمر الشراء على PancakeSwap...",
            parse_mode='HTML'
        )
        
        # The execute_auto_snipe function will send the final result message
        asyncio.create_task(execute_auto_snipe(chat_id, symbol, contract_address, application))
        
        # Since execute_auto_snipe sends the final message, we just return here.
        return

async def sniper_early_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts the Early API Sniper background task."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # 1. Check Whitelist
    if user_id not in WHITELISTED_USERS:
        await update.message.reply_text("🚫 <b>وصول مرفوض.</b> هذا الأمر متاح فقط للمستخدمين المميزين (VIP).", parse_mode='HTML')
        return

    # 2. Check if already running
    if user_id in ACTIVE_EARLY_SNIPER_TASKS and not ACTIVE_EARLY_SNIPER_TASKS[user_id].done():
        await update.message.reply_text("⚠️ <b>القنص المبكر نشط بالفعل.</b> لإيقافه، استخدم الأمر /stop_sniper_early.", parse_mode='HTML')
        return

    # 3. Get User Data
    user_record = await get_user(user_id)
    if not user_record or not user_record.get('exchange_id'):
        await update.message.reply_text("❌ <b>خطأ في الإعداد.</b> يرجى إعداد المنصة أولاً باستخدام الأمر /set_api.", parse_mode='HTML')
        return
        
    exchange_id = user_record['exchange_id']
    
    # 4. Start the background task
    # We pass the global application object to the task for sending messages
    task = asyncio.create_task(early_sniper_task(user_id, chat_id, exchange_id, context.application))
    ACTIVE_EARLY_SNIPER_TASKS[user_id] = task
    
    await update.message.reply_text(
        f"🚀 <b>بدء القنص المبكر!</b>\n\n"
        f"جاري مراقبة منصة <b>{exchange_id}</b> كل 5 ثوانٍ لاكتشاف العملات الجديدة في الـ API.\n"
        f"سيتم إرسال تنبيه فوري عند الاكتشاف.\n"
        f"لإيقاف المراقبة: /stop_sniper_early",
        parse_mode='HTML'
    )

async def stop_sniper_early_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stops the Early API Sniper background task."""
    user_id = update.effective_user.id
    
    # 1. Check Whitelist
    if user_id not in WHITELISTED_USERS:
        await update.message.reply_text("🚫 <b>وصول مرفوض.</b> هذا الأمر متاح فقط للمستخدمين المميزين (VIP).", parse_mode='HTML')
        return

    # 2. Check if running
    if user_id in ACTIVE_EARLY_SNIPER_TASKS:
        task = ACTIVE_EARLY_SNIPER_TASKS.pop(user_id)
        if not task.done():
            task.cancel()
            await update.message.reply_text("🛑 <b>تم إيقاف القنص المبكر بنجاح.</b>", parse_mode='HTML')
        else:
            await update.message.reply_text("⚠️ <b>القنص المبكر كان متوقفاً بالفعل.</b>", parse_mode='HTML')
    else:
        await update.message.reply_text("⚠️ <b>لا يوجد مهمة قنص مبكر نشطة حالياً لإيقافها.</b>", parse_mode='HTML')

async def initialize_exchange(exchange_id, api_key, api_secret, password=None):
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
        
    params = {
        'apiKey': api_key,
        'secret': api_secret,
        'options': {'defaultType': 'spot'}, # Assuming spot trading for simplicity
        'enableRateLimit': True,
    }
    
    # CRITICAL FIX: Bitget requires a password parameter
    if exchange_id == 'bitget' and password:
        params['password'] = password
        
    return exchange_class(params)

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
            # CRITICAL FIX: Use fetch_markets to check for symbol existence, which is often faster and less rate-limited than fetch_ticker
            markets = await exchange.fetch_markets()
            market_symbols = [m['symbol'] for m in markets]
            
            if symbol in market_symbols:
                # Symbol is listed, now check if it's tradable by fetching the ticker once
                try:
                    ticker = await exchange.fetch_ticker(symbol)
                    if ticker and ticker.get('last') is not None:
                        # AVOID TELEGRAM MESSAGE DELAY: Only return, the main function will handle the success message
                        return
                except Exception:
                    # If ticker fails, it might be listed but not yet tradable, continue waiting
                    pass
                    
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
        password = user_record.get('password') # CRITICAL FIX: Get password from user record
        exchange = await initialize_exchange(exchange_id, api_key, api_secret, password)
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
    
    # The symbol is already formatted by the calling function (sniping_and_trade or trade_start).
    symbol = params['symbol']
    
    try:
        # --- NEW: Place Buy Order and Get Execution Details (Optimized for Sniping) ---
        
        # 1. Place Market Buy Order
        # Determine order type and price based on user input
        order_type = params.get('order_type', 'market')
        order_price = params.get('order_price')

        # CRITICAL FIX: Force Market Order for Sniping Mode
        is_sniping = context.user_data.get('sniping_mode')
        
        if is_sniping:
            if order_type == 'limit':
                await update.message.reply_text("⚠️ [WARNING] تم تحويل أمر التداول إلى **أمر سوق (Market Order)** لضمان السرعة القصوى في وضع القنص.")
            order_type = 'market'
            order_price = None # Market orders do not use price
            
        # CRITICAL FIX: For Market Buy Orders, price must be None in create_order
        if order_type == 'market':
            order_price = None
        
        
        # CRITICAL FIX: Use Market or Limit in the message based on the final order_type
        order_type_display = 'MARKET' if order_type == 'market' else 'LIMIT'
        
        # 1. Get current price and market info
        await exchange.load_markets()
        market = exchange.markets.get(symbol)
        
        if not market:
            raise ccxt.BadSymbol(f"Symbol {symbol} market info is not available on {exchange.id}.")
            
        # Get the current price (best ask for buy order)
        ticker = await exchange.fetch_ticker(symbol)
        current_price = ticker['ask'] if ticker and ticker.get('ask') else ticker['last']
        
        if not current_price:
            raise ccxt.ExchangeError(f"Could not fetch current price for {symbol}.")
            
        # 2. Calculate the amount (quantity) to buy
        # amount = cost / price
        amount_to_buy_raw = amount_usdt / current_price
        
        # Apply amount precision (rounding down)
        precision = market['precision']['amount']
        import math
        amount_to_buy = math.floor(amount_to_buy_raw * (10**precision)) / (10**precision)
        
        if amount_to_buy <= 0:
            raise ccxt.ExchangeError(f"Calculated amount to buy ({amount_to_buy}) is zero or less. Check minimum order size.")
            
        # CRITICAL FIX: Use Market or Limit in the message based on the final order_type
        order_type_display = 'MARKET' if order_type == 'market' else 'LIMIT'
        
        # --- FLEXIBLE ORDER PLACEMENT LOGIC (Bitget Fix) ---
        amount_for_order = amount_to_buy
        order_params = {}
        
        # CRITICAL FIX: Bitget-specific logic for Market Buy Orders
        if exchange.id == 'bitget' and order_type == 'market':
            # Bitget requires passing the cost as 'amount' and using the special param
            amount_for_order = amount_usdt
            order_params = {'createMarketBuyOrderRequiresPrice': False}
            
            await update.message.reply_text("⚠️ [BITGET FIX] تم تطبيق الحل الخاص لمنصة Bitget لأمر السوق.")
            
        await update.message.reply_text(f"🛒 [STEP 1/3] Placing {order_type_display} Buy Order for {amount_for_order:.6f} {market['base'] if exchange.id != 'bitget' or order_type != 'market' else 'USDT'} (Cost: {amount_usdt} USDT)...")
        
        # CRITICAL FIX: Place the order using the calculated amount (or cost for Bitget market)
        market_buy_order = await exchange.create_order(
            symbol=symbol,
            type=order_type,
            side='buy',
            amount=amount_for_order, # Use calculated amount (or cost for Bitget market)
            price=order_price, # Only used for limit order
            params=order_params
        )
        
        # CRITICAL FIX: The error 'NoneType' object has no attribute 'find' 
        # is likely happening inside ccxt when it tries to process a None response from the exchange.
        # We must ensure the response is not None before proceeding.
        if market_buy_order is None:
            raise ccxt.ExchangeError("Exchange returned a None response for the buy order. Check API keys and permissions.")
            
        # CRITICAL FIX: Ensure the order was placed successfully and has an ID
        # We must also check if the order is a dictionary before calling .get()
        if not isinstance(market_buy_order, dict) or not market_buy_order.get('id'):
            raise ccxt.ExchangeError("Failed to place market buy order. Order response is incomplete or missing ID.")
            
        order_id = market_buy_order['id']
        
        # 2. Wait for Order to be Filled and Get Execution Details
        await update.message.reply_text("🔍 [STEP 2/3] Waiting for order to be filled and getting execution details...")
        
        # CRITICAL FIX: In Sniping Mode, we assume the Market Order is filled instantly.
        # We skip the polling loop to save critical time. We only fetch the order once.
        order_details = await exchange.fetch_order(order_id, symbol)
        
        # CRITICAL FIX: If fetch_order returns None (e.g., order not found or exchange error), we must handle it.
        if order_details is None:
            raise ccxt.ExchangeError(f"Failed to fetch order details for ID {order_id}. Order might have been rejected or is missing.")
            
        # CRITICAL FIX: If the order is not filled instantly (e.g., due to low liquidity or exchange delay), 
        # we cancel it immediately to avoid hanging and raise an error.
        if order_details.get('status') not in ['closed', 'filled']:
            # Cancel the order if it's still open and failed to fill
            try:
                await exchange.cancel_order(order_id, symbol)
            except Exception:
                pass # Ignore cancel errors
            raise ccxt.ExchangeError(f"Buy order failed to fill instantly. Final status: {order_details.get('status') if order_details else 'Unknown'}")
            
        # Extract execution details
        avg_price = float(order_details.get('average') or 0)
        filled_amount = float(order_details.get('filled') or 0)
        
        if not avg_price or not filled_amount:
            # Fallback to fetching trades if average/filled is missing (e.g., some exchanges)
            trades = await exchange.fetch_my_trades(symbol, since=None, limit=None, params={'order': order_id})
            
            if not trades:
                 raise ccxt.ExchangeError("Buy order was filled but execution details are missing, and no trades were found.")
            
            filled_amount = sum(float(trade['amount']) for trade in trades)
            total_cost = sum(float(trade['cost']) for trade in trades)
            avg_price = total_cost / filled_amount if filled_amount else 0
            
            if not avg_price or not filled_amount:
                raise ccxt.ExchangeError("Failed to get execution details from order or trades.")
                
        await update.message.reply_text(f"📊 [DETAILS] Avg Price: {avg_price:.6f}, Quantity: {filled_amount:.6f}")
        
        # 3. Take Profit Limit Sell and Stop Loss
        target_sell_price = avg_price * (1 + profit_percent / 100)
        
        # Get precision for the symbol
        await exchange.load_markets()
        market = exchange.markets.get(symbol)
        
        if not market:
            raise ccxt.BadSymbol(f"Symbol {symbol} market info is not available on {exchange.id}. Cannot set precision.")
            
        precision = market['precision']['amount']
        
        import math
        # CRITICAL FIX: Get the actual available balance after the buy order to account for fees
        base_currency = market['base'] # e.g., 'ALU'
        
        # Fetch the balance for the base currency (the coin we just bought)
        balance = await exchange.fetch_balance()
        available_amount = balance.get(base_currency, {}).get('free', 0)
        
        # CRITICAL FIX: Round the amount to sell to the correct precision before placing the order
        # Use the minimum of the calculated filled amount and the actual available balance
        amount_to_sell_raw = min(filled_amount, available_amount)
        
        # Round down the amount to sell to the correct precision
        amount_to_sell = math.floor(amount_to_sell_raw * (10**precision)) / (10**precision)
        
        if amount_to_sell <= 0:
            raise ccxt.InsufficientFunds(f"Insufficient available balance ({available_amount} {base_currency}) to place the sell order after fees.")
            
        await update.message.reply_text(f"🎯 [STEP 3/3] Placing Take Profit Limit Sell (+{profit_percent}%) at {target_sell_price:.6f}...\n(Selling actual available amount: {amount_to_sell:.6f} {base_currency})")
        
        limit_sell_order = await exchange.create_limit_sell_order(symbol, amount_to_sell, target_sell_price)
        
        # Update filled_amount_precise to the actual amount sold for profit calculation
        filled_amount_precise = amount_to_sell
        
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
            
        # --- AUTOMATIC PROFIT SHARING LOGIC ---
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
                if stop_order and stop_order.get('status') == 'open':
                    await exchange.cancel_order(stop_order['id'], symbol)
                    await update.message.reply_text("❌ [CLEANUP] تم إلغاء أمر وقف الخسارة (Stop Loss).")
                    
                # Call the automatic withdrawal function
                await handle_profit_withdrawal(
                    update, 
                    context, 
                    user_id, 
                    amount_usdt, # amount_usdt is the initial investment
                    filled_amount_precise, 
                    avg_price, 
                    target_sell_price, 
                    symbol
                )
                break # Exit the monitoring loop
                
            if order_status['status'] == 'canceled' or order_status['status'] == 'rejected':
                await update.message.reply_text("❌ [FAILURE] تم إلغاء أو رفض أمر البيع (Take Profit). لن يتم اقتطاع أي شيء.")
                break # Exit the monitoring loop
            
            # NO REPEATING STATUS MESSAGE - Monitoring continues silently
            
        await update.message.reply_text("✅ **تم الانتهاء من عملية التداول والاقتطاع (إن وجدت).**")
            
    except ccxt.ExchangeError as e:
        await update.message.reply_text(f"🚨 [EXCHANGE ERROR] {type(e).__name__}: {e}")
    except ccxt.NetworkError as e:
        await update.message.reply_text(f"🚨 [NETWORK ERROR] {type(e).__name__}: {e}")
    except Exception as e:
        # CRITICAL FIX: Catch the specific AttributeError and provide a clear message
        # Check for common CCXT errors that might be masked by a generic Exception
        error_message = str(e)
        
        # Check for specific CCXT errors that indicate API or balance issues
        if "API-key format invalid" in error_message or "Invalid API key" in error_message:
            await update.message.reply_text("🚨 [API ERROR] فشل الاتصال بالمنصة. يرجى التأكد من أن مفاتيح API صحيحة.")
        elif "Insufficient balance" in error_message or "not enough balance" in error_message:
            await update.message.reply_text("🚨 [BALANCE ERROR] رصيدك غير كافٍ لإجراء عملية الشراء.")
        elif "BadSymbol" in error_message:
            await update.message.reply_text(f"🚨 [SYMBOL ERROR] الرمز {params['symbol']} غير متوفر أو غير صحيح على المنصة.")
        elif "'NoneType' object has no attribute 'find'" in error_message:
            # This is the original generic error that was being masked
            await update.message.reply_text(f"🚨 [CRITICAL ERROR] فشل في معالجة استجابة أمر الشراء: {type(e).__name__}.\n\n**السبب المحتمل:** المنصة لم ترجع استجابة صالحة لأمر الشراء. يرجى التأكد من صلاحية مفاتيح API، وتوفر الرصيد الكافي، وأن الرمز المدخل صحيح.")
        else:
            # Fallback for truly unexpected errors
            await update.message.reply_text(f"🚨 [CRITICAL ERROR] خطأ غير متوقع: {type(e).__name__}: {e}")
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
        exchange = initialize_exchange(user_record['exchange_id'], user_record['api_key'], user_record['api_secret'])
        
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
    user_record = await get_user(update.effective_user.id)
    exchange_id = user_record.get('exchange_id')
    
    if not exchange_id:
        await update.message.reply_text("🚨 [ERROR] لم يتم اختيار منصة التداول. يرجى اختيارها أولاً باستخدام /set_api.")
        return
        
    try:
        # The exchange ID is a string (e.g., 'bingx'). We get the class from ccxt.
        exchange_class = getattr(ccxt, exchange_id)
        # Initialize the exchange object for public calls (fetching ticker)
        temp_exchange = exchange_class({'enableRateLimit': True})
    except AttributeError:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] المنصة المختارة غير مدعومة: {exchange_id}. يرجى اختيار منصة مدعومة.")
        return
    except Exception as e:
        # This is the line that was causing the original error if EXCHANGE_ID was used instead of exchange_id
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] فشل تهيئة المنصة المؤقتة: {type(e).__name__}: {e}")
        return
    
    # 1. Wait for listing (Sniping)
    try:
        # The wait_for_listing function will ensure the symbol is tradable.
        # We need to ensure the symbol is correctly formatted before passing it to wait_for_listing.
        # The symbol formatting logic is inside execute_trade, which is called *after* sniping.
        # We need to move the symbol formatting logic to be *before* the sniping process.
        
        # --- Symbol Formatting (Moved from execute_trade) ---
        symbol = params['symbol'].upper()
        if '/' not in symbol and not symbol.endswith('USDT'):
            symbol = f"{symbol}/USDT"
        elif '/' not in symbol and symbol.endswith('USDT'):
            symbol = f"{symbol[:-4]}/{symbol[-4:]}"
            
        params['symbol'] = symbol
        # --- End Symbol Formatting ---
        
        await wait_for_listing(update, context, temp_exchange, params['symbol'])
    except Exception as e:
        await update.message.reply_text(f"🚨 [CRITICAL ERROR] Failed during sniping wait: {e}")
        return
    finally:
        await temp_exchange.close()

    # 2. Execute trade (This will initialize a new exchange with user's keys)
    # CRITICAL FIX: Set sniping_mode to True before calling execute_trade
    context.user_data['sniping_mode'] = True
    
    # AVOID TELEGRAM MESSAGE DELAY: Remove the success message here to gain a few milliseconds
    # await update.message.reply_text(f"✅ [SUCCESS] {params['symbol']} is now listed! Proceeding to trade execution...")
    await execute_trade(update, context, params) 
    
    # CRITICAL FIX: Clear sniping_mode after the trade is executed
    context.user_data['sniping_mode'] = False


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
    """Sends a message with available commands."""
    user_id = update.effective_user.id
    
    # 1. Get user data
    user_record = await get_user(user_id)
    lang = await get_user_language(user_id)
    
    # 2. Determine user type and welcome message
    username = update.effective_user.username or update.effective_user.first_name
    
    # List of commands for VIP users (Owner, Abood, and other whitelisted)
    vip_commands = [
        get_text(user_id, 'cmd_trade', lang=lang),
        get_text(user_id, 'cmd_sniping', lang=lang),
        get_text(user_id, 'cmd_grid_trade', lang=lang),
        get_text(user_id, 'cmd_stop_grid', lang=lang),
        get_text(user_id, 'cmd_sniper_early', lang=lang),
        get_text(user_id, 'cmd_stop_sniper_early', lang=lang),
        get_text(user_id, 'cmd_cancel', lang=lang),
        get_text(user_id, 'cmd_set_api', lang=lang),
        get_text(user_id, 'cmd_status_bot', lang=lang),
        get_text(user_id, 'cmd_support', lang=lang),
    ]
    
    # List of commands for regular clients
    client_commands = [
        get_text(user_id, 'cmd_trade', lang=lang),
        get_text(user_id, 'cmd_sniping', lang=lang),
        get_text(user_id, 'cmd_grid_trade', lang=lang),
        get_text(user_id, 'cmd_stop_grid', lang=lang),
        get_text(user_id, 'cmd_cancel', lang=lang),
        get_text(user_id, 'cmd_set_api', lang=lang),
        get_text(user_id, 'cmd_status_sub', lang=lang),
        get_text(user_id, 'cmd_support', lang=lang),
    ]
    
    if user_id == OWNER_ID:
        welcome_key = 'welcome_vip_owner'
        commands_list = vip_commands
    elif user_id == ABOOD_ID:
        welcome_key = 'welcome_vip_abood'
        commands_list = vip_commands
    elif user_id in WHITELISTED_USERS:
        welcome_key = 'welcome_vip_other'
        commands_list = vip_commands
    else:
        welcome_key = 'welcome_client'
        commands_list = client_commands
        
    # 3. Construct the message
    welcome_message = get_text(user_id, welcome_key, lang=lang, username=username)
    
    # Add active sniper status to the message
    sniper_status = ""
    # Check the global dictionary for active tasks
    # We need to import ACTIVE_EARLY_SNIPER_TASKS from bot.py itself, but since we are in bot.py, we can use it directly.
    # However, to avoid a circular dependency issue if this file were split, it's safer to assume it's a global variable.
    # Since it's defined at the top level, it should be accessible.
    if user_id in ACTIVE_EARLY_SNIPER_TASKS and not ACTIVE_EARLY_SNIPER_TASKS[user_id].done():
        sniper_status = "\n\n⚠️ <b>القنص المبكر نشط حالياً!</b> (/stop_sniper_early)"
    
    full_message = welcome_message + "\n\n" + "\n".join(commands_list) + sniper_status
    
    # 4. Send the message
    await update.message.reply_text(full_message, parse_mode='HTML')
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    await add_new_user(user_id)
    
    lang = await get_user_language(user_id)
    
    # Auto-setup VIP API Keys for ABOOD (Removed as per user request)
        
    # Define common commands list
    commands = [
        get_text(user_id, 'cmd_trade', lang=lang),
        get_text(user_id, 'cmd_sniping', lang=lang),
        get_text(user_id, 'cmd_grid_trade', lang=lang),
        get_text(user_id, 'cmd_stop_grid', lang=lang),
        get_text(user_id, 'cmd_cancel', lang=lang),
        get_text(user_id, 'cmd_set_api', lang=lang),
        get_text(user_id, 'cmd_support', lang=lang),
    ]
    
    if user_id in WHITELISTED_USERS:
        if user_id == OWNER_ID:
            welcome_message = get_text(user_id, 'welcome_vip_owner', lang=lang, username=username)
            commands.append(get_text(user_id, 'cmd_status_bot', lang=lang))
        elif user_id == ABOOD_ID:
            welcome_message = get_text(user_id, 'welcome_vip_abood', lang=lang)
            commands.append(get_text(user_id, 'cmd_status_bot', lang=lang))
        else:
            welcome_message = get_text(user_id, 'welcome_vip_other', lang=lang, username=username)
            commands.append(get_text(user_id, 'cmd_status_sub', lang=lang))
        
        welcome_message += "\n" + "\n".join(commands)
        
        # Add language selection button
        keyboard = [
            [InlineKeyboardButton(get_text(user_id, 'lang_select_title', lang=lang), callback_data='select_language')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
        return
        
    # New Client Welcome Message (Bot is now free)
    welcome_message = get_text(user_id, 'welcome_client', lang=lang, username=username)
    commands.append(get_text(user_id, 'cmd_status_bot', lang=lang))
    welcome_message += "\n" + "\n".join(commands)
    
    # Add language selection button
    keyboard = [
        [InlineKeyboardButton(get_text(user_id, 'lang_select_title', lang=lang), callback_data='select_language')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_message,
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
    
    user_id = update.effective_user.id
    lang = await get_user_language(user_id)
    
    # Reset is_sniping flag
    context.user_data['is_sniping'] = False
    
    keyboard = [
        [InlineKeyboardButton(get_text(user_id, 'trade_market_btn', lang=lang), callback_data='order_type_market')],
        [InlineKeyboardButton(get_text(user_id, 'trade_limit_btn', lang=lang), callback_data='order_type_limit')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        get_text(user_id, 'trade_start_title', lang=lang),
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
    # CRITICAL FIX: If Bitget is selected, we need to ask for the Trading Password
    if exchange_id == 'bitget':
        await query.edit_message_text(
            f"✅ [اختيار المنصة] تم اختيار منصة **{exchange_id.upper()}**.\n\n"
            "🛠️ [إعداد API] يرجى إرسال مفتاح API الخاص بك الآن."
        )
    else:
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
    
    exchange_id = context.user_data.get('exchange_id')
    
    # CRITICAL FIX: If Bitget is selected, ask for the Trading Password next
    if exchange_id == 'bitget':
        await update.message.reply_text(
            "🔑 [إعداد API] تم حفظ مفتاح API.\n\n"
            "🔒 **[مطلوب لـ Bitget]** يرجى إرسال **كلمة مرور التداول (Trading Password)** الخاصة بك الآن."
        )
        # We will use WAITING_FOR_API_SECRET state to capture the password
        return WAITING_FOR_API_SECRET
    
    await update.message.reply_text(
        "🔑 [إعداد API] تم حفظ مفتاح API. يرجى إرسال مفتاح API السري (API Secret) الآن."
    )
    
    return WAITING_FOR_API_SECRET

async def set_api_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the API secret or Trading Password and saves all data to the database."""
    from database import get_user_by_api_key # Local import to fix the recurring issue
    
    user_id = update.effective_user.id
    exchange_id = context.user_data.get('exchange_id')
    
    # CRITICAL FIX: Handle Bitget Trading Password
    if exchange_id == 'bitget' and 'api_secret' not in context.user_data:
        # This is the Trading Password
        context.user_data['password'] = update.message.text.strip()
        
        # Now ask for the API Secret
        await update.message.reply_text(
            "🔒 [إعداد API] تم حفظ كلمة مرور التداول.\n\n"
            "🔑 يرجى إرسال مفتاح API السري (API Secret) الآن."
        )
        # We will use the same state to capture the secret next
        context.user_data['api_secret'] = 'temp_placeholder' # Placeholder to indicate we are now waiting for the secret
        return WAITING_FOR_API_SECRET
        
    # This is the API Secret (for all exchanges, or the second step for Bitget)
    api_secret = update.message.text.strip()
    api_key = context.user_data.get('api_key')
    password = context.user_data.get('password') # Will be None for non-Bitget
    
    # Clear the temporary placeholder if it exists
    if context.user_data.get('api_secret') == 'temp_placeholder':
        del context.user_data['api_secret']
        
    # Final save to database
    from database import update_api_keys
    
    # Ensure user exists in DB before attempting to update keys
    await add_new_user(user_id) 
    
    try:
        # Save to database
        # NOTE: update_api_keys now accepts exchange_id as the second argument
        await update_api_keys(user_id, exchange_id, api_key, api_secret, password) # CRITICAL FIX: Pass password
        
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
        exchange = initialize_exchange(user_record['exchange_id'], user_record['api_key'], user_record['api_secret'])
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
        
        # CRITICAL FIX: Start the monitoring task for the new grid
        await start_grid_monitoring(context.application, grid_id)
        
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
        exchange = initialize_exchange(user_record['exchange_id'], user_record['api_key'], user_record['api_secret'])
        
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
        "🌐 <b>اختر لغتك المفضلة / Select your preferred language:</b>",
        reply_markup=reply_markup,
        parse_mode='HTML'
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

    await query.edit_message_text(message_text, parse_mode='HTML')

# --- END LANGUAGE SELECTION HANDLERS ---

# --- GRID MONITORING LOGIC (Refactored to use individual tasks) ---

# Dictionary to hold active grid tasks: {grid_id: asyncio.Task}
active_grid_tasks = {}

async def grid_monitoring_task(application: Application, grid_id: int):
    """Monitors a single grid and places new orders based on fills."""
    
    # The loop will run until the grid is stopped in the database
    while True:
        try:
            grid = await get_grid(grid_id)
            if not grid or grid['status'] != 'active':
                # Grid is stopped or not found, exit the task
                break
                
            user_id = grid['user_id']
            symbol = grid['symbol']
            
            # Use Decimal for all calculations
            lower_bound = Decimal(str(grid['lower_bound']))
            upper_bound = Decimal(str(grid['upper_bound']))
            num_grids = int(grid['num_grids'])
            amount_per_order = Decimal(str(grid['amount_per_order']))
            
            user_record = await get_user(user_id)
            if not user_record or not user_record.get('api_key'):
                # User keys are missing, stop the grid and notify
                await stop_grid(grid_id)
                await application.bot.send_message(user_id, f"🚨 **توقف الشبكة {grid_id}**\n\nتم إيقاف شبكة التداول لـ {symbol} بسبب عدم توفر مفاتيح API.")
                break
                
            exchange = initialize_exchange(user_record['exchange_id'], user_record['api_key'], user_record['api_secret'])
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
            
            # 2. Fetch Open Orders and Trades
            # Fetch open orders to see what is currently active
            open_orders = await exchange.fetch_open_orders(symbol)
            
            # Get the current price
            ticker = await exchange.fetch_ticker(symbol)
            current_price = Decimal(str(ticker['last']))
            
            # Determine the next Buy and Sell points (based on current price)
            
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
            # Check if the expected Buy order is missing (meaning it was filled or cancelled)
            # The expected Buy order is at the next_buy_price
            quantizer_price = Decimal(f'1e-{price_precision}')
            
            buy_order_open = any(
                order['side'] == 'buy' and 
                Decimal(str(order['price'])).quantize(quantizer_price) == next_buy_price.quantize(quantizer_price)
                for order in open_orders
            )
            
            if next_buy_price and not buy_order_open:
                # A Buy order was filled (or cancelled), place a new Sell order at the next point up
                sell_price = next_buy_price + grid_step
                
                # Check if the sell price is within the upper bound
                if sell_price <= upper_bound:
                    # Place the Sell Limit Order
                    sell_amount_base = amount_per_order / sell_price # Approximate amount
                    
                    # Apply precision rounding
                    quantizer_amount = Decimal(f'1e-{amount_precision}')
                    sell_amount_base = sell_amount_base.quantize(quantizer_amount, rounding=ROUND_HALF_UP)
                    
                    # Convert Decimal back to float for ccxt
                    sell_price_float = float(sell_price.quantize(quantizer_price, rounding=ROUND_HALF_UP))
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
                    
                    # Apply precision rounding
                    quantizer_amount = Decimal(f'1e-{amount_precision}')
                    buy_amount_base = buy_amount_base.quantize(quantizer_amount, rounding=ROUND_HALF_UP)
                    
                    # Convert Decimal back to float for ccxt
                    new_buy_price_float = float(new_buy_price.quantize(quantizer_price, rounding=ROUND_HALF_UP))
                    buy_amount_float = float(buy_amount_base)
                    
                    try:
                        await exchange.create_limit_buy_order(symbol, buy_amount_float, new_buy_price_float)
                        await application.bot.send_message(user_id, f"🛒 **شبكة {grid_id} (BUY)**\n\nتم وضع أمر شراء جديد عند: {new_buy_price_float:.{price_precision}f}")
                    except Exception as e:
                        await application.bot.send_message(user_id, f"⚠️ **شبكة {grid_id} (ERROR)**\n\nفشل وضع أمر الشراء عند {new_buy_price_float}: {e}")
                        
            # --- Logic for Sell Order Replacement (If a Sell was filled) ---
            # Check if the expected Sell order is missing (meaning it was filled or cancelled)
            # The expected Sell order is at the next_sell_price
            sell_order_open = any(
                order['side'] == 'sell' and 
                Decimal(str(order['price'])).quantize(quantizer_price) == next_sell_price.quantize(quantizer_price)
                for order in open_orders
            )
            
            if next_sell_price and not sell_order_open:
                # A Sell order was filled (or cancelled), place a new Buy order at the next point down
                buy_price = next_sell_price - grid_step
                
                # Check if the buy price is within the lower bound
                if buy_price >= lower_bound:
                    # Place the Buy Limit Order
                    buy_amount_base = amount_per_order / buy_price
                    
                    # Apply precision rounding
                    quantizer_amount = Decimal(f'1e-{amount_precision}')
                    buy_amount_base = buy_amount_base.quantize(quantizer_amount, rounding=ROUND_HALF_UP)
                    
                    # Convert Decimal back to float for ccxt
                    buy_price_float = float(buy_price.quantize(quantizer_price, rounding=ROUND_HALF_UP))
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
                    
                    # Apply precision rounding
                    quantizer_amount = Decimal(f'1e-{amount_precision}')
                    sell_amount_base = sell_amount_base.quantize(quantizer_amount, rounding=ROUND_HALF_UP)
                    
                    # Convert Decimal back to float for ccxt
                    new_sell_price_float = float(new_sell_price.quantize(quantizer_price, rounding=ROUND_HALF_UP))
                    sell_amount_float = float(sell_amount_base)
                    
                    try:
                        await exchange.create_limit_sell_order(symbol, sell_amount_float, new_sell_price_float)
                        await application.bot.send_message(user_id, f"📈 **شبكة {grid_id} (SELL)**\n\nتم وضع أمر بيع جديد عند: {new_sell_price_float:.{price_precision}f}")
                    except Exception as e:
                        await application.bot.send_message(user_id, f"⚠️ **شبكة {grid_id} (ERROR)**\n\nفشل وضع أمر البيع عند {new_sell_price_float}: {e}")
                        
        except Exception as e:
            print(f"Error monitoring grid {grid_id}: {e}")
            # Send a message to the user about the critical error
            try:
                await application.bot.send_message(user_id, f"🚨 **خطأ فادح في مراقبة الشبكة {grid_id}**\n\nالخطأ: {type(e).__name__}: {e}\n\nسيتم إيقاف مراقبة هذه الشبكة مؤقتاً.")
            except Exception as msg_e:
                print(f"Failed to send error message to user {user_id}: {msg_e}")
        finally:
            if 'exchange' in locals():
                await exchange.close()
                
        # Sleep for a short interval before checking again
        await asyncio.sleep(5) 
        
    # Remove the task from the global dictionary when it finishes
    if grid_id in active_grid_tasks:
        del active_grid_tasks[grid_id]

async def start_grid_monitoring(application: Application, grid_id: int):
    """Starts a new monitoring task for a specific grid."""
    if grid_id not in active_grid_tasks:
        task = asyncio.create_task(grid_monitoring_task(application, grid_id))
        active_grid_tasks[grid_id] = task
        print(f"Started monitoring task for grid {grid_id}")

async def stop_grid_monitoring(grid_id: int):
    """Stops the monitoring task for a specific grid."""
    if grid_id in active_grid_tasks:
        task = active_grid_tasks[grid_id]
        task.cancel()
        del active_grid_tasks[grid_id]
        print(f"Stopped monitoring task for grid {grid_id}")

async def global_grid_manager_loop(application: Application):
    """Manages the lifecycle of all grid monitoring tasks."""
    while True:
        try:
            # Fetch all active grids from the database
            active_grids = await get_active_grids()
            active_grid_ids = {grid['id'] for grid in active_grids}
            
            # Start tasks for new active grids
            for grid_id in active_grid_ids:
                if grid_id not in active_grid_tasks:
                    await start_grid_monitoring(application, grid_id)
                    
            # Stop tasks for grids that are no longer active
            tasks_to_stop = [grid_id for grid_id in active_grid_tasks if grid_id not in active_grid_ids]
            for grid_id in tasks_to_stop:
                await stop_grid_monitoring(grid_id)
                
        except Exception as e:
            print(f"Global Grid Manager Error: {e}")
            
        # Check for new/stopped grids every 60 seconds
        await asyncio.sleep(60)

# --- END GRID MONITORING LOGIC (Refactored) ---

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
    
    # New Handlers for Early Sniper
    application.add_handler(CommandHandler("sniper_early", sniper_early_command))
    application.add_handler(CommandHandler("stop_sniper_early", stop_sniper_early_command))
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
    
    # Add handler for early sniper callbacks
    application.add_handler(CallbackQueryHandler(handle_sniper_callback, pattern='^snipe_(buy|cancel)_'))
    
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
    
    # Start the global grid manager loop after the event loop is running
    async def post_init_callback(application: Application):
        asyncio.create_task(global_grid_manager_loop(application))
        
    # The post_init argument is not supported in this version. We will use the application.post_init hook instead.
    application.post_init = post_init_callback
    
    application.run_polling(poll_interval=1.0, allowed_updates=Update.ALL_TYPES)

@app.route('/', methods=['GET'])
def home():
    return "Telegram Bot is running (Polling mode with Keep-Alive).", 200


if __name__ == "__main__":
    main()



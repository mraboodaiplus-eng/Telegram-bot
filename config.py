import os
import sys

# قائمة المتغيرات البيئية المطلوبة
REQUIRED_ENV_VARS = [
    'MEXC_API_KEY',
    'MEXC_API_SECRET',
    'TELEGRAM_BOT_TOKEN',
    'TELEGRAM_CHAT_ID',
    'WHITELIST_SYMBOLS' # تمت إضافته لتمكين تحديد العملات من البيئة
]

# التحقق الصارم من وجود جميع المتغيرات البيئية
for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        print(f"FATAL ERROR: Missing required environment variable: {var}")
        print("Protocol 'Zero-Doubt' Violation: Program terminated.")
        sys.exit(1)

# استخراج المتغيرات
MEXC_API_KEY = os.getenv('MEXC_API_KEY')
MEXC_API_SECRET = os.getenv('MEXC_API_SECRET')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# معالجة قائمة العملات البيضاء
# يجب أن تكون قائمة مفصولة بفواصل، وسيتم تحويلها إلى قائمة Python
WHITELIST_SYMBOLS_STR = os.getenv('WHITELIST_SYMBOLS')
WHITELIST_SYMBOLS = [s.strip().upper() for s in WHITELIST_SYMBOLS_STR.split(',') if s.strip()]

# ثوابت الاستراتيجية (مبدأ ما بعد الكفاءة)
# عتبة الشراء: 5% ارتفاع في 20 ثانية
BUY_THRESHOLD = 0.05
TIME_WINDOW_SECONDS = 20

# عتبة البيع: 3% تراجع عن سعر الذروة
SELL_THRESHOLD = 0.03

# ثوابت الاتصال
MEXC_WS_URL = "wss://wbs.mexc.com/ws"
MEXC_REST_URL = "https://api.mexc.com"

# ثوابت إعادة الاتصال
RECONNECT_DELAY = 5 # ثواني

# إعدادات الكود النظيف (PEP 8)
# لا توجد متغيرات عالمية غير ضرورية، كل شيء يتم تحميله مرة واحدة
# والتحقق منه بشكل صارم.

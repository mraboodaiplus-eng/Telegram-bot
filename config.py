"""
Omega Predator - Configuration Module
تكوين المشروع وتحميل المتغيرات البيئية
"""

import os
from typing import List
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

# ===== MEXC API Configuration =====
MEXC_API_KEY = os.getenv('MEXC_API_KEY', '')
MEXC_SECRET_KEY = os.getenv('MEXC_API_SECRET', '')
MEXC_BASE_URL = 'https://api.mexc.com'
MEXC_WS_URL = 'wss://wbs.mexc.com/ws'

# ===== Telegram Configuration =====
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# ===== Trading Parameters =====
# عتبة الشراء: ارتفاع 5% خلال 20 ثانية
BUY_THRESHOLD = 0.05  # 5%

# عتبة البيع: تراجع 3% من الذروة
SELL_THRESHOLD = 0.03  # 3%

# النافذة الزمنية للمراقبة (بالثواني)
TIME_WINDOW = 20  # 20 seconds

# القائمة البيضاء للعملات (سيتم تحديثها من قبل المستخدم)
# تم إزالة WHITELIST_STR بناءً على أمر المدير العام
WHITELIST: List[str] = [] # القائمة البيضاء أصبحت ديناميكية

# مبلغ الصفقة (سيتم تحديده من قبل المستخدم عند البدء)
TRADE_AMOUNT_USD = 0.0

# ===== System Configuration =====
# مستوى التسجيل
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# إعادة الاتصال التلقائي
AUTO_RECONNECT = True
RECONNECT_DELAY = 5  # seconds

# ===== Validation =====
def validate_config() -> bool:
    """
    التحقق من صحة الإعدادات الأساسية
    Returns: True إذا كانت جميع الإعدادات صحيحة
    """
    if not MEXC_API_KEY or not MEXC_SECRET_KEY:
        print("❌ خطأ: مفاتيح MEXC API غير محددة. يرجى تعيين MEXC_API_KEY و MEXC_API_SECRET.")
        return False
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ خطأ: إعدادات Telegram غير محددة. يرجى تعيين TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID.")
        return False
    
    return True

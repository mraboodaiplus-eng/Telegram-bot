import os
import sys
from dotenv import load_dotenv

# تحميل المتغيرات من ملف .env إذا وجد (للتطوير المحلي)
load_dotenv()

def get_env_variable(var_name):
    value = os.getenv(var_name)
    if not value:
        print(f"❌ CRITICAL ERROR: Variable {var_name} is missing!")
        sys.exit(1)
    return value

# التحقق الصارم عند البدء
print("⚙️ Initializing Omega Configuration...")
MEXC_API_KEY = get_env_variable("MEXC_API_KEY")
MEXC_API_SECRET = get_env_variable("MEXC_API_SECRET")
TELEGRAM_BOT_TOKEN = get_env_variable("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = get_env_variable("TELEGRAM_CHAT_ID")

# قائمة العملات المستهدفة (يمكن تعديلها هنا أو جعلها متغير بيئي مستقبلاً)
TARGET_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"] 

print("✅ Configuration Loaded Successfully.")
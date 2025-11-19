import os
import sys
from dotenv import load_dotenv

load_dotenv()

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    MEXC_API_KEY = os.getenv("MEXC_API_KEY")
    MEXC_API_SECRET = os.getenv("MEXC_API_SECRET")
    
    # قائمة الاستبعاد (تجنب عملات الرافعة والعملات الخاملة)
    EXCLUDED_PATTERNS = ['3L', '3S', '4L', '4S', '5L', '5S', 'DOWN', 'UP', 'BEAR', 'BULL']

    @classmethod
    def validate(cls):
        missing_vars = []
        if not cls.TELEGRAM_BOT_TOKEN: missing_vars.append("TELEGRAM_BOT_TOKEN")
        if not cls.TELEGRAM_CHAT_ID: missing_vars.append("TELEGRAM_CHAT_ID")
        if not cls.MEXC_API_KEY: missing_vars.append("MEXC_API_KEY")
        if not cls.MEXC_API_SECRET: missing_vars.append("MEXC_API_SECRET")
        
        if missing_vars:
            print(f"❌ خطأ قاتل: المتغيرات {', '.join(missing_vars)} مفقودة.")
            sys.exit(1)

Config.validate()
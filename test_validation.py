"""
ملف اختبار للتحقق من صحة الكود
"""

import sys


def test_imports():
    """اختبار استيراد جميع الوحدات"""
    try:
        import config
        import trading_logic
        import mexc_handler
        import websocket_handler
        import telegram_handler
        import main
        print("✅ جميع الوحدات تم استيرادها بنجاح")
        return True
    except Exception as e:
        print(f"❌ فشل استيراد الوحدات: {e}")
        return False


def test_trading_logic():
    """اختبار منطق التداول"""
    try:
        from trading_logic import TradingEngine
        import config
        
        engine = TradingEngine()
        
        # اختبار إضافة أسعار
        symbol = 'BTCUSDT'
        engine.add_price(symbol, 50000.0, 1000.0)
        engine.add_price(symbol, 52500.0, 1020.0)
        
        # اختبار شرط الشراء (ارتفاع 5%)
        result = engine.check_buy_condition(symbol, 52500.0, 1020.0)
        assert result == True, "يجب أن يتحقق شرط الشراء عند ارتفاع 5%"
        
        # اختبار فتح صفقة
        engine.open_position(symbol, 52500.0, 0.1)
        assert engine.positions[symbol]['active'] == True
        
        # اختبار شرط البيع (تراجع 3%)
        result = engine.check_sell_condition(symbol, 50925.0)  # تراجع 3%
        assert result == True, "يجب أن يتحقق شرط البيع عند تراجع 3%"
        
        print("✅ اختبارات منطق التداول نجحت")
        return True
    except Exception as e:
        print(f"❌ فشلت اختبارات منطق التداول: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config():
    """اختبار الإعدادات"""
    try:
        import config
        
        assert config.BUY_THRESHOLD == 0.05
        assert config.SELL_THRESHOLD == 0.03
        assert config.TIME_WINDOW == 20
        assert isinstance(config.WHITELIST, list)
        
        print("✅ اختبارات الإعدادات نجحت")
        return True
    except Exception as e:
        print(f"❌ فشلت اختبارات الإعدادات: {e}")
        return False


def main():
    """تشغيل جميع الاختبارات"""
    print("=" * 50)
    print("🧪 بدء اختبارات التحقق من الكود")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_config,
        test_trading_logic,
    ]
    
    results = []
    for test in tests:
        print(f"\n🔍 تشغيل: {test.__name__}")
        results.append(test())
    
    print("\n" + "=" * 50)
    if all(results):
        print("✅ جميع الاختبارات نجحت!")
        print("=" * 50)
        return 0
    else:
        print("❌ بعض الاختبارات فشلت")
        print("=" * 50)
        return 1


if __name__ == "__main__":
    sys.exit(main())

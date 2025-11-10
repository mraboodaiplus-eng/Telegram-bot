import requests
import json
import time

# اسم الملف الذي يحتوي على التوكنات التي تم جمعها (كل توكن في سطر جديد)
INPUT_FILE = "raw_tokens.txt"
# اسم الملف الذي سيتم حفظ التوكنات الصالحة فيه
OUTPUT_FILE = "valid_tokens.txt"
# حجم الدفعة للتقرير
BATCH_SIZE = 100

def check_token_validity(token):
    """
    يتحقق من صلاحية توكن بوت تليجرام باستخدام طريقة getMe.
    """
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        # لا نحتاج إلى تأخير هنا، التأخير سيكون على مستوى الدفعات
        response = requests.get(url, timeout=5)
        # إذا كان الرد 200 OK والـ 'ok' في الـ JSON هي True، فالتوكن صالح
        if response.status_code == 200:
            data = response.json()
            if data.get('ok') is True:
                return True
        return False
    except requests.exceptions.RequestException:
        # التعامل مع أخطاء الاتصال أو انتهاء المهلة
        return False

def validate_tokens():
    """
    يقرأ التوكنات من ملف الإدخال ويتحقق من صلاحيتها ويحفظ الصالح منها.
    """
    valid_count = 0
    total_count = 0
    
    try:
        with open(INPUT_FILE, 'r') as f:
            tokens = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"خطأ: لم يتم العثور على ملف الإدخال {INPUT_FILE}. يرجى التأكد من وجوده.")
        return

    total_count = len(tokens)
    print(f"تم العثور على {total_count} توكن محتمل في الملف.")
    
    with open(OUTPUT_FILE, 'w') as out_f:
        for i, token in enumerate(tokens):
            
            if check_token_validity(token):
                out_f.write(token + '\n')
                valid_count += 1
                print(f"[{i+1}/{total_count}] التوكن صالح: {token[:10]}... - الصالح: {valid_count}")
            else:
                print(f"[{i+1}/{total_count}] التوكن غير صالح: {token[:10]}...")

            # تقرير الدفعة
            if (i + 1) % BATCH_SIZE == 0:
                print("-" * 50)
                print(f"✅ تقرير الدفعة رقم {(i + 1) // BATCH_SIZE}: تم فحص {i + 1} توكن. الصالح حتى الآن: {valid_count}")
                print("-" * 50)
                # تأخير بين الدفعات لتجنب الحظر من تليجرام
                time.sleep(5) 

    print("=" * 50)
    print(f"✅ اكتمل التحقق. إجمالي التوكنات التي تم فحصها: {total_count}")
    print(f"✅ إجمالي التوكنات الصالحة: {valid_count}. تم حفظها في {OUTPUT_FILE}")
    print("=" * 50)

if __name__ == "__main__":
    validate_tokens()

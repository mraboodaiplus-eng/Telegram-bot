import os
import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from google import genai
from PIL import Image
import io

# تحميل المتغيرات البيئية
load_dotenv()

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# الأوامر المطلوبة لتعديل الصورة
ENHANCEMENT_PROMPT = """Ultra high-resolution cinematic enhancement only.
Preserve the subject with absolute 100% fidelity to the original image. No changes to facial features, identity, expression, pose, proportions, gender, camera angle, clothing, or background.

Perform a pure hyper-realistic upscale to increase clarity and sharpness only. Enhance natural skin texture realistically, preserving all original details exactly as-is, with visible pores and fine definition, no beautification or alteration.

Apply a cinematic color grade without changing lighting direction or composition: subtle warm amber highlights, gentle teal in shadows, deep blacks with controlled contrast. Maintain the original lighting structure while enhancing depth and dynamic range.

Add uniform, authentic analog film grain. Enhance shallow depth of field only if it already exists in the source image.

High-contrast, moody cinematic film-still look. Strictly no stylization or modifications that alter realism or the subject in any way."""

async def process_image(image_bytes: bytes, api_key: str) -> bytes:
    """
    دالة لمعالجة الصورة باستخدام Nano Banana API (Gemini 2.5 Flash Image)
    """
    try:
        client = genai.Client(api_key=api_key)
        
        # تحويل bytes إلى PIL Image
        img = Image.open(io.BytesIO(image_bytes))
        
        # إرسال الطلب إلى النموذج
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[ENHANCEMENT_PROMPT, img],
        )
        
        # استخراج الصورة من الاستجابة
        for part in response.parts:
            if part.inline_data is not None:
                # تحويل الصورة الناتجة إلى bytes
                output_img = part.as_image()
                img_byte_arr = io.BytesIO()
                output_img.save(img_byte_arr, format='PNG')
                return img_byte_arr.getvalue()
        
        raise Exception("لم يتم العثور على صورة في استجابة API")
    except Exception as e:
        logger.error(f"Error in process_image: {e}")
        raise

async def handle_photo_common(message: types.Message, bot: Bot, api_key: str):
    """معالج مشترك للصور لكلا البوتين"""
    processing_msg = await message.answer("⏳ <b>جاري المعالجة...</b>\n🔄 يتم تحسين الصورة باستخدام Nano Banana")
    
    try:
        # الحصول على أعلى جودة للصورة
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        image_data = await bot.download_file(file.file_path)
        image_bytes = image_data.read()
        
        # معالجة الصورة
        enhanced_image = await process_image(image_bytes, api_key)
        
        # إرسال النتيجة
        await message.answer_document(
            BufferedInputFile(enhanced_image, filename="enhanced_image.png"),
            caption="✅ <b>تم التحسين بنجاح!</b>\n✨ تم استخدام نموذج Nano Banana"
        )
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        await message.answer(f"❌ <b>عذراً، حدث خطأ أثناء المعالجة</b>\n\n📝 التفاصيل: {str(e)}")
    finally:
        try:
            await processing_msg.delete()
        except:
            pass

async def handle_document_common(message: types.Message, bot: Bot, api_key: str):
    """معالج مشترك للملفات لكلا البوتين"""
    if message.document.mime_type and not message.document.mime_type.startswith('image/'):
        await message.answer("⚠️ يرجى إرسال ملف صورة فقط!")
        return
        
    processing_msg = await message.answer("⏳ <b>جاري المعالجة...</b>\n🔄 يتم تحسين الصورة باستخدام Nano Banana")
    
    try:
        file = await bot.get_file(message.document.file_id)
        image_data = await bot.download_file(file.file_path)
        image_bytes = image_data.read()
        
        enhanced_image = await process_image(image_bytes, api_key)
        
        await message.answer_document(
            BufferedInputFile(enhanced_image, filename=f"enhanced_{message.document.file_name}"),
            caption="✅ <b>تم التحسين بنجاح!</b>\n✨ تم استخدام نموذج Nano Banana"
        )
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        await message.answer(f"❌ <b>عذراً، حدث خطأ أثناء المعالجة</b>\n\n📝 التفاصيل: {str(e)}")
    finally:
        try:
            await processing_msg.delete()
        except:
            pass

# إعداد البوت الأول
bot1 = Bot(token=os.getenv('BOT_TOKEN_1'), parse_mode=ParseMode.HTML)
dp1 = Dispatcher()

@dp1.message(Command("start"))
async def cmd_start1(message: types.Message):
    await message.answer("مرحباً! أنا البوت الأول لتحسين الصور باستخدام Nano Banana. أرسل صورتك الآن!")

@dp1.message(F.photo)
async def photo_handler1(message: types.Message):
    await handle_photo_common(message, bot1, os.getenv('NANO_BANANA_API_KEY_1'))

@dp1.message(F.document)
async def doc_handler1(message: types.Message):
    await handle_document_common(message, bot1, os.getenv('NANO_BANANA_API_KEY_1'))

# إعداد البوت الثاني
bot2 = Bot(token=os.getenv('BOT_TOKEN_2'), parse_mode=ParseMode.HTML)
dp2 = Dispatcher()

@dp2.message(Command("start"))
async def cmd_start2(message: types.Message):
    await message.answer("مرحباً! أنا البوت الثاني لتحسين الصور باستخدام Nano Banana. أرسل صورتك الآن!")

@dp2.message(F.photo)
async def photo_handler2(message: types.Message):
    await handle_photo_common(message, bot2, os.getenv('NANO_BANANA_API_KEY_2'))

@dp2.message(F.document)
async def doc_handler2(message: types.Message):
    await handle_document_common(message, bot2, os.getenv('NANO_BANANA_API_KEY_2'))

async def main():
    logger.info("🚀 جاري تشغيل البوتين معاً...")
    
    # حذف الـ webhooks
    await bot1.delete_webhook(drop_pending_updates=True)
    await bot2.delete_webhook(drop_pending_updates=True)
    
    # تشغيل البوتين في وقت واحد
    await asyncio.gather(
        dp1.start_polling(bot1),
        dp2.start_polling(bot2)
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⛔️ تم إيقاف البوتات")

import os
import logging
import asyncio
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.enums import ParseMode

# إعداد السجلات
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Prompt التحسين السينمائي الخاص بك
ENHANCEMENT_PROMPT = """
Ultra high-resolution cinematic enhancement only.
Preserve the subject with absolute 100% fidelity to the original image. No changes to facial features, identity, expression, pose, proportions, gender, camera angle, clothing, or background.
Perform a pure hyper-realistic upscale to increase clarity and sharpness only. Enhance natural skin texture realistically, preserving all original details exactly as-is, with visible pores and fine definition, no beautification or alteration.
Apply a cinematic color grade without changing lighting direction or composition: subtle warm amber highlights, gentle teal in shadows, deep blacks with controlled contrast. Maintain the original lighting structure while enhancing depth and dynamic range.
Add uniform, authentic analog film grain. Enhance shallow depth of field only if it already exists in the source image.
High-contrast, moody cinematic film-still look. Strictly no stylization or modifications that alter realism or the subject in any way.
"""

# دالة Nano Banana
async def process_nano_banana(image_bytes: bytes, api_key: str) -> bytes:
    endpoint = "https://api.nano-banana.ai/v1/upscale" 
    headers = {"Authorization": f"Bearer {api_key}"}
    data = aiohttp.FormData()
    data.add_field('image', image_bytes, filename='input.jpg', content_type='image/jpeg')
    data.add_field('prompt', ENHANCEMENT_PROMPT)
    data.add_field('model', 'nano-banana-v1')
    
    async with aiohttp.ClientSession() as session:
        async with session.post(endpoint, headers=headers, data=data, timeout=300) as resp:
            if resp.status == 200:
                return await resp.read()
            else:
                error_msg = await resp.text()
                raise Exception(f"Nano Banana Error: {resp.status}")

def setup_handlers(dp: Dispatcher, api_key: str):
    @dp.message(Command("start"))
    async def cmd_start(message: types.Message):
        await message.answer("✅ **تم التفعيل بنجاح!**\nأرسل صورة لرفع جودتها سينمائياً (Nano Banana).")

    @dp.message(F.photo | F.document)
    async def handle_image(message: types.Message):
        if message.document and not message.document.mime_type.startswith('image/'): return
        msg = await message.answer("⏳ **جاري المعالجة السينمائية...**")
        try:
            file_id = message.photo[-1].file_id if message.photo else message.document.file_id
            file = await message.bot.get_file(file_id)
            image_data = await message.bot.download_file(file.file_path)
            result = await process_nano_banana(image_data.read(), api_key)
            await message.answer_document(BufferedInputFile(result, filename="4k_upscaled.png"), caption="✨ تم الرفع بجودة 4K")
        except Exception as e:
            await message.answer(f"❌ خطأ: {str(e)}")
        finally:
            await msg.delete()

# --- جزء السيرفر الوهمي لتجاوز فحص Koyeb ---
async def handle_health_check(request):
    return web.Response(text="Bot is running!")

async def run_dummy_server():
    app = web.Application()
    app.router.add_get('/', handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    # Koyeb يستخدم المنفذ 8000 بشكل افتراضي
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    logger.info("Dummy server started on port 8000 for Health Check.")

async def main():
    # تشغيل السيرفر الوهمي في الخلفية
    asyncio.create_task(run_dummy_server())

    tasks = []
    # البوت الأول
    if os.getenv("BOT_TOKEN_1") and os.getenv("NANO_BANANA_API_KEY_1"):
        bot1 = Bot(token=os.getenv("BOT_TOKEN_1"), parse_mode=ParseMode.MARKDOWN)
        dp1 = Dispatcher()
        setup_handlers(dp1, os.getenv("NANO_BANANA_API_KEY_1"))
        tasks.append(dp1.start_polling(bot1))

    # البوت الثاني
    if os.getenv("BOT_TOKEN_2") and os.getenv("NANO_BANANA_API_KEY_2"):
        bot2 = Bot(token=os.getenv("BOT_TOKEN_2"), parse_mode=ParseMode.MARKDOWN)
        dp2 = Dispatcher()
        setup_handlers(dp2, os.getenv("NANO_BANANA_API_KEY_2"))
        tasks.append(dp2.start_polling(bot2))

    if tasks:
        await asyncio.gather(*tasks)
    else:
        logger.error("No Environment Variables found!")

if __name__ == "__main__":
    asyncio.run(main())
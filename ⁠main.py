import os
import sys
import asyncio
import logging
import aiosqlite
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Включаем принудительный вывод логов в консоль Render
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Проверяем наличие токена
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ ОШИБКА: Переменная BOT_TOKEN не найдена в настройках Render Environment!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
DB_NAME = "docvault.db"

class DocForm(StatesGroup):
    title = State()
    expiry_date = State()

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                expiry_date DATE
            )
        """)
        await db.commit()
    logger.info("База данных успешно инициализирована.")

@dp.message(CommandStart())
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить документ", callback_data="add_doc")],
        [InlineKeyboardButton(text="📋 Мои документы", callback_data="list_docs")]
    ])
    await message.answer("👋 Привет! Я бот для учета сроков документов и страховок.", reply_markup=kb)

@dp.callback_query(F.data == "add_doc")
async def start_add(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название документа (например, 'ОСАГО Haval'):")
    await state.set_state(DocForm.title)
    await callback.answer()

@dp.message(DocForm.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите дату окончания (ДД.ММ.ГГГГ, например 25.12.2026):")
    await state.set_state(DocForm.expiry_date)

@dp.message(DocForm.expiry_date)
async def process_date(message: Message, state: FSMContext):
    try:
        exp_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("⚠️ Неверный формат. Введите дату как ДД.ММ.ГГГГ:")
        return

    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO documents (user_id, title, expiry_date) VALUES (?, ?, ?)",
            (message.from_user.id, data["title"], exp_date.isoformat())
        )
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Документ <b>{data['title']}</b> сохранен!", parse_mode="HTML")

@dp.callback_query(F.data == "list_docs")
async def list_docs(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT title, expiry_date FROM documents WHERE user_id = ? ORDER BY expiry_date ASC",
            (callback.from_user.id,)
        )
        rows = await cursor.fetchall()

    if not rows:
        await callback.message.answer("У вас пока нет сохраненных документов.")
    else:
        text = "📋 Ваши документы:\n\n" + "\n".join([f"• <b>{t}</b> — до {d}" for t, d in rows])
        await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {port}")

async def main():
    try:
        logger.info("Запуск бота...")
        await init_db()
        await start_server()
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception(f"Критическая ошибка при работе: {e}")

if __name__ == "__main__":
    asyncio.run(main())

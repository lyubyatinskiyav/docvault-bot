import os
import asyncio
import aiosqlite
from datetime import datetime, date
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Получаем токен из переменной окружения Render
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
DB_NAME = "docvault.db"

# Состояния диалога добавления документа
class DocForm(StatesGroup):
    title = State()
    expiry_date = State()

# Создание таблицы базы данных при старте
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                expiry_date DATE,
                notified_30 INTEGER DEFAULT 0
            )
        """)
        await db.commit()

# Обработка команды /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить документ", callback_data="add_doc")],
        [InlineKeyboardButton(text="📋 Мои документы", callback_data="list_docs")]
    ])
    await message.answer(
        "👋 Привет! Я бот для контроля сроков документов и страховок.\n\n"
        "Я сохраню даты окончания полисов ОСАГО, прав или поверок счетчиков и вовремя напомню о них.",
        reply_markup=kb
    )

# Старт сценария добавления документа
@dp.callback_query(F.data == "add_doc")
async def start_add(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название документа (например: 'ОСАГО Haval' или 'Водительские права'):")
    await state.set_state(DocForm.title)
    await callback.answer()

# Получение названия
@dp.message(DocForm.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите дату окончания в формате ДД.ММ.ГГГГ (например, 25.12.2026):")
    await state.set_state(DocForm.expiry_date)

# Получение и валидация даты
@dp.message(DocForm.expiry_date)
async def process_date(message: Message, state: FSMContext):
    try:
        exp_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("⚠️ Неверный формат даты. Введите в виде ДД.ММ.ГГГГ (например, 25.12.2026):")
        return

    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO documents (user_id, title, expiry_date) VALUES (?, ?, ?)",
            (message.from_user.id, data["title"], exp_date.isoformat())
        )
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Документ <b>{data['title']}</b> успешно сохранен!\nСрок действия: до {message.text.strip()}.", parse_mode="HTML")

# Просмотр списка документов
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
        text = "📋 <b>Ваши документы:</b>\n\n"
        for title, exp in rows:
            # Преобразуем ГГГГ-ММ-ДД обратно в читаемый вид ДД.ММ.ГГГГ
            try:
                d_obj = datetime.strptime(exp, "%Y-%m-%d")
                clean_date = d_obj.strftime("%d.%m.%Y")
            except Exception:
                clean_date = exp
            text += f"• <b>{title}</b> — до {clean_date}\n"
        await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

# Вспомогательный веб-сервер для поддержания статуса на Render
async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await init_db()
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


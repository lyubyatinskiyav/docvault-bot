import os
import sys
import html
import logging
from datetime import date, datetime

import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не найден. Добавьте его в Environment сервиса Render.")
    sys.exit(1)

WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "docvault-webhook")
DB_NAME = "docvault.db"
PORT = int(os.getenv("PORT", "10000"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class DocForm(StatesGroup):
    title = State()
    expiry_date = State()


def public_base_url() -> str:
    url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if url:
        return url
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
    if host:
        return f"https://{host}"
    return ""


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить документ", callback_data="add_doc")],
            [InlineKeyboardButton(text="Мои документы", callback_data="list_docs")],
        ]
    )


def format_expiry(iso: str) -> str:
    exp = date.fromisoformat(iso)
    days = (exp - date.today()).days
    pretty = exp.strftime("%d.%m.%Y")
    if days < 0:
        return f"{pretty} (истёк {abs(days)} дн. назад)"
    if days == 0:
        return f"{pretty} (сегодня)"
    return f"{pretty} (через {days} дн.)"


async def init_db() -> None:
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                expiry_date DATE
            )
            """
        )
        await db.commit()
    logger.info("База данных готова.")


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Привет! Я DocVault — бот для учёта сроков документов и страховок.",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменил. Можно начать снова.", reply_markup=main_keyboard())


@dp.callback_query(F.data == "add_doc")
async def start_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(
        "Введите название документа (например, ОСАГО Haval):"
    )
    await state.set_state(DocForm.title)
    await callback.answer()


@dp.message(DocForm.title)
async def process_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не должно быть пустым. Введите ещё раз:")
        return
    await state.update_data(title=title)
    await message.answer(
        "Введите дату окончания (ДД.ММ.ГГГГ, например 25.12.2026):"
    )
    await state.set_state(DocForm.expiry_date)


@dp.message(DocForm.expiry_date)
async def process_date(message: Message, state: FSMContext) -> None:
    try:
        exp_date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("Неверный формат. Введите дату как ДД.ММ.ГГГГ:")
        return

    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO documents (user_id, title, expiry_date) VALUES (?, ?, ?)",
            (message.from_user.id, data["title"], exp_date.isoformat()),
        )
        await db.commit()

    await state.clear()
    await message.answer(
        f"Документ <b>{html.escape(data['title'])}</b> сохранён.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@dp.callback_query(F.data == "list_docs")
async def list_docs(callback: CallbackQuery) -> None:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT title, expiry_date FROM documents WHERE user_id = ? ORDER BY expiry_date ASC",
            (callback.from_user.id,),
        )
        rows = await cursor.fetchall()

    if not rows:
        await callback.message.answer(
            "Пока нет сохранённых документов.",
            reply_markup=main_keyboard(),
        )
    else:
        lines = [
            f"• <b>{html.escape(title)}</b> — до {format_expiry(expiry)}"
            for title, expiry in rows
        ]
        await callback.message.answer(
            "Ваши документы:\n\n" + "\n".join(lines),
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
    await callback.answer()


async def handle_ping(_request: web.Request) -> web.Response:
    return web.Response(text="DocVault bot is running")


async def on_startup(bot: Bot) -> None:
    await init_db()
    base = public_base_url()
    if not base:
        logger.warning("Публичный URL Render не найден — webhook не установлен.")
        return
    webhook_url = f"{base}{WEBHOOK_PATH}"
    await bot.set_webhook(
        webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    logger.info("Webhook: %s", webhook_url)


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()
    await bot.session.close()


def main() -> None:
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app.router.add_get("/", handle_ping)
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    logger.info("Listening on 0.0.0.0:%s", PORT)
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

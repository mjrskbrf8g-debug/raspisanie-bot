import asyncio
import logging
import re
import sqlite3
from datetime import datetime, date
from typing import Optional

import pytz
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, DB_PATH
from schedule_data import LESSONS, SPECIAL_DAYS, parse_ru_date, YEAR

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

MSK = pytz.timezone("Europe/Moscow")

WEEKDAYS_RU = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]

MONTHS_RU = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4,
    "ма": 5, "июн": 6, "июл": 7, "август": 8,
    "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}


def parse_user_date(text: str) -> Optional[date]:
    """Пытается распознать дату в свободном тексте пользователя.
    Понимает форматы: '12.09', '12/09', '12-09', '12 сентября'.
    Возвращает объект date или None, если распознать не удалось."""
    text = text.strip().lower()

    # Формат "12.09" / "12/09" / "12-09"
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})(?:[.\-/]\d{2,4})?$", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        try:
            return date(YEAR, month, day)
        except ValueError:
            return None

    # Формат "12 сентября"
    m = re.match(r"^(\d{1,2})\s+([а-яё]+)", text)
    if m:
        day = int(m.group(1))
        word = m.group(2)
        for stem, month in MONTHS_RU.items():
            if word.startswith(stem):
                try:
                    return date(YEAR, month, day)
                except ValueError:
                    return None
        return None

    return None


def setup_database():
    """Создаёт (или пересоздаёт) таблицы расписания и заполняет их данными
    из schedule_data.py. Вызывается при каждом запуске бота, поэтому
    на сервере не нужно отдельно запускать init_db.py.

    Таблица chats (список чатов, куда добавлен бот) НЕ пересоздаётся -
    она должна сохраняться между перезапусками бота."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS schedule")
    cur.execute("DROP TABLE IF EXISTS special_days")

    cur.execute("""
        CREATE TABLE schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            subject TEXT NOT NULL,
            link TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE special_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_of_week INTEGER NOT NULL,
            note TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY
        )
    """)

    rows = []
    for time_str, subject, dates, link in LESSONS:
        for d in dates:
            rows.append((parse_ru_date(d), time_str, subject, link))

    cur.executemany(
        "INSERT INTO schedule (date, time, subject, link) VALUES (?,?,?,?)",
        rows,
    )
    cur.executemany(
        "INSERT INTO special_days (day_of_week, note) VALUES (?,?)",
        SPECIAL_DAYS,
    )

    conn.commit()
    conn.close()
    logging.info(f"База данных готова: {len(rows)} пар, {len(SPECIAL_DAYS)} особых дней.")


def add_chat(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO chats (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()


def remove_chat(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def get_all_chats() -> list[int]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM chats")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def build_schedule_message(d: date) -> Optional[str]:
    """Возвращает готовый текст сообщения на дату d,
    либо None, если по расписанию для этого дня ничего не найдено
    (в этом случае бот ничего не отправляет)."""
    day_of_week = d.weekday()  # 0 = Понедельник
    date_iso = d.isoformat()
    date_str = d.strftime("%d.%m.%Y")
    header = f"{WEEKDAYS_RU[day_of_week]}, {date_str}"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Ищем пары на эту конкретную дату
    cur.execute(
        """
        SELECT time, subject, link
        FROM schedule
        WHERE date = ?
        ORDER BY time
        """,
        (date_iso,),
    )
    lessons = cur.fetchall()

    if lessons:
        lines = [header]
        for i, (time_str, subject, link) in enumerate(lessons, start=1):
            link_part = f" - {link}" if link else ""
            lines.append(f"{i}) {time_str} - {subject}{link_part}")
        conn.close()
        return "\n".join(lines)

    # 2. Если пар нет - ищем особый день (самоподготовка/практика),
    #    он действует каждую неделю для этого дня недели
    cur.execute(
        """
        SELECT note
        FROM special_days
        WHERE day_of_week = ?
        LIMIT 1
        """,
        (day_of_week,),
    )
    special = cur.fetchone()
    conn.close()

    if special:
        return f"{header}\n{special[0]}"

    # 3. Нет вообще никакой информации - ничего не отправляем
    return None


async def send_daily_schedule():
    today = datetime.now(MSK).date()
    text = build_schedule_message(today)
    if text is None:
        logging.info("На сегодня нет данных в базе - рассылка не отправляется.")
        return
    for chat_id in get_all_chats():
        try:
            await bot.send_message(chat_id, text)
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение {chat_id}: {e}")


@dp.my_chat_member()
async def on_bot_membership_changed(update: ChatMemberUpdated):
    """Срабатывает, когда бота добавляют в чат (личный или групповой)
    или удаляют из него. Регистрирует/удаляет чат автоматически -
    пользователям не нужно писать /start вручную."""
    new_status = update.new_chat_member.status
    chat_id = update.chat.id

    if new_status in ("member", "administrator", "creator"):
        add_chat(chat_id)
        logging.info(f"Бот добавлен в чат {chat_id}, подписка оформлена.")
        try:
            await bot.send_message(
                chat_id,
                "Привет! Я бот расписания занятий.\n"
                "Каждый день в 8:00 по МСК буду присылать сюда расписание на сегодня.\n"
                "Команда /today - показать расписание на сегодня прямо сейчас.\n"
                "Также можно написать дату, например 12.09 или 12 сентября.",
            )
        except Exception as e:
            logging.error(f"Не удалось отправить приветствие в чат {chat_id}: {e}")
    elif new_status in ("left", "kicked"):
        remove_chat(chat_id)
        logging.info(f"Бот удалён из чата {chat_id}, подписка отменена.")


@dp.message(Command("start"))
async def cmd_start(message: Message):
    add_chat(message.chat.id)
    await message.answer(
        "Привет! Я бот расписания занятий.\n\n"
        "Каждый день в 8:00 по МСК я буду присылать сюда расписание на сегодня.\n"
        "Команда /today - показать расписание на сегодня прямо сейчас.\n"
        "Также можешь просто написать дату, например 12.09 или 12 сентября -"
        " пришлю расписание на неё."
    )


@dp.message(Command("today"))
async def cmd_today(message: Message):
    today = datetime.now(MSK).date()
    text = build_schedule_message(today)
    if text is None:
        await message.answer(f"{today.strftime('%d.%m.%Y')}\nНа сегодня информации в базе не найдено.")
    else:
        await message.answer(text)


@dp.message(F.text)
async def handle_date_request(message: Message):
    """Обрабатывает свободный текст с датой (не команду).
    Команды выше по коду перехватываются раньше и сюда не попадают.
    Если текст не похож на дату - бот молчит (чтобы не мешать обычной
    переписке в чате, особенно групповом)."""
    requested_date = parse_user_date(message.text)
    if requested_date is None:
        return

    text = build_schedule_message(requested_date)
    if text is None:
        await message.answer(
            f"{requested_date.strftime('%d.%m.%Y')}\nНа эту дату информации в базе не найдено."
        )
    else:
        await message.answer(text)


async def main():
    setup_database()

    scheduler = AsyncIOScheduler(timezone=MSK)
    scheduler.add_job(send_daily_schedule, "cron", hour=8, minute=0)
    scheduler.start()

    logging.info("Бот запущен, жду сообщений...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

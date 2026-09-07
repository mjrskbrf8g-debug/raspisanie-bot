import asyncio
import logging
import sqlite3
from datetime import datetime, date
from typing import Optional

import pytz
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, USER_CHAT_IDS, DB_PATH
from schedule_data import LESSONS, SPECIAL_DAYS, parse_ru_date

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

MSK = pytz.timezone("Europe/Moscow")

WEEKDAYS_RU = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]


def setup_database():
    """Создаёт (или пересоздаёт) таблицы и заполняет их расписанием
    из schedule_data.py. Вызывается при каждом запуске бота, поэтому
    на сервере не нужно отдельно запускать init_db.py."""
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
    for chat_id in USER_CHAT_IDS:
        try:
            await bot.send_message(chat_id, text)
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение {chat_id}: {e}")


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я бот расписания занятий.\n\n"
        "Каждый день в 8:00 по МСК я буду присылать расписание на сегодня.\n"
        "Команда /today - показать расписание на сегодня прямо сейчас.\n\n"
        f"Твой chat_id: {message.chat.id}\n"
        "Добавь этот chat_id в файл config.py в список USER_CHAT_IDS, "
        "чтобы получать ежедневную рассылку, и перезапусти бота."
    )


@dp.message(Command("today"))
async def cmd_today(message: Message):
    today = datetime.now(MSK).date()
    text = build_schedule_message(today)
    if text is None:
        await message.answer(f"{today.strftime('%d.%m.%Y')}\nНа сегодня информации в базе не найдено.")
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

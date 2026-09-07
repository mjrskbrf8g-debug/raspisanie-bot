"""
Запусти этот файл, чтобы создать базу данных и заполнить её расписанием
(для запуска бота локально, например на твоём Mac).

Если нужно поменять расписание позже:
 - поправь LESSONS / SPECIAL_DAYS в файле schedule_data.py
 - удали файл schedule.db  (команда: rm schedule.db)
 - запусти этот файл заново: python3.12 init_db.py

Если бот запущен на сервере (bothost и т.п.) - база пересоздаётся
автоматически при каждом старте бота, этот файл там не нужен.
"""

import sqlite3
from config import DB_PATH
from schedule_data import LESSONS, SPECIAL_DAYS, parse_ru_date

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,     -- 'ГГГГ-ММ-ДД'
    time TEXT NOT NULL,     -- например "09:00-10:30"
    subject TEXT NOT NULL,
    link TEXT               -- ссылка на пару (может быть NULL)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS special_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week INTEGER NOT NULL,   -- 0=Пн ... 6=Вс
    note TEXT NOT NULL              -- например "День самоподготовки"
)
""")

conn.commit()

rows_to_insert = []
for time_str, subject, dates, link in LESSONS:
    for d in dates:
        iso_date = parse_ru_date(d)
        rows_to_insert.append((iso_date, time_str, subject, link))

cur.executemany(
    "INSERT INTO schedule (date, time, subject, link) VALUES (?,?,?,?)",
    rows_to_insert,
)

cur.executemany(
    "INSERT INTO special_days (day_of_week, note) VALUES (?,?)",
    SPECIAL_DAYS,
)

conn.commit()
conn.close()

print(f"База данных создана. Добавлено {len(rows_to_insert)} пар и {len(SPECIAL_DAYS)} особых дней.")
print("Файл базы: " + DB_PATH)

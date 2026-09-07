"""
Запусти этот файл, чтобы:
 1) добавить одну пару на конкретную дату (или сразу на несколько дат),
 2) добавить особый день (самоподготовка/практика) для дня недели,
 3) вписать/поменять ссылку у уже существующих пар с таким же названием.
"""

import sqlite3
from config import DB_PATH

DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def ask(prompt, choices=None):
    while True:
        val = input(prompt).strip()
        if choices and val not in choices:
            print(f"Нужно ввести одно из: {choices}")
            continue
        return val


def main():
    print("Что делаем?")
    print("1 - Добавить пару на дату(ы)")
    print("2 - Добавить особый день (самоподготовка/практика)")
    print("3 - Вписать/поменять ссылку у пар с определённым названием")
    mode = ask("Выбор (1/2/3): ", ["1", "2", "3"])

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if mode == "1":
        dates_raw = ask(
            "Дата(ы) в формате ГГГГ-ММ-ДД, через запятую если несколько "
            "(например 2026-09-14, 2026-09-28): "
        )
        dates = [d.strip() for d in dates_raw.split(",") if d.strip()]
        time_str = ask("Время (например 09:00-10:30): ")
        subject = ask("Название предмета: ")
        link = ask("Ссылка на пару (Enter, если нет ссылки): ")

        rows = [(d, time_str, subject, link or None) for d in dates]
        cur.executemany(
            "INSERT INTO schedule (date, time, subject, link) VALUES (?,?,?,?)",
            rows,
        )
        print(f"Добавлено пар: {len(rows)}")

    elif mode == "2":
        for i, d in enumerate(DAYS):
            print(f"{i} - {d}")
        day = int(ask("Номер дня недели: ", [str(i) for i in range(7)]))
        note = ask("Текст (например 'День самоподготовки'): ")
        cur.execute(
            "INSERT INTO special_days (day_of_week, note) VALUES (?,?)",
            (day, note),
        )
        print("Особый день добавлен!")

    else:
        subject = ask("Название предмета (точно как в базе): ")
        link = ask("Новая ссылка: ")
        cur.execute(
            "UPDATE schedule SET link = ? WHERE subject = ?",
            (link, subject),
        )
        print(f"Обновлено строк: {cur.rowcount}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()

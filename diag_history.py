"""Диагностика: вся ли история чатов попала в базу бота.
Запуск из папки бота: python3 diag_history.py
Сравнивает число сообщений в чате по данным Битрикс24 с числом в базе. Тексты не печатаются.
"""
import sqlite3
from collections import Counter

from bot import config
from bot.bitrix import Bitrix

bx = Bitrix(config.BITRIX_WEBHOOK)
db = sqlite3.connect(config.DB_PATH)
db.row_factory = sqlite3.Row
in_db = {r[0]: r[1] for r in db.execute("select chat_id, count(*) from messages group by chat_id")}
first_side = {}
for r in db.execute("select chat_id, side from messages where side in ('C','O') order by chat_id, ts desc, msg_id desc"):
    first_side[r[0]] = r[1]  # последнее присвоение = самое раннее сообщение
chats = sorted(in_db)
res, errs = bx.batch({f"c{c}": ("imopenlines.dialog.get", {"CHAT_ID": c}) for c in chats})
full, short, missing, owners = 0, 0, 0, Counter()
examples = []
for c in chats:
    d = res.get(f"c{c}") or {}
    total = int(d.get("message_count") or 0)
    if total <= in_db[c]:
        full += 1
    else:
        short += 1
        missing += total - in_db[c]
        if len(examples) < 10:
            examples.append(f"{c}: в Битрикс24 {total}, в базе {in_db[c]}")
print(f"Чатов в базе: {len(chats)}; история полная: {full}; неполная: {short}; не хватает сообщений: {missing}")
print("Примеры неполных чатов:", "; ".join(examples) or "-")
print("Первое сообщение в базе (клиент C / менеджер O):", dict(Counter(first_side.get(c, "нет") for c in chats)))
print("Ошибок dialog.get:", len(errs))
print("\nГотово. Пришлите этот вывод целиком: текстов переписки в нём нет.")

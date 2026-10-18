"""Почему новая версия загрузила мало сообщений. Запуск: python3 diag_load.py 18859 10885
Тексты не печатаются: только ID, даты, отправители, длины и как бот понял сообщение.
"""
import sys
import sqlite3
from collections import Counter

from bot import config
from bot.bitrix import Bitrix
from bot.store import Store
from bot.parse import Parser
from bot.collector import to_local

bx = Bitrix(config.BITRIX_WEBHOOK)
store = Store(config.DB_PATH)
parser = Parser(store.users(), config.EXCLUDED_USER_IDS, config.EXCLUDED_NAMES)


def summary(title, msgs):
    msgs = sorted(msgs, key=lambda m: int(m["id"]))
    print(f"   {title}: {len(msgs)} сообщ.", end="")
    if msgs:
        print(f", id {msgs[0]['id']}..{msgs[-1]['id']}, даты {str(msgs[0].get('date'))[:19]} .. {str(msgs[-1].get('date'))[:19]}")
        kinds = Counter(parser.classify(m.get("author_id"), m.get("text") or "")[0] for m in msgs)
        print(f"      авторы: {dict(Counter(str(m.get('author_id')) for m in msgs).most_common(5))}; как понял бот: {dict(kinds)}")
    else:
        print()


for chat in sys.argv[1:] or ["18859", "10885"]:
    print(f"\n== Чат {chat}")
    d = bx.result("im.dialog.messages.get", {"DIALOG_ID": f"chat{chat}", "LIMIT": 50}) or {}
    summary("напрямую, первая страница", d.get("messages") or [])
    us = d.get("users") or []
    print(f"      users: {type(us).__name__}, ключи: {sorted(us[0].keys()) if isinstance(us, list) and us else '-'}")
    res, errs = bx.batch({"x": ("im.dialog.messages.get", {"DIALOG_ID": f"chat{chat}", "LIMIT": 50})})
    summary("через batch, первая страница", (res.get("x") or {}).get("messages") or [])
    if errs:
        print("      ошибка batch:", errs)
    rows = [dict(r) for r in store.db.execute("select msg_id, ts, side, kind from messages where chat_id=? order by msg_id", (chat,))]
    print(f"   в базе: {len(rows)} сообщ., id {rows[0]['msg_id'] if rows else '-'}..{rows[-1]['msg_id'] if rows else '-'}, "
          f"даты {rows[0]['ts'] if rows else '-'} .. {rows[-1]['ts'] if rows else '-'}; стороны {dict(Counter(r['side'] for r in rows))}")
    print(f"   состояние чата: {dict(store.db.execute('select * from chats where chat_id=?', (chat,)).fetchone() or {})}")
print("\nГотово. Пришлите этот вывод целиком: текстов переписки в нём нет.")

"""Диагностика одного чата: совпадает ли чат в базе бота с чатом в Битрикс24.
Запуск из папки бота: python3 diag_chat.py 100829
Тексты сообщений не печатаются: только ID, даты, отправители и длины.
"""
import sys
import os
import sqlite3
from collections import Counter

from bot import config
from bot.bitrix import Bitrix, BitrixError

chat = sys.argv[1] if len(sys.argv) > 1 else "100829"
bx = Bitrix(config.BITRIX_WEBHOOK)
if not os.path.exists(config.DB_PATH) or os.path.getsize(config.DB_PATH) == 0:
    sys.exit(f"В этой папке нет базы бота {config.DB_PATH}. Скопируйте ее из папки, где запускали main.py, "
             f"например: cp ~/Downloads/\"hikmet_bot 4\"/{config.DB_PATH} .")
db = sqlite3.connect(config.DB_PATH)
db.row_factory = sqlite3.Row

print(f"== Чат {chat} в базе бота")
sess = [dict(r) for r in db.execute("select * from sessions where chat_id=?", (chat,))]
for s in sess:
    print(f"   сессия {s['session_id']}: создана {s['created']}, линия {s['line_id']}, закрыта {s['closed']}")
by_sess = Counter(r[0] for r in db.execute("select session_id from messages where chat_id=?", (chat,)))
print(f"   сообщений по сессиям: {dict(by_sess)}")
r = db.execute("select min(ts), max(ts), count(*) from messages where chat_id=?", (chat,)).fetchone()
print(f"   период: {r[0]} .. {r[1]}, всего {r[2]}")


def show_dialog(title, params):
    print(f"\n== {title}")
    try:
        d = bx.result("imopenlines.dialog.get", params) or {}
    except BitrixError as e:
        print("   ОШИБКА:", e)
        return {}
    for k in ("id", "dialog_id", "entity_type", "entity_id", "entity_data_1", "entity_link", "message_count", "date_create", "name"):
        v = d.get(k)
        if k == "name" and v:
            v = f"<{len(str(v))} символов>"
        print(f"   {k}: {v}")
    return d


show_dialog(f"imopenlines.dialog.get(CHAT_ID={chat})", {"CHAT_ID": chat})
for s in sess:
    sid = s["session_id"]
    d = show_dialog(f"imopenlines.dialog.get(SESSION_ID={sid})", {"SESSION_ID": sid})
    try:
        h = bx.result("imopenlines.session.history.get", {"CHAT_ID": chat, "SESSION_ID": sid}) or {}
    except BitrixError as e:
        print("   история: ОШИБКА", e)
        continue
    msgs = h.get("message") or {}
    msgs = list(msgs.values()) if isinstance(msgs, dict) else list(msgs)
    chatids = Counter(str(m.get("chatid") or m.get("chat_id")) for m in msgs)
    print(f"   история сессии: {len(msgs)} сообщений, chatid в сообщениях: {dict(chatids)}"
          f"  {'OK' if set(chatids) <= {str(chat)} else '<-- НЕ СОВПАДАЕТ с ' + chat}")
    print(f"   chat id из dialog.get по сессии: {d.get('id')}  {'OK' if str(d.get('id')) == str(chat) else '<-- НЕ СОВПАДАЕТ'}")

print("\n== Сессии CRM, связанные с этими ID")
try:
    acts = bx.list_all("crm.activity.list", {"filter": {"PROVIDER_ID": "IMOPENLINES_SESSION",
                                                        "ASSOCIATED_ENTITY_ID": [s["session_id"] for s in sess] or ["0"]},
                                             "select": ["ID", "ASSOCIATED_ENTITY_ID", "OWNER_TYPE_ID", "OWNER_ID", "CREATED", "PROVIDER_PARAMS"]})
    for a in acts:
        pp = a.get("PROVIDER_PARAMS") or {}
        print(f"   дело {a['ID']}: сессия {a['ASSOCIATED_ENTITY_ID']}, владелец {a.get('OWNER_TYPE_ID')}:{a.get('OWNER_ID')}, "
              f"создано {a.get('CREATED')}, PROVIDER_PARAMS ключи: {sorted(pp) if isinstance(pp, dict) else pp}")
except BitrixError as e:
    print("   ОШИБКА:", e)
print("\nГотово. Пришлите этот вывод целиком: текстов переписки в нём нет.")

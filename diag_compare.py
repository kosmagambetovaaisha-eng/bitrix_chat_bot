"""Сравнение двух способов загрузки одного чата: история сессии и im.dialog.messages.get.
Запуск: python3 diag_compare.py            (3 чата с самыми свежими сессиями)
        python3 diag_compare.py 18859       (конкретный чат)
Тексты не печатаются: только ID, даты, отправители, длины и как бот понял сообщение.
"""
import sys

from bot import config
from bot.bitrix import Bitrix
from bot.store import Store
from bot.parse import Parser

bx = Bitrix(config.BITRIX_WEBHOOK)
store = Store(config.DB_PATH)
parser = Parser(store.users(), config.EXCLUDED_USER_IDS, config.EXCLUDED_NAMES)

if len(sys.argv) > 1:
    pairs = []
    for c in sys.argv[1:]:
        r = store.db.execute("select session_id from sessions where chat_id=? order by cast(session_id as int) desc limit 1", (c,)).fetchone()
        pairs.append((c, r[0] if r else None))
else:
    pairs = [(r[0], r[1]) for r in store.db.execute(
        "select chat_id, max(cast(session_id as int)) from sessions where chat_id is not null group by chat_id order by 2 desc limit 3")]


def line(src, m):
    a = m.get("author_id") if m.get("author_id") is not None else m.get("senderid")
    kind = parser.classify(a, m.get("text") or "")[0]
    return f"{src} id={m['id']} {str(m.get('date'))[:19]} author={a} len={len(m.get('text') or '')} {kind}"


for chat, sid in pairs:
    print(f"\n== Чат {chat}, сессия {sid}")
    h = bx.result("imopenlines.session.history.get", {"CHAT_ID": chat, "SESSION_ID": sid}) if sid else {}
    hm = (h or {}).get("message") or {}
    hm = list(hm.values()) if isinstance(hm, dict) else list(hm)
    im = (bx.result("im.dialog.messages.get", {"DIALOG_ID": f"chat{chat}", "LIMIT": 50}) or {}).get("messages") or []
    hid, iid = {int(m["id"]) for m in hm}, {int(m["id"]) for m in im}
    print(f"   история сессии: {len(hm)}, im: {len(im)}, общих id: {len(hid & iid)}, только в сессии: {len(hid - iid)}, только в im: {len(iid - hid)}")
    lo = min(hid) if hid else 0
    rows = [("СЕС", m) for m in hm] + [("IM ", m) for m in im if int(m["id"]) >= lo and int(m["id"]) not in hid]
    for src, m in sorted(rows, key=lambda x: int(x[1]["id"]))[-25:]:
        print("   " + line(src, m))
print("\nГотово. Пришлите этот вывод целиком: текстов переписки в нём нет.")

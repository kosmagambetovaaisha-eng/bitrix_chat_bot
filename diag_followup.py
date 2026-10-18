"""Диагностика follow-up: почему бот насчитал 0. Работает с локальной базой, в Битрикс не ходит.
Запуск из папки бота: python3 diag_followup.py
Тексты сообщений не печатаются.
"""
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from bot import config
from bot.analytics import analyze

db = sqlite3.connect(config.DB_PATH)
db.row_factory = sqlite3.Row
rows = [dict(r) for r in db.execute("select * from messages order by chat_id, ts, msg_id")]
print(f"Сообщений в базе: {len(rows)}, чатов: {len({r['chat_id'] for r in rows})}")
print(f"Период: {rows[0]['ts'] if rows else '-'} .. {max(r['ts'] for r in rows) if rows else '-'}")
print("Сторона сообщений:", dict(Counter(r["side"] for r in rows)), " вид:", dict(Counter(r["kind"] for r in rows)))

span = Counter()
by_chat = defaultdict(list)
for r in rows:
    r["ts"] = datetime.fromisoformat(r["ts"])
    by_chat[r["chat_id"]].append(r)
for c, ms in by_chat.items():
    d = (ms[-1]["ts"] - ms[0]["ts"]).days
    span["0 дн" if d == 0 else "1-2 дн" if d < 3 else "3-7 дн" if d < 8 else "8-30 дн" if d < 31 else "31+ дн"] += 1
print("Сколько дней покрывает история чата:", dict(span))

sess_per_chat = Counter(r[0] for r in db.execute("select chat_id from sessions where chat_id is not null"))
print("Сессий на чат в базе:", dict(Counter(min(v, 5) for v in sess_per_chat.values())), "(5 = 5 и больше)")

# Грубый поиск follow-up без правил бота: исходящее после паузы >= 21 ч, когда последним писал менеджер
loose, after_client, gaps = Counter(), 0, Counter()
for c, ms in by_chat.items():
    ms = [m for m in ms if m["side"] in ("C", "O")]
    for a, b in zip(ms, ms[1:]):
        gap = b["ts"] - a["ts"]
        if b["side"] == "O" and gap >= timedelta(hours=21):
            if a["side"] == "O":
                loose[b["author"] or "Без автора"] += 1
            else:
                after_client += 1
        if b["side"] == "O" and a["side"] == "O":
            h = gap.total_seconds() / 3600
            gaps["<3ч" if h < 3 else "3-21ч" if h < 21 else "21-72ч" if h < 72 else "72ч+"] += 1
print("\nПаузы между двумя исходящими подряд:", dict(gaps))
print(f"Исходящих после 21+ ч, когда последним писал менеджер (кандидаты в follow-up): {sum(loose.values())}")
print(f"Исходящих после 21+ ч, когда последним писал клиент (поздний ответ, не follow-up): {after_client}")
for a, n in loose.most_common():
    print(f"   {a[:20]:<22}{n}")

now = datetime.now(config.TZ).replace(tzinfo=None, microsecond=0)
fu, due = Counter(), 0
for c, ms in by_chat.items():
    s = analyze(c, ms, now)
    for ts, a in s.followups:
        fu[a] += 1
    due += s.followup_due
print(f"\nПо правилам бота: follow-up в истории {sum(fu.values())}, нужно сделать {due}")
print("\nГотово. Пришлите этот вывод целиком: текстов переписки в нём нет.")

"""Проверка, как бот понял диалоги. Работает с локальной базой, в Битрикс не ходит.

python3 check.py               сводка: follow-up за 3 дня по менеджерам
python3 check.py 102891        разбор одного чата (номер из ссылки в алерте)
"""
import sys
from collections import Counter
from datetime import datetime, timedelta

from bot import config
from bot.store import Store
from bot.analytics import analyze, flag
from bot.engine import load_states

store = Store(config.DB_PATH)
now = datetime.now(config.TZ).replace(tzinfo=None, microsecond=0)

if len(sys.argv) > 1:
    chat = sys.argv[1]
    msgs = store.chat_messages(chat)
    for m in msgs:
        m["ts"] = datetime.fromisoformat(m["ts"])
    s = analyze(chat, msgs, now)
    print(f"Чат {chat}: {len(msgs)} сообщений\n")
    for m in msgs[-40:]:
        if m["side"] == "S":
            continue
        f = flag(m)
        tags = [k for k in ("req", "ack", "subst", "hold", "price", "offer", "question", "close") if f.get(k)]
        who = "КЛИЕНТ " if m["side"] == "C" else (m["author"] or "без автора")[:14]
        print(f"{m['ts']:%d.%m %H:%M}  {who:<14} [{','.join(tags)}]  {m['text'][:70]}")
    print(f"\nМенеджер: {s.owner}; первый ответ: {s.first_response_biz_sec and round(s.first_response_biz_sec / 60)} мин (раб.)")
    print(f"Клиент ждет: {'да, с ' + format(s.waiting_since, '%d.%m %H:%M') if s.waiting_since else 'нет'}; "
          f"follow-up нужен: {s.followup_due}; сделан: {s.followup_done}; follow-up в истории: {len(s.followups)}")
    print(f"Темы клиента: {s.needs or '-'}; закрыто: {s.covered or '-'}")
else:
    states = load_states(store, now, days=3)
    fu = Counter(a for s in states for ts, a in s.followups)
    due = Counter(s.owner for s in states if s.followup_due)
    print(f"Чатов за 3 дня: {len(states)}, сообщений в базе: {store.db.execute('select count(*) from messages').fetchone()[0]}")
    print(f"Самое раннее сообщение в базе: {store.db.execute('select min(ts) from messages').fetchone()[0]}")
    print("\nМенеджер        follow-up сделано за 3 дня   нужно сделать")
    for a in sorted(set(fu) | set(due), key=lambda a: -(fu[a] + due[a])):
        print(f"{a[:15]:<16}{fu[a]:>10}{due[a]:>24}")
    print("\nПримеры чатов, где нужен follow-up:", ", ".join(s.chat_id for s in states if s.followup_due)[:200])

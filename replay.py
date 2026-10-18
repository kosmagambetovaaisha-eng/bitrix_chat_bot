"""Прогон бота на старой выгрузке (май–сентябрь), чтобы проверить логику до подключения к Битрикс.
python replay.py <m1.pkl> <день YYYY-MM-DD>
"""
import sys
import os
from datetime import datetime, timedelta
from statistics import median

import pandas as pd

from bot import config
from bot.store import Store
from bot.engine import load_states, run_alerts
from bot import reports

src, day = sys.argv[1], datetime.fromisoformat(sys.argv[2])
db = "replay.sqlite"
if os.path.exists(db):
    os.remove(db)
store = Store(db)
m = pd.read_pickle(src)
m = m[m.t < day + timedelta(days=1)]
rows = [{"msg_id": int(r.n), "chat_id": str(r.did), "session_id": "", "ts": r.t.isoformat(timespec="seconds"),
         "author_id": "", "side": r.side, "kind": r.mt, "author": r.author if r.mt in ("MGR", "TECH") else "", "text": r.ct}
        for r in m.itertuples()]
store.add_messages(rows)

# 1) Алерты за день: тик каждые 5 минут
from bot import telegram, engine
captured = []
engine.telegram.send = lambda to, text, dry=False: captured.append(text)
t = day.replace(hour=config.WORK_START)
while t < day.replace(hour=config.WORK_END):
    run_alerts(store, load_states(store, t, days=3), t)
    t += timedelta(minutes=5)
lvl1 = [x for x in captured if x.startswith("⏰")]; lvl2 = [x for x in captured if x.startswith("🔴")]
print(f"За день: {len(lvl1)} алертов менеджерам (15+ мин), {len(lvl2)} часовых сводок руководителю (60+ мин)\n")
for x in (lvl1[:1] + lvl2[:1]):
    print(x + "\n")

# 2) Отчеты на конец дня
now = day.replace(hour=19, minute=30)
states = load_states(store, now, days=3)
print(reports.morning_digest(load_states(store, day.replace(hour=10, minute=5), days=3), day.replace(hour=10, minute=5)))
print()
print(reports.daily_report(states, day.date(), now))

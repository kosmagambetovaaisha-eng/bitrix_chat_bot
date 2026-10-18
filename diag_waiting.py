"""Кто из клиентов «ждет ответа» и почему. Работает с локальной базой, в Битрикс не ходит.
Запуск из папки бота: python3 diag_waiting.py            (сводка по всем)
                      python3 diag_waiting.py Имя     (сделки одного менеджера)
Тексты сообщений не печатаются, только время, количество и длина.
"""
import sys
from collections import Counter, defaultdict
from datetime import datetime

from bot import config
from bot.engine import load_states
from bot.reports import short
from bot.store import Store

store = Store(config.DB_PATH)
now = datetime.now(config.TZ).replace(tzinfo=None, microsecond=0)
who = sys.argv[1].lower() if len(sys.argv) > 1 else None
states = [s for s in load_states(store, now) if s.waiting_since is not None]

summary = defaultdict(Counter)
for s in states:
    o = short(s.owner)
    age = (now - s.waiting_since).total_seconds() / 3600
    summary[o]["всего"] += 1
    summary[o]["до 3 ч" if age < 3 else "3-24 ч" if age < 24 else "1-3 дн"] += 1
    summary[o]["никто не отвечал"] += s.n_out == 0
    summary[o]["был ответ раньше"] += s.n_out > 0
    summary[o]["«менеджер напишет»"] += s.waiting_on_hold

print(f"Ждут ответа: {len(states)} (на {now:%d.%m %H:%M})\n")
cols = ["всего", "до 3 ч", "3-24 ч", "1-3 дн", "никто не отвечал", "был ответ раньше", "«менеджер напишет»"]
hdr = ["Всего", "<3ч", "3-24ч", "1-3дн", "БезОтв", "БылОтв", "Напишет"]
print(f"{'Менеджер':<14}" + "".join(f"{c:>8}" for c in hdr))
for o, c in sorted(summary.items(), key=lambda x: -x[1]["всего"]):
    print(f"{o[:13]:<14}" + "".join(f"{c[k]:>8}" for k in cols))
print("\nБезОтв = в чате еще не было ни одного ответа, БылОтв = клиент написал снова после ответа, Напишет = после «менеджер напишет / уточню»")

if who:
    print(f"\nСделки {who}:")
    for s in sorted(states, key=lambda x: x.waiting_since):
        if who not in s.owner.lower() and who not in short(s.owner).lower():
            continue
        msgs = store.chat_messages(s.chat_id)
        after = [m for m in msgs if m["ts"] >= s.waiting_since.isoformat(timespec="seconds") and m["side"] == "C"]
        lens = ",".join(str(len(m["text"] or "")) for m in after[-5:])
        last_out = s.last_out_ts.strftime("%d.%m %H:%M") if s.last_out_ts else "нет"
        link = f"https://hickmet.bitrix24.kz/crm/deal/details/{s.chat_id[4:]}/" if s.chat_id.startswith("deal") else s.chat_id
        print(f"  {link}  ждет с {s.waiting_since:%d.%m %H:%M}, сообщений клиента {len(after)} (длина {lens}), "
              f"последний исходящий {last_out}, отвечали: {', '.join(short(m) for m in s.managers) or 'никто'}"
              f"{', «менеджер напишет»' if s.waiting_on_hold else ''}")

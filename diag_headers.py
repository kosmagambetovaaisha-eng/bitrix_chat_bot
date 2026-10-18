"""Проверка разбора комментариев Wazzup. Работает с локальной базой. Запуск: python3 diag_headers.py
1) Заголовки, которые бот считает клиентскими, но которые встречаются в 3+ разных сделках: скорее всего это менеджеры
   (у клиента своя сделка). Их нужно добавить в NAME_ALIASES. Цифры скрыты.
2) Доля ответов без автора («Телефон») по дням.
"""
import re
from collections import Counter, defaultdict

from bot import config
from bot.store import Store

store = Store(config.DB_PATH)
deals = defaultdict(set)
for chat, author in store.db.execute("SELECT chat_id, author FROM messages WHERE chat_id LIKE 'deal%' AND side='C'"):
    deals[author].add(chat)
print("Клиентские заголовки, которые встречаются в 3+ сделках:")
rows = sorted(((len(v), k) for k, v in deals.items() if len(v) >= 3), reverse=True)
for n, k in rows[:30]:
    print(f"   {n:>4} сделок  {re.sub(r'[0-9]', '#', k)}")
if not rows:
    print("   нет")
print("\nИсходящие по дням: с автором / без автора («Телефон»)")
by = defaultdict(Counter)
for day, kind in store.db.execute("SELECT substr(ts,1,10), kind FROM messages WHERE chat_id LIKE 'deal%' AND side='O'"):
    by[day][kind] += 1
for day in sorted(by)[-14:]:
    c = by[day]
    tot = sum(c.values())
    print(f"   {day}: с автором {c['MGR']}, без автора {c['OUT_UNATTR']} ({c['OUT_UNATTR'] / tot * 100:.0f}%)")
print("\nГотово. Текстов переписки в выводе нет.")

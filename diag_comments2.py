"""Формат комментариев Wazzup в ленте сделок. Запуск: python3 diag_comments2.py
Печатает только заголовки комментариев (до двоеточия), без текста сообщений.
Телефон и имя клиента перед скобкой скрываются.
"""
import re
from collections import Counter
from datetime import datetime, timedelta

from bot import config
from bot.bitrix import Bitrix

bx = Bitrix(config.BITRIX_WEBHOOK)
since = (datetime.now(config.TZ) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
deals = bx.list_all("crm.deal.list", {"filter": {">=DATE_MODIFY": since}, "select": ["ID"], "order": {"DATE_MODIFY": "DESC"}}, limit=15)
heads, icons, n = Counter(), Counter(), 0
for d in deals:
    for c in bx.list_all("crm.timeline.comment.list", {"filter": {"ENTITY_TYPE": "deal", "ENTITY_ID": d["ID"]},
                                                       "select": ["ID", "CREATED", "AUTHOR_ID", "COMMENT"]}, limit=30):
        t = str(c.get("COMMENT") or "")
        if "wazzup" not in t.lower():
            continue
        n += 1
        first = t.split("\n")[0]
        icons.update(re.findall(r"\[img[^\]]*\](.*?)\[/img\]", first, re.I) or ["нет картинки"])
        head = re.sub(r"\[img[^\]]*\].*?\[/img\]", "", first, flags=re.I).replace("&nbsp;", " ")
        head = re.sub(r"\[/?url[^\]]*\]", "", head).split(":")[0].strip()
        head = re.sub(r"(\S+\s+)?(\S+\s+)?\(\+?\d[\d\s\-]{7,}\)", "<клиент> (<телефон>)", head)
        heads[head] += 1
print(f"Сделок: {len(deals)}, комментариев Wazzup: {n}\n")
print("Картинки в начале комментария:")
for k, v in icons.most_common(10):
    print(f"   {v:>4}  {k}")
print("\nЗаголовки (до двоеточия):")
for k, v in heads.most_common(30):
    print(f"   {v:>4}  {k}")
print("\nГотово. Текстов сообщений в выводе нет.")

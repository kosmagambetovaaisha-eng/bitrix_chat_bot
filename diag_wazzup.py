"""Пишет ли Wazzup переписку в CRM Битрикс24 после отключения открытой линии.
Запуск: python3 diag_wazzup.py
Тексты не печатаются: только типы записей, количества и даты.
"""
from collections import Counter
from datetime import datetime, timedelta

from bot import config
from bot.bitrix import Bitrix, BitrixError

bx = Bitrix(config.BITRIX_WEBHOOK)
since = (datetime.now(config.TZ) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")

print(f"== Дела CRM, созданные после {since}, по типам")
try:
    acts = bx.list_all("crm.activity.list", {"filter": {">=CREATED": since},
                                             "select": ["ID", "PROVIDER_ID", "PROVIDER_TYPE_ID", "TYPE_ID", "OWNER_TYPE_ID", "AUTHOR_ID"],
                                             "order": {"ID": "DESC"}}, limit=500)
    print(f"   всего (до 500): {len(acts)}")
    for (p, t), n in Counter((a.get("PROVIDER_ID"), a.get("PROVIDER_TYPE_ID")) for a in acts).most_common(15):
        print(f"   {p} / {t}: {n}")
except BitrixError as e:
    print("   ОШИБКА:", e)

print("\n== Сделки, измененные за сутки")
try:
    deals = bx.list_all("crm.deal.list", {"filter": {">=DATE_MODIFY": since}, "select": ["ID", "DATE_MODIFY"],
                                          "order": {"DATE_MODIFY": "DESC"}}, limit=5)
except BitrixError as e:
    deals = []
    print("   ОШИБКА:", e)
for d in deals:
    print(f"\n   сделка {d['ID']} (изменена {d.get('DATE_MODIFY')})")
    try:
        a = bx.list_all("crm.activity.list", {"filter": {"OWNER_TYPE_ID": 2, "OWNER_ID": d["ID"], ">=CREATED": since},
                                              "select": ["ID", "PROVIDER_ID", "PROVIDER_TYPE_ID", "CREATED"]}, limit=50)
        print(f"      дела за сутки: {dict(Counter(x.get('PROVIDER_ID') for x in a))}")
    except BitrixError as e:
        print("      дела: ОШИБКА", e)
    try:
        c = bx.list_all("crm.timeline.comment.list", {"filter": {"ENTITY_TYPE": "deal", "ENTITY_ID": d["ID"]},
                                                      "select": ["ID", "CREATED", "AUTHOR_ID"]}, limit=50)
        fresh = [x for x in c if str(x.get("CREATED", "")) >= since[:10]]
        print(f"      комментарии в ленте: всего {len(c)}, за сутки {len(fresh)}, авторы {dict(Counter(str(x.get('AUTHOR_ID')) for x in fresh))}")
    except BitrixError as e:
        print("      комментарии: ОШИБКА", e)
print("\nГотово. Пришлите этот вывод целиком: текстов переписки в нём нет.")

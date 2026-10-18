"""Видит ли бот новые сессии открытых линий. Запуск: python3 diag_sessions.py
Тексты не печатаются.
"""
from datetime import datetime, timedelta

from bot import config
from bot.bitrix import Bitrix, BitrixError

bx = Bitrix(config.BITRIX_WEBHOOK)


def acts(title, params):
    print(f"\n== {title}")
    try:
        r = bx.call("crm.activity.list", params)
    except BitrixError as e:
        print("   ОШИБКА:", e)
        return []
    items = r.get("result") or []
    print(f"   всего: {r.get('total')}")
    for a in items[:8]:
        print(f"   дело {a['ID']}: сессия {a.get('ASSOCIATED_ENTITY_ID')}, создано {a.get('CREATED')}, "
              f"обновлено {a.get('LAST_UPDATED')}, завершено {a.get('COMPLETED')}")
    return items


sel = ["ID", "ASSOCIATED_ENTITY_ID", "CREATED", "LAST_UPDATED", "COMPLETED"]
since = (datetime.now(config.TZ) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
last = acts("Самые новые сессии в CRM (по ID)", {"filter": {"PROVIDER_ID": "IMOPENLINES_SESSION"}, "select": sel, "order": {"ID": "DESC"}})
acts(f"Обновлены после {since} (как ищет бот), от новых", {"filter": {"PROVIDER_ID": "IMOPENLINES_SESSION", ">=LAST_UPDATED": since}, "select": sel, "order": {"ID": "DESC"}})
acts(f"Созданы после {since}", {"filter": {"PROVIDER_ID": "IMOPENLINES_SESSION", ">=CREATED": since}, "select": sel, "order": {"ID": "DESC"}})

print("\n== Есть ли сессии новее, чем видно в CRM (imopenlines.dialog.get по номеру сессии)")
top = max([int(a["ASSOCIATED_ENTITY_ID"]) for a in last] or [109495])
cmds = {f"s{n}": ("imopenlines.dialog.get", {"SESSION_ID": n}) for n in range(top + 1, top + 400, 8)}
res, errs = bx.batch(cmds)
found = sorted((int(k[1:]), v.get("id"), v.get("date_create")) for k, v in res.items() if v)
print(f"   проверено номеров после {top}: {len(cmds)}, найдено сессий: {len(found)}, ошибок: {len(errs)}")
for n, chat, dt in found[:5] + found[-5:]:
    print(f"   сессия {n}: чат {chat}, чат создан {dt}")
print("\nГотово. Пришлите этот вывод целиком: текстов переписки в нём нет.")

"""Проверка: может ли вебхук забирать всю историю чата целиком (метод im.dialog.messages.get, право im).
Запуск из папки бота: python3 diag_im.py 102587 11467
Тексты не печатаются: только количества, ID и даты.
"""
import sys

from bot import config
from bot.bitrix import Bitrix, BitrixError

bx = Bitrix(config.BITRIX_WEBHOOK)
try:
    sc = bx.result("scope")
    print("Права вебхука:", ", ".join(sc), "| im:", "ЕСТЬ" if "im" in sc else "НЕТ")
except BitrixError as e:
    print("scope: ОШИБКА", e)

for chat in sys.argv[1:] or ["102587", "11467"]:
    print(f"\n== Чат {chat}")
    try:
        total = int((bx.result("imopenlines.dialog.get", {"CHAT_ID": chat}) or {}).get("message_count") or 0)
    except BitrixError as e:
        total = None
        print("   dialog.get: ОШИБКА", e)
    got, last_id, pages = {}, None, 0
    while pages < 40:
        params = {"DIALOG_ID": f"chat{chat}", "LIMIT": 50}
        if last_id:
            params["LAST_ID"] = last_id
        try:
            r = bx.result("im.dialog.messages.get", params) or {}
        except BitrixError as e:
            print("   im.dialog.messages.get: ОШИБКА", e)
            break
        msgs = r.get("messages") or []
        pages += 1
        if not msgs:
            break
        for m in msgs:
            got[int(m["id"])] = m
        last_id = min(int(m["id"]) for m in msgs)
        if len(msgs) < 50:
            break
    if got:
        ds = sorted(str(m.get("date"))[:16] for m in got.values())
        print(f"   im.dialog.messages.get: {len(got)} сообщений за {pages} запросов, с {ds[0]} по {ds[-1]}")
        print(f"   поля сообщения: {sorted(next(iter(got.values())).keys())}")
    print(f"   в Битрикс24 по dialog.get: {total}")
print("\nГотово. Пришлите этот вывод целиком: текстов переписки в нём нет.")

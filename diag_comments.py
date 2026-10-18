"""Что за комментарии появляются в ленте сделок (автор 201). Запуск: python3 diag_comments.py 114837 114957
Текст комментариев не печатается: только время, автор, длина, число строк и служебные признаки.
"""
import re
import sys

from bot import config
from bot.bitrix import Bitrix

bx = Bitrix(config.BITRIX_WEBHOOK)
KEYS = ["входящ", "исходящ", "автор", "whatsapp", "wazzup", "клиент", "менеджер", "сообщени", "канал", "назначен",
        "распредел", "очеред", "[b]", "[url", "http", "+7", "===", "→", "->"]
for deal in sys.argv[1:] or ["114837", "114957"]:
    print(f"\n== Сделка {deal}")
    items = bx.list_all("crm.timeline.comment.list", {"filter": {"ENTITY_TYPE": "deal", "ENTITY_ID": deal},
                                                      "select": ["ID", "CREATED", "AUTHOR_ID", "COMMENT", "FILES"]}, limit=20)
    for c in sorted(items, key=lambda x: str(x.get("CREATED"))):
        t = str(c.get("COMMENT") or "")
        low = t.lower()
        flags = [k for k in KEYS if k in low]
        shape = re.sub(r"[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]+", "x", t.split("\n")[0])[:60]
        print(f"   {c.get('CREATED')} автор {c.get('AUTHOR_ID')} длина {len(t)} строк {t.count(chr(10)) + 1} "
              f"файлы {bool(c.get('FILES'))} признаки {flags}\n      форма 1-й строки: {shape}")
print("\nГотово. Текстов в выводе нет: буквы заменены на x.")

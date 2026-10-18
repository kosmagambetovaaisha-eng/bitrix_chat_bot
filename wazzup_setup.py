"""Подключение вебхуков Wazzup к боту.
python3 wazzup_setup.py                 показать текущие настройки вебхуков Wazzup
python3 wazzup_setup.py https://<адрес сервера>/<WAZZUP_WEBHOOK_PATH>    подключить
Сначала запустите бота на сервере (python3 main.py): при подключении Wazzup шлет тестовый запрос и ждет ответ 200.
"""
import sys
import urllib.error

from bot import config
from bot.wazzup import api

if not config.WAZZUP_API_KEY:
    sys.exit("В env.txt нет WAZZUP_API_KEY (ключ из личного кабинета Wazzup, раздел API).")
try:
    cur = api("GET")
    print("Сейчас в Wazzup:", cur)
    if len(sys.argv) > 1:
        url = sys.argv[1]
        if cur.get("webhooksUri") and cur["webhooksUri"] != url and "--force" not in sys.argv:
            sys.exit(f"В Wazzup уже указан другой адрес вебхуков: {cur['webhooksUri']}. Если его использует другая система, "
                     "она перестанет получать сообщения. Чтобы заменить, добавьте --force.")
        print(api("PATCH", {"webhooksUri": url, "subscriptions": {"messagesAndStatuses": True, "contactsAndDealsCreation": False,
                                                                  "channelsUpdates": False, "templateStatus": False}}))
        print("Готово: Wazzup будет присылать сообщения боту.")
except urllib.error.HTTPError as e:
    print("Ошибка Wazzup:", e.code, e.read().decode("utf-8", "replace")[:300])

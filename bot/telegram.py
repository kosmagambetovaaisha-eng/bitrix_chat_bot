import json
import urllib.parse
import urllib.request

from . import config


def send(chat_id, text, dry_run=False):
    if dry_run or not config.TG_TOKEN or not chat_id:
        print(f"\n--- [Telegram -> {chat_id or 'не задан'}] ---\n{text}\n")
        return
    for i in range(0, len(text), 3900):
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[i:i + 3900], "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        with urllib.request.urlopen(f"https://api.telegram.org/bot{config.TG_TOKEN}/sendMessage", data=data, timeout=20) as r:
            res = json.loads(r.read())
            if not res.get("ok"):
                raise RuntimeError(f"Telegram: {res}")

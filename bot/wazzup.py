"""Прием переписки из Wazzup через вебхуки (открытая линия Битрикс24 отключена 13.10.2026).

Wazzup не отдает историю сообщений по API, он сам присылает каждое сообщение на адрес бота (POST, JSON):
{"messages": [{"messageId", "channelId", "chatType", "chatId", "dateTime", "type", "isEcho", "text",
               "authorName", "authorId", "status", "isDeleted", ...}]}
isEcho=false: входящее от клиента; isEcho=true: исходящее, автор в authorName.
Документация: https://wazzup24.com/help/api-en/webhooks/
"""
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .collector import to_local
from .parse import SIDE, clean_text, name_key

API = "https://api.wazzup24.com/v3/webhooks"
MEDIA = {"image": "[фото]", "video": "[видео]", "audio": "[аудио]", "document": "[файл]", "vcard": "[контакт]",
         "geo": "[геолокация]", "wapi_template": "", "missing_call": "[пропущенный звонок]"}


def chat_key(m):
    """Чат = канал Wazzup + номер клиента. В базе chat_id вида wz:<телефон>:<начало id канала>."""
    return f"wz:{m.get('chatId')}:{str(m.get('channelId', ''))[:8]}"


def to_row(parser, m):
    """Сообщение вебхука -> строка таблицы messages (или None, если сообщение пропускаем)."""
    if m.get("isDeleted") or not m.get("messageId") or not m.get("dateTime"):
        return None
    text = m.get("text") or MEDIA.get(m.get("type"), f"[{m.get('type')}]")
    if m.get("isEcho"):
        name = parser.manager_name(m.get("authorName") or "")
        if not name:
            kind = "OUT_UNATTR"
        elif name_key(name) in parser.excluded_keys:
            kind = "TECH"
        else:
            kind = "MGR"
        author = name
    else:
        kind, author = "CLI", ""
    return {"msg_id": str(m["messageId"]), "chat_id": chat_key(m), "session_id": str(m.get("channelId") or ""),
            "ts": to_local(m["dateTime"]).isoformat(timespec="seconds"), "author_id": str(m.get("authorId") or ""),
            "side": SIDE[kind], "kind": kind, "author": author, "text": clean_text(text)}


def handle(store, parser, body):
    """Разобрать тело вебхука и сохранить сообщения. Возвращает число сохраненных."""
    data = json.loads(body or b"{}")
    if data.get("test"):
        return 0
    rows = [r for r in (to_row(parser, m) for m in data.get("messages") or []) if r]
    # одно и то же сообщение может прийти повторно (смена статуса, правка): храним последнюю версию
    store.db.executemany("INSERT OR REPLACE INTO messages VALUES "
                         "(:msg_id,:chat_id,:session_id,:ts,:author_id,:side,:kind,:author,:text)", rows)
    store.db.commit()
    return len(rows)


def serve(store_factory, parser_factory, port, path):
    """HTTP-сервер для вебхуков в отдельном потоке. SQLite открываем в потоке сервера."""
    local = threading.local()

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path.rstrip("/") != path.rstrip("/"):
                self.send_response(404); self.end_headers(); return
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                if not hasattr(local, "store"):
                    local.store = store_factory()
                handle(local.store, parser_factory(), body)
            except Exception as e:  # отвечаем 200, чтобы Wazzup не отключил вебхук, ошибку пишем в лог
                print("Ошибка вебхука Wazzup:", type(e).__name__, e)
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Жду вебхуки Wazzup на порту {port}, путь {path}")
    return srv


def api(method, body=None):
    req = urllib.request.Request(API, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {config.WAZZUP_API_KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")

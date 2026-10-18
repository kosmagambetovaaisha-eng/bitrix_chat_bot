"""SQLite-хранилище: сессии открытых линий, сообщения, пользователи, отправленные алерты."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, name TEXT, is_employee INTEGER, is_excluded INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, chat_id TEXT, line_id TEXT, source TEXT,
  created TEXT, closed INTEGER DEFAULT 0, responsible_id TEXT,
  last_polled TEXT, last_msg_id INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
  msg_id INTEGER, chat_id TEXT, session_id TEXT, ts TEXT,
  author_id TEXT, side TEXT, kind TEXT, author TEXT, text TEXT,
  PRIMARY KEY (chat_id, msg_id)
);
CREATE INDEX IF NOT EXISTS ix_msg_chat_ts ON messages(chat_id, ts);
CREATE INDEX IF NOT EXISTS ix_msg_ts ON messages(ts);
CREATE TABLE IF NOT EXISTS chats (
  chat_id TEXT PRIMARY KEY, last_msg_id INTEGER DEFAULT 0, last_polled TEXT
);
CREATE TABLE IF NOT EXISTS deals (
  deal_id TEXT PRIMARY KEY, responsible_id TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
  key TEXT PRIMARY KEY, sent_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS tg_users (
  chat_id TEXT PRIMARY KEY, role TEXT, manager TEXT, name TEXT, updated TEXT
);
"""


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- meta
    def get(self, k, default=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def set(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, str(v)))
        self.db.commit()

    # --- users
    def upsert_users(self, rows):
        self.db.executemany("INSERT OR REPLACE INTO users(id,name,is_employee,is_excluded) VALUES (?,?,?,?)", rows)
        self.db.commit()

    def users(self):
        return {r["id"]: dict(r) for r in self.db.execute("SELECT * FROM users")}

    # --- sessions
    def upsert_session(self, s):
        self.db.execute(
            """INSERT INTO sessions(session_id,chat_id,line_id,source,created,closed,responsible_id)
               VALUES (:session_id,:chat_id,:line_id,:source,:created,:closed,:responsible_id)
               ON CONFLICT(session_id) DO UPDATE SET chat_id=COALESCE(excluded.chat_id, chat_id),
               closed=excluded.closed, responsible_id=excluded.responsible_id""", s)

    def open_sessions(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM sessions WHERE closed=0 OR last_polled IS NULL")]

    def mark_polled(self, session_id, ts, last_msg_id):
        self.db.execute("UPDATE sessions SET last_polled=?, last_msg_id=MAX(last_msg_id,?) WHERE session_id=?",
                        (ts, last_msg_id, session_id))

    # --- chats (сбор всей истории чата через im.dialog.messages.get)
    def chat_last_ids(self):
        return {r["chat_id"]: r["last_msg_id"] for r in self.db.execute("SELECT * FROM chats")}

    def mark_chat(self, chat_id, ts, last_msg_id):
        self.db.execute("""INSERT INTO chats(chat_id,last_msg_id,last_polled) VALUES (?,?,?)
                           ON CONFLICT(chat_id) DO UPDATE SET last_polled=excluded.last_polled,
                           last_msg_id=MAX(last_msg_id, excluded.last_msg_id)""", (chat_id, last_msg_id, ts))

    # --- сделки (ответственный, для ответов «Телефон» и чатов без ответа)
    def set_deals(self, rows):
        self.db.executemany("INSERT OR REPLACE INTO deals VALUES (?,?)", rows)
        self.db.commit()

    def deal_responsibles(self):
        return {r[0]: r[1] for r in self.db.execute("SELECT deal_id, responsible_id FROM deals")}

    # --- messages
    def add_messages(self, rows):
        self.db.executemany(
            "INSERT OR IGNORE INTO messages VALUES (:msg_id,:chat_id,:session_id,:ts,:author_id,:side,:kind,:author,:text)", rows)
        self.db.commit()

    def messages_for_chats(self, chats):
        out = {}
        for i in range(0, len(chats), 500):
            part = chats[i:i + 500]
            q = "SELECT * FROM messages WHERE chat_id IN (%s) ORDER BY chat_id, ts, msg_id" % ",".join("?" * len(part))
            for r in self.db.execute(q, part):
                out.setdefault(r["chat_id"], []).append(dict(r))
        return out

    def chats_active_since(self, ts):
        return [r[0] for r in self.db.execute("SELECT DISTINCT chat_id FROM messages WHERE ts>=?", (ts,))]

    def chat_messages(self, chat_id):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM messages WHERE chat_id=? ORDER BY ts, msg_id", (chat_id,))]

    # --- alerts (чтобы не слать одно и то же дважды)
    def alert_sent(self, key):
        return self.db.execute("SELECT 1 FROM alerts WHERE key=?", (key,)).fetchone() is not None

    def mark_alert(self, key, ts):
        self.db.execute("INSERT OR IGNORE INTO alerts VALUES (?,?)", (key, ts))
        self.db.commit()

    # --- доступ к Telegram-боту: role = admin | manager | pending | blocked
    def tg_user(self, chat_id):
        r = self.db.execute("SELECT * FROM tg_users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(r) if r else None

    def tg_set(self, chat_id, role, manager="", name=None, ts=""):
        old = self.tg_user(chat_id) or {}
        self.db.execute("INSERT OR REPLACE INTO tg_users VALUES (?,?,?,?,?)",
                        (str(chat_id), role, manager, name if name is not None else old.get("name", ""), ts))
        self.db.commit()

    def tg_users(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM tg_users ORDER BY role, manager, name")]

    def tg_chats(self, role, manager=None):
        q, a = "SELECT chat_id FROM tg_users WHERE role=?", [role]
        if manager is not None:
            q += " AND manager=?"; a.append(manager)
        return [r[0] for r in self.db.execute(q, a)]

    def commit(self):
        self.db.commit()

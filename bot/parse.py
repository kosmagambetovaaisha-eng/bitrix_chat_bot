"""Разбор сырого сообщения Битрикс24 / Wazzup: кто написал (клиент, менеджер, система) и чистый текст.

Правило из анализа: менеджер = автор исходящего сообщения. Поле «ответственный» сессии не используется.
Wazzup пересылает в Битрикс сообщения, отправленные с телефона, с заголовком
«=== Исходящее сообщение, автор: Битрикс24 (Имя) ===». Если вместо имени «Телефон», автор неизвестен.
"""
import re

HDR = re.compile(r"=== Исходящее сообщение, автор: (.*?) ===")
WZ = "=== SYSTEM WZ ==="
SYSP = re.compile(r"Создан|Начат новый диалог|перенаправлено|transferred|Контактная информация|прикреплена|"
                  r"Автоматическое завершение|работу с диалогом|снят с оператора|присоединил|Session closed|^\[b\]|Создана")
WZ_ERR = re.compile(r"нельзя отправить|нельзя начать|не доставлено|Пополните баланс|error|диалоговое окно закрыто|"
                    r"канал не оплачен|Файл не подходит")
BBCODE = re.compile(r"\[/?(b|i|u|s|br|url|quote|color|size|user|chat|icon|send|put|code|context)[^\]]*\]", re.I)

# kind: CLI клиент, MGR менеджер (автор известен), OUT_UNATTR исходящее без автора,
#       TECH технический пользователь, SYS система, DELIVERY_FAIL ошибка доставки
SIDE = {"CLI": "C", "MGR": "O", "OUT_UNATTR": "O", "TECH": "O", "SYS": "S", "DELIVERY_FAIL": "S"}


# Варианты написания имен менеджеров (латиница, кириллица, порядок слов) -> одно имя: из names.txt
# (строки «вариант = каноническое», в git не попадает) и из env.txt: NAME_ALIASES=Иван Петров:Ivan Petrov;...
ALIASES = {}


def _load_names(path=None):
    import os
    path = path or os.environ.get("NAMES_PATH", "names.txt")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith(("#", "!")) and "=" in line:
                a, b = line.split("=", 1)
                ALIASES[a.strip()] = b.strip()


_load_names()


def norm_name(s):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    s = re.sub(r"^Битрикс24 \((.*)\)$", r"\1", s)
    return s


KZ_FOLD = str.maketrans("қғұүәөіңһё", "кгууаоинхе")


def name_key(s):
    return " ".join(sorted(norm_name(s).lower().translate(KZ_FOLD).split()))


def clean_text(t):
    t = (t or "").split(WZ)[0]
    t = BBCODE.sub(" ", t).replace("ㅤ", " ")
    return re.sub(r"\s+", " ", t).strip()


import os
for pair in os.environ.get("NAME_ALIASES", "").split(";"):
    if ":" in pair:
        a, b = pair.split(":", 1)
        ALIASES[a.strip()] = b.strip()
ALIAS_KEY = {}


def canonical(name):
    """Одно имя для всех вариантов написания (сравнение без учета порядка слов и регистра)."""
    if not ALIAS_KEY:
        for k, v in ALIASES.items():
            ALIAS_KEY[name_key(k)] = v
            ALIAS_KEY[name_key(v)] = v
    n = norm_name(name)
    return ALIAS_KEY.get(name_key(n), n)


class Parser:
    def __init__(self, users, excluded_ids=(), excluded_names=()):
        """users: {id: {'name', 'is_employee'}} из user.get."""
        self.users = users
        self.excluded_ids = set(map(str, excluded_ids))
        self.excluded_keys = {name_key(n) for n in excluded_names}
        self.by_key = {name_key(u["name"]): canonical(u["name"]) for u in users.values() if u.get("is_employee")}

    def manager_name(self, raw):
        n = norm_name(raw)
        if not n or n in ("Телефон", "[ИМЯ]"):
            return ""
        return canonical(self.by_key.get(name_key(n), n))

    def classify(self, author_id, text):
        """-> (kind, author_name, clean_text)"""
        author_id = str(author_id or "0")
        raw = text or ""
        m = HDR.search(raw)
        if m:  # исходящее, проброшенное Wazzup (часто приходит от имени клиента/коннектора)
            name = self.manager_name(m.group(1))
            body = clean_text(HDR.split(raw)[-1])
            if not name:
                return "OUT_UNATTR", "", body
            if name_key(name) in self.excluded_keys:
                return "TECH", name, body
            return "MGR", name, body
        u = self.users.get(author_id)
        if author_id == "0" or u is None and SYSP.search(raw):
            return "SYS", "", clean_text(raw)
        if u and u.get("is_employee"):
            nm = canonical(u["name"])
            if author_id in self.excluded_ids or name_key(nm) in self.excluded_keys:
                return "TECH", nm, clean_text(raw)
            return "MGR", nm, clean_text(raw)
        # клиент (пользователь коннектора)
        if WZ in raw:
            pre = raw.split(WZ)[0].strip(" ㅤ")
            if WZ_ERR.search(raw):
                return ("DELIVERY_FAIL" if pre else "SYS"), "", clean_text(raw)
            return ("SYS" if not pre else "OUT_UNATTR"), "", clean_text(raw)
        return "CLI", "", clean_text(raw)

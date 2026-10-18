"""Рабочий график менеджеров из schedule.txt: по нему считаются скорость ответа и ожидание клиента.
Кого нет в графике, считаем по общему WORK_START-WORK_END в WORK_DAYS."""
import os
import re
from datetime import datetime, timedelta

from . import config
from .parse import canonical

_SCHED = None  # имя -> [(start_min, end_min) или None] на 7 дней недели


def _hm(s):
    h, _, m = s.strip().partition(":")
    return int(h) * 60 + int(m or 0)


def load(path=None):
    global _SCHED
    _SCHED = {}
    path = path or config.SCHEDULE_PATH
    if not os.path.exists(path):
        return _SCHED
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, *days = [x.strip() for x in line.split(";")]
        if len(days) != 7:
            print(f"schedule.txt: у «{name}» должно быть 7 дней, строка пропущена")
            continue
        week = []
        for d in days:
            m = re.match(r"^(\d{1,2}(?::\d\d)?)\s*-\s*(\d{1,2}(?::\d\d)?)$", d)
            week.append((_hm(m.group(1)), _hm(m.group(2))) if m else None)
        _SCHED[canonical(name)] = week
    return _SCHED


def sched():
    return _SCHED if _SCHED is not None else load()


def _default(day):
    if day.isoweekday() not in config.WORK_DAYS:
        return None
    return config.WORK_START * 60, config.WORK_END * 60


def shift(name, day):
    """(начало, конец) смены менеджера в этот день как datetime, или None (выходной)."""
    week = sched().get(name)
    hm = week[day.weekday()] if week else _default(day)
    if not hm:
        return None
    d0 = datetime.combine(day if not isinstance(day, datetime) else day.date(), datetime.min.time())
    return d0 + timedelta(minutes=hm[0]), d0 + timedelta(minutes=hm[1])


def team_shift(day):
    """Рабочее время команды: от самого раннего начала до самого позднего конца смен в этот день."""
    spans = [shift(n, day) for n in sched()] + [shift("", day)]
    spans = [s for s in spans if s]
    return (min(s[0] for s in spans), max(s[1] for s in spans)) if spans else None


def _overlap(a, b, span_fn):
    if b <= a:
        return 0.0
    tot, day = 0.0, a.date()
    while day <= b.date():
        sp = span_fn(day)
        if sp:
            s, e = max(a, sp[0]), min(b, sp[1])
            if e > s:
                tot += (e - s).total_seconds()
        day += timedelta(days=1)
    return tot


def biz_seconds(name, a, b):
    """Секунды между a и b, попавшие в смены менеджера name (None = рабочее время команды)."""
    return _overlap(a, b, team_shift if name is None else (lambda d: shift(name, d)))


def on_shift(name, t):
    sp = team_shift(t.date()) if name is None else shift(name, t.date())
    return bool(sp) and sp[0] <= t < sp[1]


def describe(name, day):
    sp = shift(name, day)
    if name not in sched():
        return f"{sp[0]:%H:%M}–{sp[1]:%H:%M} (общий график)" if sp else "выходной (общий график)"
    return f"{sp[0]:%H:%M}–{sp[1]:%H:%M}" if sp else "выходной"

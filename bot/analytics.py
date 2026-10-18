"""Аналитика диалога «на сейчас». Те же определения, что в отчете за май–сентябрь:

- первый ответ: от первого запроса клиента до первого содержательного ответа менеджера
  (приветствие, представление, «менеджер напишет», просьба позвонить не считаются);
- рабочее время: смены менеджеров из schedule.txt (команда: от самой ранней до самой поздней смены);
- клиент ждет ответа: последнее сообщение от клиента и ему нужен ответ;
- follow-up: клиент молчит 24 ч и больше, менеджер написал снова (новая волна не раньше чем через 3 ч);
- образцовый диалог: первый ответ до 15 мин в рабочее время, все вопросы закрыты, клиент не ждет.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import Counter

from . import config, schedule
from .rules import (lang, is_ack, subst_len, MEDIA, STORY, POSTPONE, DECLINE, QWORD, GREET_STRIP, REPEAT, NEED,
                    NEED_PRIO, NEED_RU, COVER, HOLD, CALL_O, OFFER, GREET_O, INTRO, NEXTSTEP, FOLLOWTPL, HOT, BOOKED, CLOSE_O)

WAVE_GAP = timedelta(hours=3)


def biz_seconds(a, b, name=None):
    """Секунды рабочего времени между a и b: по смене менеджера name или (None) по рабочему времени команды."""
    return schedule.biz_seconds(name, a, b)


def in_work_hours(t, name=None):
    return schedule.on_shift(name, t)


_CACHE = {}


def flag(msg):
    """Признаки одного сообщения, с кэшем по (chat_id, msg_id): регулярки считаются один раз."""
    key = (msg.get("chat_id"), msg.get("msg_id"))
    if key[1] is not None and key in _CACHE:
        return _CACHE[key]
    f = _flag(msg)
    if key[1] is not None:
        _CACHE[key] = f
    return f


def _flag(msg):
    t = msg["text"] or ""
    f = {}
    if msg["side"] == "C":
        story = bool(STORY.search(t))
        ack = is_ack(t)
        q = bool(QWORD.search(GREET_STRIP.sub(" ", t))) and not ack
        short_decline = bool(DECLINE.search(t)) and len(t) < 40 and "?" not in t and not any(
            w in t.lower() for w in ("дорого", "қымбат", "кымбат"))
        f["ack"] = ack
        f["media"] = bool(MEDIA.search(t))
        f["decline"] = bool(DECLINE.search(t)) and not f["media"]
        f["postpone"] = bool(POSTPONE.search(t)) and len(t) < 120
        f["req"] = not ack and not f["postpone"] and not short_decline and not (story and not q)
        f["needs"] = {k for k, r in NEED.items() if k != "hajj" and r.search(t)} if not story else set()
        f["repeat"] = bool(REPEAT.search(t))
        f["hot"] = bool(HOT.search(t))
        f["booked"] = bool(BOOKED.search(t))
    elif msg["side"] == "O":
        price = bool(COVER["price"].search(t))
        offer = bool(OFFER.search(t)) and len(t) > 150
        hold = bool(HOLD.search(t)) and len(t) < 160
        handoff = "[ТЕЛ]" in t and not price and len(t) < 300
        greet_intro = bool(GREET_O.search(t) or INTRO.search(t)) and subst_len(t) < 15
        f["price"] = price
        f["offer"] = offer
        f["question"] = "?" in t
        f["hold"] = hold
        f["call"] = bool(CALL_O.search(t))
        f["subst"] = t == "" or "?" in t or price or offer or not (greet_intro or hold or handoff)
        f["next"] = bool(NEXTSTEP.search(t))
        f["followup_tpl"] = bool(FOLLOWTPL.search(t))
        f["close"] = bool(CLOSE_O.search(t)) and len(t) < 200 and "?" not in t
        f["covers"] = {k for k, r in COVER.items() if k != "job_partner" and r.search(t)}
    return f


@dataclass
class DialogState:
    chat_id: str
    first_client_ts: datetime = None
    first_request_ts: datetime = None
    first_response_ts: datetime = None
    first_response_by: str = ""
    first_response_sec: float = None
    first_response_biz_sec: float = None
    managers: Counter = field(default_factory=Counter)
    primary_manager: str = ""
    last_manager: str = ""
    language: str = "neutral"
    needs: set = field(default_factory=set)
    covered: set = field(default_factory=set)
    waiting_since: datetime = None       # клиент ждет ответа с этого момента
    waiting_biz_min: float = 0.0
    waiting_on_hold: bool = False        # клиенту написали только «менеджер напишет / уточню»
    hold_since: datetime = None
    last_client_ts: datetime = None
    last_out_ts: datetime = None
    last_out_kind: str = ""              # price / offer / question / short
    followup_due: bool = False           # клиент молчит >= 24 ч, повторного касания не было
    followup_done: bool = False
    client_declined: bool = False
    client_hot: bool = False
    client_booked: bool = False
    price_asked: bool = False
    price_given: bool = False
    n_client: int = 0
    n_out: int = 0
    n_out_unattr: int = 0
    out_by_day: Counter = field(default_factory=Counter)  # (date, manager) -> исходящих
    followups: list = field(default_factory=list)          # [(ts, manager)]

    @property
    def owner(self):
        return self.last_manager or self.primary_manager or "Нет менеджера"

    @property
    def fully_covered(self):
        return bool(self.needs) and self.needs <= self.covered

    @property
    def model(self):
        return (self.first_response_biz_sec is not None and self.first_response_biz_sec <= 900
                and (self.fully_covered or not self.needs) and self.waiting_since is None and self.n_out > 0)


def analyze(chat_id, msgs, now):
    """msgs: список dict (ts: datetime, side, kind, author, text) по возрастанию времени."""
    st = DialogState(chat_id=chat_id)
    msgs = [m for m in msgs if m["ts"] <= now]
    langs = Counter()
    pending_req = None          # первый неотвеченный запрос клиента
    hold_since = None
    silence_from = None         # последнее сообщение клиента, после которого менеджер отвечал
    for m in msgs:
        f = flag(m)
        ts = m["ts"]
        if m["side"] == "C":
            st.n_client += 1
            st.last_client_ts = ts
            if st.first_client_ts is None:
                st.first_client_ts = ts
            lg = lang(m["text"])
            if lg != "neutral":
                langs[lg] += 1
            st.needs |= f["needs"]
            st.price_asked |= "price" in f["needs"]
            st.client_declined = f["decline"] or f["postpone"]
            st.client_hot |= f["hot"]
            st.client_booked |= f["booked"]
            if f["req"]:
                if st.first_request_ts is None:
                    st.first_request_ts = ts
                if pending_req is None:
                    pending_req = ts
            silence_from = None
        elif m["side"] == "O":
            st.n_out += 1
            if m["kind"] == "MGR":
                st.managers[m["author"]] += 1
                st.last_manager = m["author"]
                st.out_by_day[(ts.date(), m["author"])] += 1
            elif m["kind"] == "OUT_UNATTR":
                st.n_out_unattr += 1
            st.covered |= f["covers"]
            st.price_given |= f["price"]
            # follow-up: менеджер пишет повторно после >= FOLLOWUP_HOURS молчания клиента
            if st.last_out_ts and st.last_client_ts and st.last_out_ts > st.last_client_ts and \
                    ts - st.last_out_ts >= WAVE_GAP and ts - max(st.last_out_ts, st.last_client_ts) >= timedelta(hours=config.FOLLOWUP_HOURS) - WAVE_GAP:
                st.followups.append((ts, m["author"] or "Без автора"))
            if f["subst"]:
                if st.first_request_ts and st.first_response_ts is None:
                    st.first_response_ts = ts
                    st.first_response_by = m["author"] or "Без автора"
                    st.first_response_sec = (ts - st.first_request_ts).total_seconds()
                    st.first_response_biz_sec = biz_seconds(st.first_request_ts, ts)
                pending_req = None
                hold_since = None
                st.last_out_kind = "price" if f["price"] else "offer" if f["offer"] else "question" if f["question"] else "short"
            if f["close"]:
                st.last_out_kind = "close"
            elif f["hold"] and pending_req is not None and hold_since is None:
                hold_since = ts
            st.last_out_ts = ts
    st.primary_manager = st.managers.most_common(1)[0][0] if st.managers else ""
    st.language = "kz" if langs["kz"] > langs["ru"] else "ru" if langs["ru"] > langs["kz"] else ("mixed" if langs else "neutral")
    if pending_req is not None:
        st.waiting_since = pending_req
        st.waiting_biz_min = biz_seconds(pending_req, now) / 60
        st.waiting_on_hold = hold_since is not None
        st.hold_since = hold_since
    # follow-up по последнему молчанию клиента
    if st.last_out_ts and (st.last_client_ts is None or st.last_out_ts > st.last_client_ts) and not st.client_declined:
        first_out_after = next((m["ts"] for m in msgs if m["side"] == "O" and (st.last_client_ts is None or m["ts"] > st.last_client_ts)), None)
        silent = now - first_out_after if first_out_after else timedelta(0)
        worth = st.last_out_kind in ("price", "offer", "question") or st.client_hot or (st.needs and not st.fully_covered and st.last_out_kind != "close")
        if silent >= timedelta(hours=config.FOLLOWUP_HOURS) and worth and not st.client_booked:
            later = [m for m in msgs if m["side"] == "O" and m["ts"] >= first_out_after + WAVE_GAP]
            st.followup_done = bool(later)
            st.followup_due = not later
    return st


def need_labels(keys):
    return ", ".join(NEED_RU.get(k, k) for k in NEED_PRIO if k in keys) or "Общий вопрос"

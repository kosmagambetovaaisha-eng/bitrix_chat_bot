"""Клиент REST API Битрикс24 через входящий вебхук.

Лимит Битрикс: около 2 запросов в секунду, batch до 50 команд в одном запросе.
"""
import time
import json
import urllib.parse
import urllib.request
import urllib.error


class BitrixError(Exception):
    pass


class Bitrix:
    def __init__(self, webhook, min_interval=0.55, timeout=30):
        if not webhook or "/rest/" not in webhook:
            raise ValueError("BITRIX_WEBHOOK не задан или имеет неверный вид")
        import re
        # если в адрес попало имя метода (например .../profile.json), убираем его
        webhook = re.sub(r"/[A-Za-z0-9_.]+\.json/?$", "", webhook.strip())
        self.base = webhook.rstrip("/") + "/"
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0

    def _post(self, method, params):
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        data = urllib.parse.urlencode(_flatten(params or {}), doseq=True).encode()
        req = urllib.request.Request(self.base + method + ".json", data=data)
        for attempt in range(5):
            self._last = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                try:
                    err = json.loads(body)
                except ValueError:
                    err = {"error": str(e.code), "error_description": body[:300]}
                if err.get("error") in ("QUERY_LIMIT_EXCEEDED", "OPERATION_TIME_LIMIT") or e.code in (502, 503):
                    time.sleep(2 * (attempt + 1))
                    continue
                raise BitrixError(f"{method}: {err.get('error')} {err.get('error_description', '')}")
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                # обрыв связи (Connection reset, таймаут): ждем и повторяем
                time.sleep(2 * (attempt + 1))
                last = e
        raise BitrixError(f"{method}: нет ответа от портала")

    def call(self, method, params=None):
        res = self._post(method, params)
        if "error" in res:
            raise BitrixError(f"{method}: {res.get('error')} {res.get('error_description', '')}")
        return res

    def result(self, method, params=None):
        return self.call(method, params).get("result")

    def list_all(self, method, params=None, limit=None):
        """Постраничная выборка для методов *.list (start/next)."""
        params = dict(params or {})
        out, start = [], 0
        while True:
            params["start"] = start
            res = self.call(method, params)
            items = res.get("result") or []
            if isinstance(items, dict):  # некоторые методы возвращают {items: [...]}
                items = items.get("items") or items.get("tasks") or list(items.values())
            out.extend(items)
            if limit and len(out) >= limit:
                return out[:limit]
            if "next" not in res:
                return out
            start = res["next"]

    def batch(self, commands, halt=0):
        """commands: {key: (method, params)} -> {key: result}. Режется по 50."""
        keys = list(commands)
        result, errors = {}, {}
        for i in range(0, len(keys), 50):
            chunk = keys[i:i + 50]
            cmd = {k: commands[k][0] + "?" + urllib.parse.urlencode(_flatten(commands[k][1] or {}), doseq=True) for k in chunk}
            res = self.result("batch", {"halt": halt, "cmd": cmd})
            result.update(res.get("result") or {})
            errors.update(res.get("result_error") or {})
        return result, errors


def _flatten(d, prefix=""):
    """{'filter': {'>ID': 5}} -> {'filter[>ID]': 5} в формате, который понимает Битрикс."""
    out = {}
    for k, v in d.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                if isinstance(x, dict):
                    out.update(_flatten(x, f"{key}[{i}]"))
                else:
                    out[f"{key}[{i}]"] = x
        elif isinstance(v, bool):
            out[key] = "Y" if v else "N"
        else:
            out[key] = v
    return out

# -*- coding: utf-8 -*-
import json as _json
import urllib.error
import urllib.request


def _build_request(url, method, headers, body):
    method = (method or "GET").upper()
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", "LuaStudio/1.0")
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = _json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        elif isinstance(body, bytes):
            data = body
        else:
            data = str(body).encode("utf-8")
    return urllib.request.Request(str(url), data=data, headers=hdrs, method=method)


def request(url, method="GET", headers=None, body=None, timeout=10.0):
    try:
        req = _build_request(url, method, headers, body)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                text = raw.decode("utf-8")
            except Exception:
                text = raw.decode("latin-1", errors="replace")
            return {"status": resp.status, "body": text,
                    "headers": dict(resp.headers.items()), "error": None}
    except urllib.error.HTTPError as ex:
        try:
            text = ex.read().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        hdrs = {}
        try:
            hdrs = dict(ex.headers.items())
        except Exception:
            pass
        return {"status": ex.code, "body": text, "headers": hdrs, "error": str(ex)}
    except Exception as ex:
        return {"status": 0, "body": "", "headers": {}, "error": str(ex)}

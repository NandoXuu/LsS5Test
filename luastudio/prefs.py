import json
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "editor_prefs.json")

DEFAULTS = {
    "font_size": 15,
    "indent_guides": True,
}

_data = None


def _load():
    global _data
    if _data is None:
        _data = dict(DEFAULTS)
        try:
            with open(_PATH, encoding="utf-8") as fh:
                saved = json.load(fh)
            if isinstance(saved, dict):
                for k in DEFAULTS:
                    if k in saved:
                        _data[k] = saved[k]
        except Exception:
            pass
    return _data


def get(key):
    return _load().get(key, DEFAULTS.get(key))


def set(key, value):
    _load()[key] = value
    try:
        with open(_PATH, "w", encoding="utf-8") as fh:
            json.dump(_data, fh)
    except Exception:
        pass

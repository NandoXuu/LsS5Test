# -*- coding: utf-8 -*-
from .lua import LuaTable, tostring, to_py

MAX_FLAGS = 256


def _num(v, default=0.0):
    try:
        f = float(v)
        return f if f == f else default
    except Exception:
        return default


def _sources(key):
    if isinstance(key, LuaTable):
        v = to_py(key)
        seq = v if isinstance(v, list) else list(v.values()) if isinstance(v, dict) else []
        return [tostring(x) for x in seq if x is not None]
    if key is None:
        return []
    return [tostring(key)]


class KeyFlag(LuaTable):
    __slots__ = ("mgr", "sources", "seconds", "until", "frame", "fired")

    def __init__(self, mgr, sources, seconds):
        LuaTable.__init__(self)
        self.mgr = mgr
        self.sources = sources
        self.seconds = max(0.0, seconds)
        self.until = 0.0
        self.frame = -1
        self.fired = False
        self.set("Reset", lambda *a: self.reset())
        self.set("Trigger", lambda *a: self.trigger())

    def trigger(self):
        self.until = self.mgr.clock() + self.seconds
        self.frame = self.mgr.frame
        self.fired = True

    def reset(self):
        self.until = 0.0
        self.frame = -1
        self.fired = False

    def poll(self):
        for s in self.sources:
            if self.mgr.query(s, 1):
                self.trigger()
                return

    def active(self):
        if self.frame == self.mgr.frame:
            return True
        return self.mgr.clock() < self.until

    def remaining(self):
        if not self.fired:
            return 0.0
        return max(0.0, self.until - self.mgr.clock())

    def lua_value(self):
        return self.active()

    def get(self, key):
        if key == "value":
            return self.active()
        if key == "remaining":
            return float(self.remaining())
        if key == "pressed":
            return self.frame == self.mgr.frame
        if key == "held":
            return any(self.mgr.query(s, 0) for s in self.sources)
        if key == "seconds":
            return float(self.seconds)
        if key == "key":
            return self.sources[0] if len(self.sources) == 1 else None
        return LuaTable.get(self, key)

    def set(self, key, value):
        if key == "seconds":
            self.seconds = max(0.0, _num(value, self.seconds))
            return
        LuaTable.set(self, key, value)


def install(rt):
    mgr = rt.input
    t = LuaTable()

    def _is_pressed(key=None, seconds=1.0, *rest):
        srcs = _sources(key)
        if not srcs:
            rt.log("[keynumb] IsPressed precisa de uma tecla, ex.: keynumb.IsPressed(\"Z\", 1)")
            return False
        secs = max(0.0, _num(seconds, 1.0))
        for f in mgr.key_flags:
            if f.sources == srcs and f.seconds == secs:
                return f
        if len(mgr.key_flags) >= MAX_FLAGS:
            rt.log("[keynumb] limite de %d flags atingido" % MAX_FLAGS)
            return False
        f = KeyFlag(mgr, srcs, secs)
        mgr.key_flags.append(f)
        return f

    t.set("IsPressed", _is_pressed)
    t.set("isPressed", _is_pressed)
    t.set("Clear", lambda *a: mgr.key_flags.clear())
    return t

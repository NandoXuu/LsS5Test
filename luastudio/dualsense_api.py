# -*- coding: utf-8 -*-
from .lua import LuaTable, from_py
from .api import safe_float
from . import dualsense as ds


def _num(args, i, default):
    if len(args) > i and args[i] is not None:
        return safe_float(args[i], default)
    return default


def install(rt):
    dev = rt.dualsense
    t = LuaTable()

    def color_or_log(args):
        rgb, rest = ds.split_color(args)
        if rgb is None:
            rt.log("[dualsense] cor invalida (use \"#RRGGBB\", {r,g,b} ou r, g, b)")
        return rgb, rest

    def set_color(*a):
        rgb, _ = color_or_log(a)
        return dev.set_color(rgb) if rgb is not None else False

    def get_color(*a):
        rgb = dev.color()
        if rgb is None:
            return None
        r, g, b = (float(int(round(c * 255))) for c in rgb)
        out = LuaTable()
        out.set("r", r)
        out.set("g", g)
        out.set("b", b)
        out.set("hex", ds.to_hex(rgb))
        return out

    def fade(*a):
        rgb, rest = color_or_log(a)
        return dev.fade(rgb, _num(rest, 0, 1.0)) if rgb is not None else False

    def pulse(*a):
        rgb, rest = color_or_log(a)
        return dev.pulse(rgb, _num(rest, 0, 1.5)) if rgb is not None else False

    def blink(*a):
        rgb, rest = color_or_log(a)
        return dev.blink(rgb, _num(rest, 0, 0.25), _num(rest, 1, 0)) if rgb is not None else False

    def battery(*a):
        info = dev.battery()
        if info is None:
            return None
        out = LuaTable()
        out.set("level", float(info[0]))
        out.set("charging", bool(info[1]))
        return out

    t.set("isConnected", lambda *a: dev.connected())
    t.set("count", lambda *a: float(dev.count()))
    t.set("name", lambda *a: dev.name())
    t.set("refresh", lambda *a: float(dev.refresh()))
    t.set("list", lambda *a: from_py(dev.devices()))
    t.set("select", lambda index=1, *a: dev.select(safe_float(index, 1.0)))

    t.set("setColor", set_color)
    t.set("setLed", set_color)
    t.set("getColor", get_color)
    t.set("off", lambda *a: dev.off())
    t.set("setBrightness", lambda v=1.0, *a: dev.set_brightness(v))
    t.set("getBrightness", lambda *a: float(dev.brightness()))
    t.set("setPlayer", lambda n=0, *a: dev.set_player(n))
    t.set("getPlayer", lambda *a: float(dev.player()))

    t.set("fade", fade)
    t.set("pulse", pulse)
    t.set("blink", blink)
    t.set("rainbow", lambda period=4.0, *a: dev.rainbow(safe_float(period, 4.0)))
    t.set("stopEffect", lambda *a: dev.stop_effect())
    t.set("effect", lambda *a: dev.effect())

    t.set("vibrate", lambda duration=0.3, strength=1.0, *a: dev.vibrate(safe_float(duration, 0.3), safe_float(strength, 1.0)))
    t.set("rumble", lambda low=1.0, high=1.0, duration=0.3, *a: dev.rumble(safe_float(low, 1.0), safe_float(high, 1.0), safe_float(duration, 0.3)))
    def pattern(durations=None, strengths=None, loop=False, *a):
        if not isinstance(durations, LuaTable):
            return False
        times = [safe_float(x) for x in durations.ipairs_list()]
        amps = [safe_float(x) for x in strengths.ipairs_list()] if isinstance(strengths, LuaTable) else []
        return dev.pattern(times, amps, bool(loop))
    t.set("pattern", pattern)
    t.set("stopVibration", lambda *a: dev.stop_vibration())
    t.set("battery", battery)
    return t

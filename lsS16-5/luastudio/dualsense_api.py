# -*- coding: utf-8 -*-
from .lua import LuaTable, from_py, to_py
from .api import safe_float
from . import dualsense as ds
from . import dualsense_triggers as dt


def _num(args, i, default):
    if len(args) > i and args[i] is not None:
        return safe_float(args[i], default)
    return default


def _py_args(rest):
    args, kwargs = [], {}
    for value in rest:
        if isinstance(value, LuaTable):
            named = dict((k, to_py(v)) for k, v in value.items() if isinstance(k, str))
            if named:
                kwargs.update(named)
            else:
                args.append([to_py(v) for v in value.ipairs_list()])
        else:
            args.append(value)
    return args, kwargs


def _opts(table):
    if not isinstance(table, LuaTable):
        return {}
    return dict((str(k).lower(), to_py(v)) for k, v in table.items() if isinstance(k, str))


def _step_dict(table):
    return dict((k, to_py(v)) for k, v in table.items() if isinstance(k, str))


def install_triggers(rt):
    trig = rt.dualsense_triggers
    t = LuaTable()

    def guard(fn):
        def run(*a):
            try:
                return fn(*a)
            except (ValueError, TypeError) as e:
                rt.log("[dualsense.trigger] %s" % e)
                return False
        return run

    def effect_fn(name):
        def run(side=None, *rest):
            args, kwargs = _py_args(rest)
            return trig.set(side, name, *args, **kwargs)
        return guard(run)

    for name in ("rigid", "feedback", "wall", "zones", "slope", "spring", "detent", "ratchet",
                 "weapon", "bow", "gallop", "machine", "vibration", "raw"):
        t.set(name, effect_fn(name))
    t.set("vibrationZones", effect_fn("vibration_zones"))

    def set_effect(side=None, name=None, *rest):
        args, kwargs = _py_args(rest)
        return trig.set(side, name, *args, **kwargs)

    def hold(side=None, seconds=0.2, name=None, *rest):
        args, kwargs = _py_args(rest)
        return trig.hold(side, safe_float(seconds, 0.2), name, *args, **kwargs)

    def ramp(side=None, seconds=1.0, name=None, params=None, options=None, *rest):
        o = _opts(options)
        kwargs = _step_dict(params) if isinstance(params, LuaTable) else {}
        return trig.ramp(side, name, safe_float(seconds, 1.0), o.get("easing", "linear"),
                         bool(o.get("loop", False)), int(safe_float(o.get("times", 0))), **kwargs)

    def sequence(side=None, steps=None, options=None, *rest):
        if not isinstance(steps, LuaTable):
            raise ValueError("sequence precisa de uma lista de passos")
        o = _opts(options)
        items = [_step_dict(s) for s in steps.ipairs_list() if isinstance(s, LuaTable)]
        seq = dt.Sequence(items, bool(o.get("loop", False)), int(safe_float(o.get("times", 0))),
                          None if o.get("final", "off") in ("off", None) else o["final"])
        return trig.play(side, seq)

    def preset(side=None, name=None, intensity=1.0, *rest):
        return trig.preset(side, name, safe_float(intensity, 1.0))

    def off(side=None, *rest):
        return trig.off(side)

    def effect(side="R2", *rest):
        return trig.effect(side).hex()

    def status(*a):
        return from_py(trig.status())

    def set_color(*a):
        rgb, _ = ds.split_color(a)
        if rgb is None:
            rt.log("[dualsense.trigger] cor invalida")
            return False
        return trig.lightbar(rgb)

    t.set("connect", guard(lambda *a: trig.connect()))
    t.set("disconnect", guard(lambda *a: trig.disconnect()))
    t.set("isConnected", lambda *a: trig.connected)
    t.set("state", lambda *a: trig.state)
    t.set("status", status)
    t.set("set", guard(set_effect))
    t.set("hold", guard(hold))
    t.set("ramp", guard(ramp))
    t.set("sequence", guard(sequence))
    t.set("preset", guard(preset))
    t.set("presets", lambda *a: from_py(dt.preset_names()))
    t.set("effects", lambda *a: from_py(dt.effect_names()))
    t.set("off", guard(off))
    t.set("stop", guard(off))
    t.set("isPlaying", guard(lambda side="R2", *a: trig.playing(side)))
    t.set("effect", guard(effect))
    t.set("rumble", guard(lambda low=0.0, high=None, *a: trig.rumble(safe_float(low), None if high is None else safe_float(high))))
    t.set("setColor", guard(set_color))
    t.set("setPlayer", guard(lambda n=0, *a: trig.player(safe_float(n))))
    return t


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
    t.set("trigger", install_triggers(rt))
    t.set("triggers", t.get("trigger"))
    return t

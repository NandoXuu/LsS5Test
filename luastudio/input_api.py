# -*- coding: utf-8 -*-
"""API Lua do sistema de entrada (ver inputs.py pra logica).

input.isDown/isPressed/isReleased/axis      atalhos (qualquer dispositivo)
input.bind / bindAxis / unbind              acoes ("pular" = SPACE ou pad:A)
input.keyboard.*   input.mouse.*   input.gamepad.* (alias input.controller)
"""

from .lua import LuaTable, tostring, to_py
from . import inputs as inp
from . import softkeyboard as softkb


def _pid(a):
    if a and isinstance(a[0], (int, float)) and not isinstance(a[0], bool):
        return int(a[0]), tuple(a[1:])
    return None, tuple(a)


def _arg(rest, i, default=None):
    return rest[i] if len(rest) > i and rest[i] is not None else default


def _num(v, default=0.0):
    try:
        f = float(v)
        return f if f == f else default
    except Exception:
        return default


def _tbl(**kv):
    t = LuaTable()
    for k, v in kv.items():
        t.set(k, v)
    return t


def _flat(args):
    out = []
    for a in args:
        if a is None:
            continue
        if isinstance(a, LuaTable):
            v = to_py(a)
            seq = v if isinstance(v, list) else list(v.values()) if isinstance(v, dict) else []
            out.extend(tostring(x) for x in seq if x is not None)
        else:
            out.append(tostring(a))
    return out


def _sticks(which):
    w = str(which if which is not None else "BOTH").strip().upper()
    if w in ("BOTH", "ALL", ""):
        return ["LEFT", "RIGHT"]
    return ["RIGHT" if w.startswith("R") else "LEFT"]


def install(rt, input_t):
    mgr = rt.input

    # ------------------------------------------------ atalhos genericos
    input_t.set("isDown", lambda name=None: mgr.query(tostring(name), 0))
    input_t.set("isPressed", lambda name=None: mgr.query(tostring(name), 1))
    input_t.set("isReleased", lambda name=None: mgr.query(tostring(name), 2))
    input_t.set("axis", lambda name=None: float(mgr.axis_value(tostring(name))))

    def _bind(action=None, *sources):
        if action is None:
            return False
        mgr.bind(tostring(action), _flat(sources))
        return True
    input_t.set("bind", _bind)

    def _bind_axis(name=None, neg=None, pos=None, pad_axis=None):
        if name is None:
            return False
        mgr.bind_axis(tostring(name), _flat([neg]), _flat([pos]),
                      tostring(pad_axis) if pad_axis is not None else None)
        return True
    input_t.set("bindAxis", _bind_axis)
    input_t.set("unbind", lambda name=None: mgr.unbind(tostring(name)) if name is not None else None)

    # ------------------------------------------------------- teclado
    kb = LuaTable()
    kb.set("isDown", lambda name=None: mgr._kq(name, 0))
    kb.set("isPressed", lambda name=None: mgr._kq(name, 1))
    kb.set("isReleased", lambda name=None: mgr._kq(name, 2))
    kb.set("lastKey", lambda *a: mgr.last_key)

    def _on_key(fn=None):
        if fn is not None:
            rt.key_handlers.append(fn)
    kb.set("onKey", _on_key)
    kb.set("isTyping", lambda *a: bool(rt.typing_probe()))
    kb.set("hasHardware", lambda *a: bool(softkb.has_hardware_keyboard(True)))
    kb.set("hideVirtual", lambda *a: softkb.hide_virtual())

    def _set_virtual(m=None):
        if not softkb.set_mode(m):
            rt.log("[input] modo de teclado virtual invalido: use auto, always ou never")
            return False
        return True
    kb.set("setVirtual", _set_virtual)
    kb.set("getVirtual", lambda *a: softkb.mode())
    input_t.set("keyboard", kb)

    # --------------------------------------------------------- mouse
    ms = LuaTable()
    ms.set("position", input_t.get("mousePosition"))
    ms.set("isDown", lambda btn=1: mgr._mq(btn, 0))
    ms.set("isPressed", lambda btn=1: mgr._mq(btn, 1))
    ms.set("isReleased", lambda btn=1: mgr._mq(btn, 2))
    input_t.set("mouse", ms)

    # ------------------------------------------------------- gamepad
    gp = LuaTable()

    gp.set("count", lambda *a: float(len(mgr.targets())))

    def _is_connected(*a):
        pid, _ = _pid(a)
        return any(p.connected for p in mgr.targets(pid))
    gp.set("isConnected", _is_connected)

    def _name(*a):
        pid, _ = _pid(a)
        p = mgr.first_pad(pid)
        return p.name if p else ""
    gp.set("name", _name)

    def _guid(*a):
        pid, _ = _pid(a)
        p = mgr.first_pad(pid)
        return p.guid if p else ""
    gp.set("guid", _guid)

    def _profile(*a):
        pid, _ = _pid(a)
        p = mgr.first_pad(pid)
        return p.profile if p else mgr.default_profile
    gp.set("profile", _profile)

    def _set_profile(*a):
        pid, rest = _pid(a)
        prof = str(_arg(rest, 0, "")).strip().lower()
        if prof not in inp.PROFILES:
            rt.log("[input] perfil '%s' desconhecido (use android, xbox, playstation)" % prof)
            return False

        def apply(p):
            p.profile = prof
            p.reset_config()
        mgr.configure(pid, apply)
        return True
    gp.set("setProfile", _set_profile)

    def _map(*a):
        pid, rest = _pid(a)
        n = inp.canon_button(_arg(rest, 0))
        if n is None:
            return False
        raw = int(_num(_arg(rest, 1), 0))

        def apply(p):
            p.btn_over[n] = raw
            p.invalidate()
        mgr.configure(pid, apply)
        return True
    gp.set("map", _map)

    def _map_axis(*a):
        pid, rest = _pid(a)
        n = inp.canon_axis(_arg(rest, 0))
        if n is None:
            return False
        raw = int(_num(_arg(rest, 1), 0))

        def apply(p):
            p.axis_over[n] = raw
        mgr.configure(pid, apply)
        return True
    gp.set("mapAxis", _map_axis)

    def _reset_map(*a):
        pid, _ = _pid(a)

        def apply(p):
            p.btn_over.clear()
            p.axis_over.clear()
            p.invalidate()
        mgr.configure(pid, apply)
    gp.set("resetMap", _reset_map)

    def _btn(kind):
        def fn(*a):
            pid, rest = _pid(a)
            return mgr._pq(pid, _arg(rest, 0, ""), kind)
        return fn
    gp.set("isDown", _btn(0))
    gp.set("isPressed", _btn(1))
    gp.set("isReleased", _btn(2))

    def _last_button(*a):
        pid, _ = _pid(a)
        return mgr.pad_last_button(pid)
    gp.set("lastButton", _last_button)

    def _axis(*a):
        pid, rest = _pid(a)
        return float(mgr.pad_axis(pid, _arg(rest, 0, "")))
    gp.set("axis", _axis)

    def _stick(*a):
        pid, rest = _pid(a)
        x, y, m, ang = mgr.pad_stick(pid, _arg(rest, 0, "LEFT"))
        return _tbl(x=float(x), y=float(y), magnitude=float(m), angle=float(ang))
    gp.set("stick", _stick)

    def _trigger(*a):
        pid, rest = _pid(a)
        return float(mgr.pad_trigger(pid, _arg(rest, 0, "LT")))
    gp.set("trigger", _trigger)

    def _dpad(*a):
        pid, _ = _pid(a)
        x, y = mgr.pad_dpad(pid)
        return _tbl(x=float(x), y=float(y))
    gp.set("dpad", _dpad)

    # --- deadzone / curva / limiar dos gatilhos
    def _set_dz(*a):
        pid, rest = _pid(a)
        val = max(0.0, min(0.95, _num(_arg(rest, 1), 0.15)))
        mode = _arg(rest, 2)
        m = str(mode).strip().lower() if mode is not None else None
        sticks = _sticks(_arg(rest, 0))

        def apply(p):
            for w in sticks:
                p.dz[w] = val
                if m in ("none", "axial", "radial"):
                    p.dz_mode[w] = m
        mgr.configure(pid, apply)
    gp.set("setDeadzone", _set_dz)

    def _get_dz(*a):
        pid, rest = _pid(a)
        p = mgr.first_pad(pid) or mgr.first_pad()
        return float(p.dz[_sticks(_arg(rest, 0, "LEFT"))[0]]) if p else 0.15
    gp.set("getDeadzone", _get_dz)

    def _set_dz_mode(*a):
        pid, rest = _pid(a)
        m = str(_arg(rest, 1, "radial")).strip().lower()
        if m not in ("none", "axial", "radial"):
            rt.log("[input] modo de deadzone invalido: use none, axial ou radial")
            return False
        sticks = _sticks(_arg(rest, 0))

        def apply(p):
            for w in sticks:
                p.dz_mode[w] = m
        mgr.configure(pid, apply)
        return True
    gp.set("setDeadzoneMode", _set_dz_mode)

    def _get_dz_mode(*a):
        pid, rest = _pid(a)
        p = mgr.first_pad(pid) or mgr.first_pad()
        return p.dz_mode[_sticks(_arg(rest, 0, "LEFT"))[0]] if p else "radial"
    gp.set("getDeadzoneMode", _get_dz_mode)

    def _set_curve(*a):
        pid, rest = _pid(a)
        val = max(0.1, min(8.0, _num(_arg(rest, 1), 1.0)))
        sticks = _sticks(_arg(rest, 0))

        def apply(p):
            for w in sticks:
                p.curve[w] = val
        mgr.configure(pid, apply)
    gp.set("setCurve", _set_curve)

    def _get_curve(*a):
        pid, rest = _pid(a)
        p = mgr.first_pad(pid) or mgr.first_pad()
        return float(p.curve[_sticks(_arg(rest, 0, "LEFT"))[0]]) if p else 1.0
    gp.set("getCurve", _get_curve)

    def _set_thr(*a):
        pid, rest = _pid(a)
        val = max(0.05, min(0.95, _num(_arg(rest, 0), 0.35)))

        def apply(p):
            p.trig_threshold = val
        mgr.configure(pid, apply)
    gp.set("setTriggerThreshold", _set_thr)

    def _get_thr(*a):
        pid, _ = _pid(a)
        p = mgr.first_pad(pid) or mgr.first_pad()
        return float(p.trig_threshold) if p else 0.35
    gp.set("getTriggerThreshold", _get_thr)

    # --- cru (pra descobrir/mapear indices do SEU controle)
    def _raw_button(*a):
        pid, rest = _pid(a)
        return mgr.pad_raw_button(pid, int(_num(_arg(rest, 0), -1)))
    gp.set("rawButton", _raw_button)

    def _raw_axis(*a):
        pid, rest = _pid(a)
        return float(mgr.pad_raw_axis(pid, int(_num(_arg(rest, 0), -1))))
    gp.set("rawAxis", _raw_axis)

    def _last_raw(*a):
        r = mgr.last_raw
        if not r:
            return None
        return _tbl(type=r["type"], pad=float(r["pad"]), id=float(r["id"]), value=float(r["value"]))
    gp.set("lastRaw", _last_raw)

    # --- eventos
    def _on_button(fn=None):
        if fn is not None:
            rt.pad_button_handlers.append(fn)
    gp.set("onButton", _on_button)

    def _on_connect(fn=None):
        if fn is not None:
            rt.pad_connect_handlers.append(fn)
    gp.set("onConnect", _on_connect)

    input_t.set("gamepad", gp)
    input_t.set("controller", gp)

# -*- coding: utf-8 -*-
"""Entrada unificada: teclado, mouse (bordas) e gamepads.

Sem dependencia de Kivy aqui (so a ponte KivyBridge, no fim, que recebe a
Window pronta) - da pra testar tudo sem janela.

Convencoes:
- Y cresce pra BAIXO, igual as coordenadas da tela do LuaStudio: stick pra
  cima = -1 e D-Pad pra cima = -1.
- isPressed/isReleased valem so no frame em que o evento aconteceu
  (limpos por end_frame(), chamado no fim de Runtime.update).
"""

import math
from collections import deque

HAT_UP_IS_POSITIVE = True   # Kivy: hat (x, y) com y=+1 pra cima

# ------------------------------------------------------------- teclado
KEY_ALIASES = {
    "ESC": "ESCAPE", "RETURN": "ENTER", "SPACEBAR": "SPACE", "DEL": "DELETE",
    "BKSP": "BACKSPACE", "PGUP": "PAGEUP", "PGDN": "PAGEDOWN",
    "ARROWUP": "UP", "ARROWDOWN": "DOWN", "ARROWLEFT": "LEFT",
    "ARROWRIGHT": "RIGHT", "CONTROL": "CTRL", "LCONTROL": "LCTRL",
    "RCONTROL": "RCTRL", "CAPS": "CAPSLOCK",
}
KEY_GROUPS = {"SHIFT": ("LSHIFT", "RSHIFT"), "CTRL": ("LCTRL", "RCTRL"),
              "ALT": ("LALT", "RALT")}


def _fallback_keys():
    d = {}
    for c in range(97, 123):
        d[c] = chr(c).upper()
    for c in range(48, 58):
        d[c] = chr(c)
    d.update({
        32: "SPACE", 13: "ENTER", 271: "ENTER", 27: "ESCAPE", 9: "TAB",
        8: "BACKSPACE", 127: "DELETE", 273: "UP", 274: "DOWN", 275: "RIGHT",
        276: "LEFT", 277: "INSERT", 278: "HOME", 279: "END", 280: "PAGEUP",
        281: "PAGEDOWN", 304: "LSHIFT", 303: "RSHIFT", 306: "LCTRL",
        305: "RCTRL", 308: "LALT", 307: "RALT", 301: "CAPSLOCK",
        300: "NUMLOCK", 44: "COMMA", 46: "PERIOD", 45: "MINUS",
        61: "EQUALS", 47: "SLASH", 59: "SEMICOLON", 39: "QUOTE",
        91: "LBRACKET", 93: "RBRACKET", 92: "BACKSLASH", 96: "BACKQUOTE",
    })
    for i in range(12):
        d[282 + i] = "F%d" % (i + 1)
    for i in range(10):
        d[256 + i] = "NUMPAD%d" % i
    return d


def canon_key(name):
    if name == " ":
        return "SPACE"
    s = str(name if name is not None else "").strip().upper().replace(" ", "")
    return KEY_ALIASES.get(s, s)


# ------------------------------------------------------------- gamepad
BUTTON_ALIASES = {
    "CROSS": "A", "CIRCLE": "B", "SQUARE": "X", "TRIANGLE": "Y",
    "L1": "LB", "R1": "RB", "L2": "LT", "R2": "RT", "L3": "LS", "R3": "RS",
    "OPTIONS": "START", "MENU": "START", "BACK": "SELECT", "SHARE": "SELECT",
    "CREATE": "SELECT", "PS": "HOME", "GUIDE": "HOME",
    "UP": "DPAD_UP", "DOWN": "DPAD_DOWN", "LEFT": "DPAD_LEFT", "RIGHT": "DPAD_RIGHT",
}
BUTTON_NAMES = ("A", "B", "X", "Y", "LB", "RB", "LT", "RT", "LS", "RS",
                "START", "SELECT", "HOME",
                "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT")
AXIS_ALIASES = {"LX": "LEFT_X", "LY": "LEFT_Y", "RX": "RIGHT_X", "RY": "RIGHT_Y"}
AXIS_NAMES = ("LEFT_X", "LEFT_Y", "RIGHT_X", "RIGHT_Y", "LT", "RT")
STICK_AXES = {"LEFT": ("LEFT_X", "LEFT_Y"), "RIGHT": ("RIGHT_X", "RIGHT_Y")}

# Indices crus do SDL por perfil. Sao um PALPITE razoavel (variam por
# controle/SO) - o jogador/dev ajusta com input.gamepad.map / mapAxis.
PROFILES = {
    # Android (SDL joystick usa a ordem do enum de botoes do SDL)
    "android": ({"A": 0, "B": 1, "X": 2, "Y": 3, "SELECT": 4, "HOME": 5,
                 "START": 6, "LS": 7, "RS": 8, "LB": 9, "RB": 10,
                 "DPAD_UP": 11, "DPAD_DOWN": 12, "DPAD_LEFT": 13, "DPAD_RIGHT": 14},
                {"LEFT_X": 0, "LEFT_Y": 1, "RIGHT_X": 2, "RIGHT_Y": 3, "LT": 4, "RT": 5}),
    # Xbox em Linux/Windows
    "xbox": ({"A": 0, "B": 1, "X": 2, "Y": 3, "LB": 4, "RB": 5, "SELECT": 6,
              "START": 7, "HOME": 8, "LS": 9, "RS": 10},
             {"LEFT_X": 0, "LEFT_Y": 1, "LT": 2, "RIGHT_X": 3, "RIGHT_Y": 4, "RT": 5}),
    # DualShock/DualSense em Linux (L2/R2 tambem chegam como botoes 6/7)
    "playstation": ({"A": 0, "B": 1, "Y": 2, "X": 3, "LB": 4, "RB": 5, "LT": 6,
                     "RT": 7, "SELECT": 8, "START": 9, "HOME": 10, "LS": 11, "RS": 12},
                    {"LEFT_X": 0, "LEFT_Y": 1, "LT": 2, "RIGHT_X": 3, "RIGHT_Y": 4, "RT": 5}),
}
PROFILES["generic"] = PROFILES["xbox"]


def canon_button(name):
    s = str(name if name is not None else "").strip().upper().replace(" ", "")
    s = BUTTON_ALIASES.get(s, s)
    return s if s in BUTTON_NAMES else None


def canon_axis(name):
    s = str(name if name is not None else "").strip().upper().replace(" ", "")
    s = AXIS_ALIASES.get(s, s)
    if s in ("L2",):
        s = "LT"
    if s in ("R2",):
        s = "RT"
    return s if s in AXIS_NAMES else None


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def norm_axis(value):
    """Kivy/SDL manda o eixo cru (-32768..32767) em algumas versoes e
    -1..1 em outras: aceita os dois."""
    try:
        v = float(value)
    except Exception:
        return 0.0
    if v != v:
        return 0.0
    if isinstance(value, int) and not isinstance(value, bool):
        v = v / 32767.0
    elif abs(v) > 1.5:
        v = v / 32767.0
    return _clamp(v, -1.0, 1.0)


class Pad(object):
    def __init__(self, mgr, pid, profile):
        self.mgr = mgr
        self.id = pid
        self.profile = profile
        self.name = "Gamepad %d" % pid
        self.guid = ""
        self.btn_over = {}
        self.axis_over = {}
        self._rev = None
        self.raw_buttons = set()
        self.raw_axes = {}
        self.hat = (0, 0)
        self.src = {}
        self.down = set()
        self.pressed = set()
        self.released = set()
        self.trig = {"LT": 0.0, "RT": 0.0}
        self.trig_signed = {"LT": False, "RT": False}
        self.trig_axis_seen = {"LT": False, "RT": False}
        self.trig_threshold = 0.35
        self.dz = {"LEFT": 0.15, "RIGHT": 0.15}
        self.dz_mode = {"LEFT": "radial", "RIGHT": "radial"}
        self.curve = {"LEFT": 1.0, "RIGHT": 1.0}
        self.last_button = None
        self.last_seq = 0
        self.connected = False

    def mark_connected(self):
        if not self.connected:
            self.connected = True
            self.mgr._emit("pad_connect", self.id)

    def reset_config(self):
        self.btn_over.clear()
        self.axis_over.clear()
        self._rev = None
        self.trig_threshold = 0.35
        self.dz = {"LEFT": 0.15, "RIGHT": 0.15}
        self.dz_mode = {"LEFT": "radial", "RIGHT": "radial"}
        self.curve = {"LEFT": 1.0, "RIGHT": 1.0}

    # --- mapa
    def buttons_map(self):
        m = dict(PROFILES.get(self.profile, PROFILES["xbox"])[0])
        m.update(self.btn_over)
        return m

    def axes_map(self):
        m = dict(PROFILES.get(self.profile, PROFILES["xbox"])[1])
        m.update(self.axis_over)
        return m

    def reverse(self):
        if self._rev is None:
            rev = {}
            for name, raw in self.buttons_map().items():
                rev.setdefault(raw, []).append(name)
            self._rev = rev
        return self._rev

    def invalidate(self):
        self._rev = None

    # --- estado logico (bordas)
    def _set(self, name, source, on):
        s = self.src.setdefault(name, set())
        if on:
            s.add(source)
        else:
            s.discard(source)
        now = bool(s)
        was = name in self.down
        if now and not was:
            self.down.add(name)
            self.pressed.add(name)
            self.last_button = name
            self.mgr.seq += 1
            self.last_seq = self.mgr.seq
            self.mgr._emit("pad_button", self.id, name, True)
        elif was and not now:
            self.down.discard(name)
            self.released.add(name)
            self.mgr._emit("pad_button", self.id, name, False)

    def raw_button(self, raw, on):
        raw = int(raw)
        if on:
            self.raw_buttons.add(raw)
        else:
            self.raw_buttons.discard(raw)
        self.mgr.last_raw = {"type": "button", "pad": self.id, "id": raw, "value": 1.0 if on else 0.0}
        for name in self.reverse().get(raw, ()):
            self._set(name, "b", on)

    def native_button(self, name, on, code):
        if on:
            self.raw_buttons.add(code)
        else:
            self.raw_buttons.discard(code)
        self.mgr.last_raw = {"type": "key", "pad": self.id, "id": code, "value": 1.0 if on else 0.0}
        if name in ("LT", "RT") and not self.trig_axis_seen[name]:
            self.trig[name] = 1.0 if on else 0.0
        self._set(name, "k", on)

    def raw_hat_event(self, x, y):
        x = int(_clamp(x or 0, -1, 1))
        y = int(_clamp(y or 0, -1, 1))
        self.hat = (x, y)
        self.mgr.last_raw = {"type": "hat", "pad": self.id, "id": 0, "value": float(x * 10 + y)}
        up = y > 0 if HAT_UP_IS_POSITIVE else y < 0
        dn = y < 0 if HAT_UP_IS_POSITIVE else y > 0
        self._set("DPAD_UP", "h", up)
        self._set("DPAD_DOWN", "h", dn)
        self._set("DPAD_LEFT", "h", x < 0)
        self._set("DPAD_RIGHT", "h", x > 0)

    def raw_axis_event(self, idx, value):
        # Kivy/SDL usually reports numeric axis indices, but some backends
        # expose named axes. Preserve the raw identifier and normalize both.
        aliases = {
            "LEFTX": 0, "LEFT_X": 0, "X": 0, "LX": 0,
            "LEFTY": 1, "LEFT_Y": 1, "Y": 1, "LY": 1,
            "RIGHTX": 2, "RIGHT_X": 2, "RX": 2,
            "RIGHTY": 3, "RIGHT_Y": 3, "RY": 3,
            "LTRIGGER": 4, "LEFTTRIGGER": 4, "LT": 4,
            "RTRIGGER": 5, "RIGHTTRIGGER": 5, "RT": 5,
        }
        raw_idx = idx
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            key = str(idx).strip().upper().replace(" ", "")
            if key not in aliases:
                self.mgr.last_raw = {"type": "axis", "pad": self.id,
                                     "id": str(raw_idx), "value": norm_axis(value)}
                return
            idx = aliases[key]
        v = norm_axis(value)
        self.raw_axes[idx] = v
        self.mgr.last_raw = {"type": "axis", "pad": self.id, "id": idx, "value": v}
        for t, aidx in self.axes_map().items():
            if t in ("LT", "RT") and aidx == idx:
                self.trig_axis_seen[t] = True
                if v < -0.05:
                    self.trig_signed[t] = True
                tv = (v + 1.0) / 2.0 if self.trig_signed[t] else max(0.0, v)
                self.trig[t] = _clamp(tv, 0.0, 1.0)
                thr = self.trig_threshold
                if self.trig[t] >= thr:
                    self._set(t, "t", True)
                elif self.trig[t] < thr * 0.6:
                    self._set(t, "t", False)

    # --- consultas
    def stick(self, which):
        which = "RIGHT" if str(which).upper().startswith("R") else "LEFT"
        ax, ay = STICK_AXES[which]
        am = self.axes_map()
        x = self.raw_axes.get(am.get(ax, -1), 0.0)
        y = self.raw_axes.get(am.get(ay, -1), 0.0)
        dz = self.dz[which]
        mode = self.dz_mode[which]
        c = self.curve[which]
        if mode == "radial":
            raw_m = math.hypot(x, y)
            if raw_m < dz or raw_m == 0.0:
                return 0.0, 0.0, 0.0, 0.0
            s = _clamp((min(raw_m, 1.0) - dz) / (1.0 - dz), 0.0, 1.0)
            s = s ** c
            ox, oy = x / raw_m * s, y / raw_m * s
        else:
            def one(v):
                if mode == "axial":
                    a = abs(v)
                    if a < dz:
                        return 0.0
                    a = _clamp((a - dz) / (1.0 - dz), 0.0, 1.0)
                else:
                    a = abs(v)
                return math.copysign(a ** c, v)
            ox, oy = one(x), one(y)
        mag = min(1.0, math.hypot(ox, oy))
        ang = math.degrees(math.atan2(oy, ox)) % 360.0 if mag > 0 else 0.0
        return ox, oy, mag, ang

    def axis(self, name):
        a = canon_axis(name)
        if a is None:
            return 0.0
        if a in ("LT", "RT"):
            return self.trig[a]
        which = "LEFT" if a.startswith("LEFT") else "RIGHT"
        x, y, _m, _a = self.stick(which)
        return x if a.endswith("_X") else y

    def dpad(self):
        x = (1 if "DPAD_RIGHT" in self.down else 0) - (1 if "DPAD_LEFT" in self.down else 0)
        y = (1 if "DPAD_DOWN" in self.down else 0) - (1 if "DPAD_UP" in self.down else 0)
        return x, y

    def end_frame(self):
        self.pressed.clear()
        self.released.clear()

    def reset_state(self):
        self.raw_buttons.clear()
        self.raw_axes.clear()
        self.hat = (0, 0)
        self.src.clear()
        self.down.clear()
        self.end_frame()
        self.trig = {"LT": 0.0, "RT": 0.0}


class InputManager(object):
    def __init__(self, log=None, android=False):
        self.log = log or (lambda s: None)
        self.default_profile = "android" if android else "xbox"
        self.keymap = _fallback_keys()
        self.keys_down = set()
        self.keys_pressed = set()
        self.keys_released = set()
        self.last_key = None
        self.mouse_down_set = set()
        self.mouse_pressed = set()
        self.mouse_released = set()
        self.pads = {}
        self.actions = {}
        self.axis_actions = {}
        self.listeners = []
        self.last_raw = None
        self.native_queue = deque()
        self.native_buttons = False
        self.slots = {}
        self.cfg_ops = []
        self.seq = 0

    # --- util
    def _emit(self, kind, *args):
        for fn in list(self.listeners):
            try:
                fn(kind, *args)
            except Exception as ex:  # noqa
                self.log("[input] erro no listener: %s: %s" % (type(ex).__name__, ex))

    def add_keycodes(self, mapping):
        """mapping: codigo -> nome (ex.: vindo do Keyboard.keycodes do Kivy)."""
        for code, name in mapping.items():
            if code not in self.keymap:
                self.keymap[code] = canon_key(name)

    def key_name(self, code):
        return self.keymap.get(code) or "KEY_%s" % code

    # --- teclado
    def key_down(self, name):
        name = canon_key(name)
        if not name or name in self.keys_down:
            return False
        self.keys_down.add(name)
        self.keys_pressed.add(name)
        self.last_key = name
        return True

    def key_up(self, name):
        name = canon_key(name)
        if name in self.keys_down:
            self.keys_down.discard(name)
            self.keys_released.add(name)
            return True
        return False

    def _kq(self, name, kind):
        n = canon_key(name)
        names = KEY_GROUPS.get(n, (n,))
        src = (self.keys_down, self.keys_pressed, self.keys_released)[kind]
        return any(x in src for x in names)

    # --- mouse
    @staticmethod
    def _mname(btn):
        if isinstance(btn, str):
            b = btn.strip().lower()
            return b.replace("mouse_", "") or "left"
        try:
            return {1: "left", 2: "right", 3: "middle"}.get(int(btn), "left")
        except Exception:
            return "left"

    def mouse_press(self, btn):
        b = self._mname(btn)
        if b not in self.mouse_down_set:
            self.mouse_down_set.add(b)
            self.mouse_pressed.add(b)

    def mouse_release(self, btn):
        b = self._mname(btn)
        if b in self.mouse_down_set:
            self.mouse_down_set.discard(b)
            self.mouse_released.add(b)

    def _mq(self, btn, kind):
        src = (self.mouse_down_set, self.mouse_pressed, self.mouse_released)[kind]
        return self._mname(btn) in src

    # --- gamepads
    def pad(self, pid, create=True, real=False):
        pid = int(pid)
        p = self.pads.get(pid)
        if p is None and create:
            p = Pad(self, pid, self.default_profile)
            self.pads[pid] = p
            for fn in list(self.cfg_ops):
                fn(p)
        if p is not None and real:
            p.mark_connected()
        return p

    def _joy_pad(self, ext):
        slot = self.slots.get(ext)
        if slot is None:
            used = set(self.slots.values())
            slot = next(i for i in range(256) if i not in used)
            self.slots[ext] = slot
        return self.pad(slot, real=True)

    def targets(self, pid=None):
        if pid is None:
            return sorted((p for p in self.pads.values() if p.connected), key=lambda p: p.id)
        p = self.pads.get(int(pid))
        return [p] if p is not None else []

    def first_pad(self, pid=None):
        t = self.targets(pid)
        return t[0] if t else None

    def configure(self, pid, fn):
        if pid is None:
            self.cfg_ops.append(fn)
            for p in list(self.pads.values()):
                fn(p)
        else:
            fn(self.pad(pid))

    def pad_stick(self, pid, which):
        best = (0.0, 0.0, 0.0, 0.0)
        for p in self.targets(pid):
            s = p.stick(which)
            if s[2] > best[2]:
                best = s
        return best

    def pad_axis(self, pid, name):
        best = 0.0
        for p in self.targets(pid):
            v = p.axis(name)
            if abs(v) > abs(best):
                best = v
        return best

    def pad_trigger(self, pid, name):
        n = canon_axis(name)
        if n not in ("LT", "RT"):
            return 0.0
        return max([p.trig[n] for p in self.targets(pid)] or [0.0])

    def pad_dpad(self, pid):
        x = y = 0
        for p in self.targets(pid):
            dx, dy = p.dpad()
            x += dx
            y += dy
        return int(_clamp(x, -1, 1)), int(_clamp(y, -1, 1))

    def pad_last_button(self, pid):
        best = None
        for p in self.targets(pid):
            if p.last_button is not None and (best is None or p.last_seq > best.last_seq):
                best = p
        return best.last_button if best is not None else None

    def pad_raw_button(self, pid, idx):
        return any(idx in p.raw_buttons for p in self.targets(pid))

    def pad_raw_axis(self, pid, idx):
        best = 0.0
        for p in self.targets(pid):
            v = p.raw_axes.get(idx, 0.0)
            if abs(v) > abs(best):
                best = v
        return best

    def push_native(self, item):
        self.native_queue.append(item)

    def drain_native(self, dt=0.0):
        queue = self.native_queue
        while queue:
            pid, name, on, code, label = queue.popleft()
            p = self.pad(pid, real=True)
            if label and p.name == "Gamepad %d" % pid:
                p.name = label
            if name is not None:
                p.native_button(name, on, code)

    def joy_button(self, pid, raw, on):
        self._joy_pad(pid).raw_button(raw, on)

    def joy_axis(self, pid, idx, value):
        self._joy_pad(pid).raw_axis_event(idx, value)

    def joy_hat(self, pid, hat, value):
        try:
            x, y = value
        except Exception:
            x, y = 0, 0
        self._joy_pad(pid).raw_hat_event(x, y)

    def _pq(self, pid, name, kind):
        n = canon_button(name)
        if n is None:
            return False
        return any(n in (p.down, p.pressed, p.released)[kind] for p in self.targets(pid))

    # --- acoes / consulta generica
    def bind(self, action, sources):
        self.actions[str(action)] = [str(s) for s in sources if s is not None]

    def unbind(self, action):
        self.actions.pop(str(action), None)
        self.axis_actions.pop(str(action), None)

    def bind_axis(self, name, neg, pos, pad_axis=None):
        self.axis_actions[str(name)] = {"neg": list(neg), "pos": list(pos),
                                        "pad": canon_axis(pad_axis) if pad_axis else None}

    def _src_query(self, src, kind):
        s = str(src)
        if ":" in s:
            prefix, _, rest = s.partition(":")
            prefix = prefix.strip().lower()
            if prefix in ("key", "keyboard"):
                return self._kq(rest, kind)
            if prefix in ("pad", "gamepad", "joy"):
                return self._pq(None, rest, kind)
            if prefix == "mouse":
                return self._mq(rest, kind)
        return self._query_plain(s, kind)

    def _query_plain(self, name, kind):
        if self._kq(name, kind):
            return True
        if len(str(name).strip()) == 1:
            return False      # "A", "X", "1"...: so teclado (gamepad = "pad:A")
        up = str(name).strip().upper()
        if up.startswith("MOUSE_") and self._mq(up, kind):
            return True
        if canon_button(name) is not None:
            return self._pq(None, name, kind)
        return False

    def query(self, name, kind):
        acts = self.actions.get(str(name))
        if acts is not None:
            return any(self._src_query(s, kind) for s in acts)
        return self._src_query(name, kind)

    def axis_value(self, name):
        ax = self.axis_actions.get(str(name))
        best = 0.0
        if ax is not None:
            digital = (1.0 if any(self._src_query(s, 0) for s in ax["pos"]) else 0.0) - \
                      (1.0 if any(self._src_query(s, 0) for s in ax["neg"]) else 0.0)
            best = digital
            if ax["pad"]:
                for p in self.pads.values():
                    v = p.axis(ax["pad"])
                    if abs(v) > abs(best):
                        best = v
            return _clamp(best, -1.0, 1.0)
        if canon_axis(name):
            for p in self.pads.values():
                v = p.axis(name)
                if abs(v) > abs(best):
                    best = v
        return best

    # --- ciclo
    def end_frame(self):
        self.keys_pressed.clear()
        self.keys_released.clear()
        self.mouse_pressed.clear()
        self.mouse_released.clear()
        for p in self.pads.values():
            p.end_frame()

    def reset_state(self):
        """Solta tudo (ao parar o jogo) - nao apaga mapeamentos nem acoes."""
        self.keys_down.clear()
        self.mouse_down_set.clear()
        self.last_key = None
        self.native_queue.clear()
        for p in self.pads.values():
            p.reset_state()
        self.end_frame()

    def reset_all(self):
        """Novo run de script: tira acoes/listeners de scripts anteriores."""
        self.reset_state()
        self.actions.clear()
        self.axis_actions.clear()
        self.cfg_ops = []
        for p in self.pads.values():
            p.reset_config()


# --------------------------------------------------------- ponte Kivy
class KivyBridge(object):
    """Liga os eventos da Window do Kivy no InputManager.

    `runtime` so e usado pra saber se o jogo esta rodando e pra resetar o
    orcamento de instrucoes antes de rodar callbacks Lua.
    `text_focused()` diz se um TextInput esta com foco (teclado vai pra ele)."""

    def __init__(self, window, runtime, text_focused=None):
        self.window = window
        self.rt = runtime
        self.text_focused = text_focused or (lambda: False)
        self.attached = False
        self.native = None
        try:
            from .android_pad import AndroidPadBridge
            self.native = AndroidPadBridge(runtime)
        except Exception:
            self.native = None
        try:
            from kivy.core.window import Keyboard
            self.rt.input.add_keycodes({c: n for n, c in Keyboard.keycodes.items()})
        except Exception:
            pass

    def attach(self):
        if self.window is None or self.attached:
            return
        try:
            self.window.bind(on_key_down=self._key_down, on_key_up=self._key_up,
                             on_joy_button_down=self._jb_down, on_joy_button_up=self._jb_up,
                             on_joy_axis=self._jaxis, on_joy_hat=self._jhat)
            self.attached = True
        except Exception as ex:
            self.rt.log("[input] nao consegui ligar teclado/gamepad: %s" % ex)
        # Use Kivy/SDL as the single source for gamepad buttons and axes.
        # AndroidPadBridge's View.OnKeyListener can replace SDL's own listener
        # and silently swallow controller buttons on some SDLActivity builds.
        # Keep the bridge available for future device-specific integrations,
        # but do not install it over the active SDL surface here.

    def detach(self):
        if self.native is not None:
            self.native.detach()
        if self.window is None or not self.attached:
            return
        try:
            self.window.unbind(on_key_down=self._key_down, on_key_up=self._key_up,
                               on_joy_button_down=self._jb_down, on_joy_button_up=self._jb_up,
                               on_joy_axis=self._jaxis, on_joy_hat=self._jhat)
        except Exception:
            pass
        self.attached = False

    def _live(self):
        return bool(getattr(self.rt, "running", False))

    def _key_down(self, _w, key, scancode=None, codepoint=None, modifier=None, *a):
        if not self._live() or self.text_focused():
            return False
        name = self.rt.input.key_name(key)
        if self.rt.input.key_down(name):
            self.rt.dispatch_key(name, "down", codepoint or "")
        return False

    def _key_up(self, _w, key, *a):
        if not self._live():
            return False
        name = self.rt.input.key_name(key)
        if self.rt.input.key_up(name):
            self.rt.dispatch_key(name, "up", "")
        return False

    def _joy_buttons(self):
        # Kivy's Window dispatches SDL joystick button events on Android too.
        # Never gate these on native_buttons: a successfully installed Java
        # listener does not guarantee that it receives controller events.
        return self._live()

    def _jb_down(self, _w, stick, button, *a):
        if self._joy_buttons():
            self.rt.input.joy_button(stick, button, True)
        return False

    def _jb_up(self, _w, stick, button, *a):
        if self._joy_buttons():
            self.rt.input.joy_button(stick, button, False)
        return False

    def _jaxis(self, _w, stick, axis, value, *a):
        if not self._live():
            return False
        try:
            self.rt.input.joy_axis(stick, axis, value)
        except Exception as ex:
            try:
                self.rt.log("[input] erro ao ler eixo do gamepad (%s): %s" %
                            (type(ex).__name__, ex))
            except Exception:
                pass
        return False

    def _jhat(self, _w, stick, hat, value, *a):
        if self._joy_buttons():
            self.rt.input.joy_hat(stick, hat, value)
        return False

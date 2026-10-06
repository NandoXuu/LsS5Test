# -*- coding: utf-8 -*-
import math

LEFT = "L2"
RIGHT = "R2"
ZONES = 10
SONY_VENDOR = 0x054C
PRODUCTS = (0x0CE6, 0x0DF2)
REPORT_ID = 0x02
REPORT_SIZE = 64
RIGHT_OFFSET = 11
LEFT_OFFSET = 22
EFFECT_SIZE = 11
MIN_INTERVAL = 0.01
POLL_INTERVAL = 0.25
PERMISSION_TIMEOUT = 30.0
SEND_TIMEOUT_MS = 50
MAX_FAILURES = 3
PLAYER_MASKS = (0x00, 0x04, 0x0A, 0x15, 0x1B, 0x1F)
ACTION_PERMISSION = "luastudio.DUALSENSE_USB_PERMISSION"

READY = "ready"
PENDING = "pending"
FAILED = "failed"
IDLE = "idle"

_SIDES = {
    "l2": LEFT, "lt": LEFT, "l": LEFT, "left": LEFT,
    "r2": RIGHT, "rt": RIGHT, "r": RIGHT, "right": RIGHT,
}
_BOTH = ("both", "all", "lr", "l2r2", "triggers", "")
_ALIASES = {"end": "stop", "finish": "stop"}
_LISTS = ("strengths", "amplitudes", "params")


def _num(value, default=0.0):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return default if f != f else f


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _unit(value):
    return max(0.0, min(1.0, _num(value)))


def _byte(value):
    return max(0, min(255, int(round(_num(value)))))


def _zone(value):
    return max(0, min(ZONES - 1, int(round(_unit(value) * (ZONES - 1)))))


def _level(value):
    u = _unit(value)
    return 0 if u <= 0.0 else max(1, int(round(u * 8)))


def _key(name):
    return str(name).replace("_", "").replace("-", "").lower()


def sides(spec):
    if spec is None:
        return [LEFT, RIGHT]
    if _is_number(spec):
        index = int(spec)
        if index in (1, 2):
            return [LEFT if index == 1 else RIGHT]
        raise ValueError("gatilho invalido: %s" % spec)
    name = str(spec).strip().lower()
    if name in _BOTH:
        return [LEFT, RIGHT]
    if name in _SIDES:
        return [_SIDES[name]]
    raise ValueError("gatilho invalido: %s (use \"L2\", \"R2\" ou \"both\")" % spec)


def _smooth(k):
    return k * k * (3.0 - 2.0 * k)


EASINGS = {
    "linear": lambda k: k,
    "in": lambda k: k * k,
    "out": lambda k: 1.0 - (1.0 - k) * (1.0 - k),
    "inout": _smooth,
    "smooth": _smooth,
    "cubicin": lambda k: k ** 3,
    "cubicout": lambda k: 1.0 - (1.0 - k) ** 3,
    "sine": lambda k: 0.5 - 0.5 * math.cos(math.pi * k),
    "step": lambda k: 0.0 if k < 1.0 else 1.0,
}


def ease(name, k):
    k = max(0.0, min(1.0, k))
    key = _key(name).replace("ease", "")
    fn = EASINGS.get(key)
    if fn is None:
        raise ValueError("easing desconhecido: %s" % name)
    return fn(k)


class Effect(object):
    __slots__ = ("mode", "params")

    def __init__(self, mode=0, params=()):
        values = [int(p) & 0xFF for p in list(params)[:EFFECT_SIZE - 1]]
        values += [0] * (EFFECT_SIZE - 1 - len(values))
        self.mode = int(mode) & 0xFF
        self.params = tuple(values)

    def bytes(self):
        return bytes((self.mode,) + self.params)

    def hex(self):
        return " ".join("%02X" % b for b in self.bytes())

    def is_off(self):
        return self.mode == 0

    def __eq__(self, other):
        return isinstance(other, Effect) and self.mode == other.mode and self.params == other.params

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.mode, self.params))

    def __repr__(self):
        return "Effect(%s)" % self.hex()


OFF = Effect(0)


def _zoned(mode, levels, frequency=0):
    mask = packed = 0
    for zone, level in enumerate(levels[:ZONES]):
        if level > 0:
            mask |= 1 << zone
            packed |= ((level - 1) & 7) << (3 * zone)
    if not mask:
        return OFF
    return Effect(mode, (mask & 0xFF, mask >> 8,
                         packed & 0xFF, (packed >> 8) & 0xFF,
                         (packed >> 16) & 0xFF, (packed >> 24) & 0xFF,
                         0, 0, frequency & 0xFF, 0))


def _pad(values):
    out = list(values)[:ZONES]
    return out + [0.0] * (ZONES - len(out))


def off():
    return OFF


def raw(mode=0, params=()):
    return Effect(mode, params)


def rigid(position=0.0, strength=1.0):
    return Effect(0x01, (_zone(position), _byte(_unit(strength) * 255)))


def feedback(position=0.0, strength=1.0):
    zone = _zone(position)
    level = _level(strength)
    return _zoned(0x21, [level if i >= zone else 0 for i in range(ZONES)])


def zones(strengths=()):
    return _zoned(0x21, [_level(s) for s in _pad(strengths)])


def slope(start=0.0, stop=1.0, from_strength=0.2, to_strength=1.0, easing="linear"):
    a, b = _zone(start), _zone(stop)
    first, last = from_strength, to_strength
    if b < a:
        a, b = b, a
        first, last = last, first
    levels = [0] * ZONES
    for i in range(a, b + 1):
        k = ease(easing, (i - a) / float(b - a)) if b > a else 1.0
        levels[i] = _level(_num(first) + (_num(last) - _num(first)) * k)
    return _zoned(0x21, levels)


def spring(start=0.0, stop=1.0, preload=0.15, stiffness=1.0, easing="linear"):
    return slope(start, stop, preload, stiffness, easing)


def curve(fn, start=0.0, stop=1.0):
    a, b = _zone(start), _zone(stop)
    if b < a:
        a, b = b, a
    levels = [0] * ZONES
    for i in range(a, b + 1):
        k = (i - a) / float(b - a) if b > a else 1.0
        levels[i] = _level(fn(k))
    return _zoned(0x21, levels)


def detent(position=0.5, width=0.15, strength=1.0):
    center = _unit(position) * (ZONES - 1)
    half = max(0.0, _num(width)) * (ZONES - 1) / 2.0
    level = _level(strength)
    return _zoned(0x21, [level if abs(i - center) <= max(half, 0.5) else 0 for i in range(ZONES)])


def ratchet(start=0.0, stop=1.0, teeth=4, strength=1.0, floor=0.0):
    a, b = _zone(start), _zone(stop)
    if b < a:
        a, b = b, a
    period = max(1, int(round((b - a + 1) / float(max(1, int(_num(teeth, 1)))))))
    levels = [0] * ZONES
    for i in range(a, b + 1):
        levels[i] = _level(strength if (i - a) % period == 0 else floor)
    return _zoned(0x21, levels)


def weapon(start=0.4, stop=0.7, strength=1.0):
    level = _level(strength)
    if not level:
        return OFF
    a = max(2, min(7, _zone(start)))
    b = max(a + 1, min(8, _zone(stop)))
    mask = (1 << a) | (1 << b)
    return Effect(0x25, (mask & 0xFF, mask >> 8, (level - 1) & 7))


def bow(start=0.1, stop=0.8, strength=0.8, snap=0.6):
    level, snap_level = _level(strength), _level(snap)
    if not level or not snap_level:
        return OFF
    a = max(0, min(7, _zone(start)))
    b = max(a + 1, min(8, _zone(stop)))
    mask = (1 << a) | (1 << b)
    force = ((level - 1) & 7) | (((snap_level - 1) & 7) << 3)
    return Effect(0x22, (mask & 0xFF, mask >> 8, force & 0xFF, force >> 8))


def gallop(start=0.0, stop=1.0, first=0.2, second=0.6, frequency=20):
    a = max(0, min(8, _zone(start)))
    b = max(a + 1, min(9, _zone(stop)))
    foot_a = int(round(_unit(first) * 6))
    foot_b = max(foot_a + 1, min(7, int(round(_unit(second) * 7))))
    mask = (1 << a) | (1 << b)
    ratio = (foot_b & 7) | ((foot_a & 7) << 3)
    return Effect(0x23, (mask & 0xFF, mask >> 8, ratio, max(1, _byte(frequency))))


def machine(start=0.1, stop=1.0, amplitude_a=1.0, amplitude_b=0.3, frequency=20, period=3):
    a = max(1, min(8, _zone(start)))
    b = max(a + 1, min(9, _zone(stop)))
    amp_a = int(round(_unit(amplitude_a) * 7))
    amp_b = int(round(_unit(amplitude_b) * 7))
    mask = (1 << a) | (1 << b)
    return Effect(0x27, (mask & 0xFF, mask >> 8, (amp_a & 7) | ((amp_b & 7) << 3),
                         max(1, _byte(frequency)), _byte(period)))


def vibration_zones(amplitudes=(), frequency=30):
    return _zoned(0x26, [_level(a) for a in _pad(amplitudes)], max(1, _byte(frequency)))


def vibration(position=0.0, amplitude=1.0, frequency=30):
    zone = _zone(position)
    level = _level(amplitude)
    return _zoned(0x26, [level if i >= zone else 0 for i in range(ZONES)], max(1, _byte(frequency)))


_REGISTRY = {}


def _register(fn, *names):
    import inspect
    params = tuple(inspect.signature(fn).parameters)
    for name in names or (fn.__name__,):
        _REGISTRY[_key(name)] = (fn, params)


_register(off)
_register(raw)
_register(rigid)
_register(feedback, "feedback", "wall")
_register(zones)
_register(slope)
_register(spring)
_register(detent)
_register(ratchet)
_register(weapon)
_register(bow)
_register(gallop)
_register(machine)
_register(vibration)
_register(vibration_zones)


def effect_names():
    return sorted(set(fn.__name__ for fn, _ in _REGISTRY.values()) | {"wall"})


def build(name, *args, **kwargs):
    entry = _REGISTRY.get(_key(name))
    if entry is None:
        raise ValueError("efeito desconhecido: %s" % name)
    fn, names = entry
    params = {}
    for param, value in zip(names, args):
        params[param] = value
    lookup = dict((_key(n), n) for n in names)
    for raw_key, value in kwargs.items():
        k = _key(raw_key)
        k = _key(_ALIASES.get(k, k))
        target = lookup.get(k)
        if target is None:
            raise ValueError("parametro desconhecido em %s: %s" % (name, raw_key))
        params[target] = value
    return fn(**params)


def as_effect(spec, *args, **kwargs):
    if isinstance(spec, Effect):
        return spec
    if spec is None or spec is False:
        return OFF
    if isinstance(spec, str):
        return build(spec, *args, **kwargs)
    raise ValueError("efeito invalido: %r" % (spec,))


def _moving(params):
    out = {}
    for name, value in params.items():
        if _key(name) in _LISTS:
            continue
        if isinstance(value, (list, tuple)) and len(value) == 2 and all(_is_number(x) for x in value):
            out[name] = (float(value[0]), float(value[1]))
    return out


class Hold(object):
    def __init__(self, effect=None, seconds=0.1):
        self.effect = as_effect(effect)
        self.duration = max(0.001, _num(seconds, 0.1))

    def at(self, k):
        return self.effect


class Ramp(object):
    def __init__(self, name, seconds=1.0, easing="linear", **params):
        self.name = name
        self.duration = max(0.001, _num(seconds, 1.0))
        self.easing = easing
        self.moving = _moving(params)
        self.fixed = dict((k, v) for k, v in params.items() if k not in self.moving)
        ease(easing, 0.0)
        self.at(0.0)

    def at(self, k):
        k = ease(self.easing, k)
        args = dict(self.fixed)
        for name, (a, b) in self.moving.items():
            args[name] = a + (b - a) * k
        return build(self.name, **args)


class Sequence(object):
    def __init__(self, steps, loop=False, times=0, final=None):
        self.steps = [make_step(s) for s in steps]
        if not self.steps:
            raise ValueError("sequencia vazia")
        self.loop = bool(loop)
        self.times = max(0, int(_num(times)))
        self.final = as_effect(final)


def make_step(spec):
    if isinstance(spec, (Hold, Ramp)):
        return spec
    if isinstance(spec, dict):
        data = dict(spec)
        seconds = data.pop("duration", data.pop("seconds", 0.1))
        name = data.pop("effect", "off")
        easing = data.pop("easing", "linear")
        if name is None or _key(name) == "off":
            return Hold(OFF, seconds)
        if _moving(data):
            return Ramp(name, seconds, easing, **data)
        return Hold(build(name, **data), seconds)
    if isinstance(spec, (list, tuple)) and len(spec) == 2:
        return Hold(spec[0], spec[1])
    raise ValueError("passo de sequencia invalido: %r" % (spec,))


def pulses(effect, on=0.08, off_time=0.12, count=0, loop=None):
    steps = [Hold(effect, on), Hold(OFF, off_time)]
    return Sequence(steps, loop=(count == 0) if loop is None else loop, times=count)


class _Playback(object):
    def __init__(self, sequence):
        self.sequence = sequence
        self.index = 0
        self.t = 0.0
        self.cycles = 0
        self.total = sum(s.duration for s in sequence.steps)

    def tick(self, dt):
        self.t += max(0.0, dt)
        seq = self.sequence
        while True:
            step = seq.steps[self.index]
            if self.t < step.duration:
                return step.at(self.t / step.duration), False
            self.t -= step.duration
            self.index += 1
            if self.index >= len(seq.steps):
                self.cycles += 1
                if seq.loop and (seq.times == 0 or self.cycles < seq.times):
                    self.index = 0
                else:
                    return seq.final, True


class _Track(object):
    def __init__(self):
        self.effect = OFF
        self.playback = None

    def set(self, effect):
        self.playback = None
        changed = effect != self.effect
        self.effect = effect
        return changed

    def play(self, sequence):
        self.playback = _Playback(sequence)
        return self.tick(0.0)

    def tick(self, dt):
        if self.playback is None:
            return False
        effect, done = self.playback.tick(dt)
        if done:
            self.playback = None
        changed = effect != self.effect
        self.effect = effect
        return changed


def build_report(left=OFF, right=OFF, rumble=None, lightbar=None, player=None):
    report = bytearray(REPORT_SIZE)
    report[0] = REPORT_ID
    flag0, flag1, flag2 = 0x0C, 0, 0
    report[RIGHT_OFFSET:RIGHT_OFFSET + EFFECT_SIZE] = right.bytes()
    report[LEFT_OFFSET:LEFT_OFFSET + EFFECT_SIZE] = left.bytes()
    if rumble is not None:
        flag0 |= 0x03
        flag2 |= 0x04
        report[3] = _byte(_unit(rumble[1]) * 255)
        report[4] = _byte(_unit(rumble[0]) * 255)
    if lightbar is not None:
        flag1 |= 0x04
        flag2 |= 0x02
        report[42] = 0x02
        report[45], report[46], report[47] = (_byte(_unit(c) * 255) for c in lightbar)
    if player is not None:
        flag1 |= 0x10
        report[44] = PLAYER_MASKS[max(0, min(len(PLAYER_MASKS) - 1, int(_num(player))))]
    report[1], report[2], report[39] = flag0, flag1, flag2
    return bytes(report)


class RecordingBackend(object):
    name = "recording"

    def __init__(self, accept=True):
        self.accept = accept
        self.reports = []
        self.opened = False

    def open(self):
        self.opened = True
        return READY

    def send(self, report):
        if not self.accept:
            return False
        self.reports.append(bytes(report))
        return True

    def close(self):
        self.opened = False


class HidapiBackend(object):
    name = "hidapi"

    def __init__(self, log):
        self.log = log
        self.device = None

    def open(self):
        if self.device is not None:
            return READY
        try:
            import hid
        except Exception:
            self.log("[dualsense.trigger] instale o pacote 'hid' para usar no desktop")
            return FAILED
        for product in PRODUCTS:
            try:
                device = hid.device()
                device.open(SONY_VENDOR, product)
                self.device = device
                return READY
            except Exception:
                continue
        self.log("[dualsense.trigger] DualSense nao encontrado")
        return FAILED

    def send(self, report):
        if self.device is None:
            return False
        try:
            return self.device.write(bytes(report)) >= 0
        except Exception:
            return False

    def close(self):
        device, self.device = self.device, None
        if device is not None:
            try:
                device.close()
            except Exception:
                pass


class AndroidUsbBackend(object):
    name = "android-usb"

    def __init__(self, log):
        self.log = log
        self._jni = None
        self._asked = False
        self.manager = None
        self.device = None
        self.connection = None
        self.interface = None
        self.endpoint = None

    def _api(self):
        if self._jni is None:
            try:
                from jnius import autoclass
                self._jni = {
                    "Context": autoclass("android.content.Context"),
                    "Activity": autoclass("org.kivy.android.PythonActivity"),
                    "Intent": autoclass("android.content.Intent"),
                    "PendingIntent": autoclass("android.app.PendingIntent"),
                }
            except Exception as e:
                self.log("[dualsense.trigger] jnius indisponivel: %s" % e)
                self._jni = False
        return self._jni or None

    def _find(self):
        devices = self.manager.getDeviceList()
        for name in devices.keySet():
            device = devices.get(name)
            if device.getVendorId() == SONY_VENDOR and device.getProductId() in PRODUCTS:
                return device
        return None

    def _request(self, api, activity, device):
        intent = api["Intent"](ACTION_PERMISSION)
        intent.setPackage(activity.getPackageName())
        pending = api["PendingIntent"].getBroadcast(activity, 0, intent, api["PendingIntent"].FLAG_IMMUTABLE)
        self.manager.requestPermission(device, pending)

    def open(self):
        if self.connection is not None:
            return READY
        api = self._api()
        if api is None:
            return FAILED
        try:
            activity = api["Activity"].mActivity
            self.manager = activity.getSystemService(api["Context"].USB_SERVICE)
            device = self._find()
            if device is None:
                self._asked = False
                self.log("[dualsense.trigger] DualSense nao encontrado no USB")
                return FAILED
            if not self.manager.hasPermission(device):
                if not self._asked:
                    self._asked = True
                    self._request(api, activity, device)
                return PENDING
            self._asked = False
            return READY if self._claim(device) else FAILED
        except Exception as e:
            self._asked = False
            self.log("[dualsense.trigger] erro USB: %s" % e)
            return FAILED

    def _claim(self, device):
        connection = self.manager.openDevice(device)
        if connection is None:
            self.log("[dualsense.trigger] nao foi possivel abrir o controle")
            return False
        interface = None
        for i in range(device.getInterfaceCount()):
            candidate = device.getInterface(i)
            if candidate.getInterfaceClass() == 3:
                interface = candidate
                break
        if interface is None:
            connection.close()
            self.log("[dualsense.trigger] interface HID nao encontrada")
            return False
        if not connection.claimInterface(interface, True):
            connection.close()
            self.log("[dualsense.trigger] nao foi possivel assumir a interface HID")
            return False
        endpoint = None
        for i in range(interface.getEndpointCount()):
            candidate = interface.getEndpoint(i)
            if candidate.getDirection() == 0:
                endpoint = candidate
                break
        self.device, self.connection = device, connection
        self.interface, self.endpoint = interface, endpoint
        return True

    def send(self, report):
        if self.connection is None:
            return False
        data = bytearray(report)
        try:
            if self.endpoint is not None:
                return self.connection.bulkTransfer(self.endpoint, data, len(data), SEND_TIMEOUT_MS) >= 0
            return self.connection.controlTransfer(
                0x21, 0x09, 0x0200 | data[0], self.interface.getId(), data, len(data), SEND_TIMEOUT_MS) >= 0
        except Exception as e:
            self.log("[dualsense.trigger] erro ao enviar: %s" % e)
            return False

    def close(self):
        connection, interface = self.connection, self.interface
        self.connection = self.interface = self.endpoint = self.device = None
        self._asked = False
        if connection is not None:
            try:
                if interface is not None:
                    connection.releaseInterface(interface)
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass


def default_backend(android, log):
    return AndroidUsbBackend(log) if android else HidapiBackend(log)


def _preset_engine(i):
    return Sequence([
        Ramp("vibration", 1.4, "smooth", position=0.0, amplitude=(0.3 * i, 0.6 * i), frequency=(12, 40)),
        Ramp("vibration", 1.4, "smooth", position=0.0, amplitude=(0.6 * i, 0.3 * i), frequency=(40, 12)),
    ], loop=True)


def _preset_heartbeat(i):
    return Sequence([
        Hold(vibration(0.0, i, 40), 0.09),
        Hold(OFF, 0.11),
        Hold(vibration(0.0, i * 0.8, 35), 0.09),
        Hold(OFF, 0.65),
    ], loop=True)


PRESETS = {
    "pistol": lambda i: weapon(0.4, 0.7, i),
    "shotgun": lambda i: weapon(0.3, 0.8, i),
    "machinegun": lambda i: vibration(0.1, i, 25),
    "rapid": lambda i: machine(0.1, 1.0, i, i * 0.4, 30, 3),
    "bow": lambda i: bow(0.1, 0.8, i, i * 0.75),
    "softspring": lambda i: spring(0.0, 1.0, 0.1 * i, 0.5 * i),
    "heavyspring": lambda i: spring(0.0, 1.0, 0.4 * i, i),
    "wall": lambda i: feedback(0.6, i),
    "brake": lambda i: spring(0.2, 1.0, 0.1 * i, i, "in"),
    "ratchet": lambda i: ratchet(0.1, 1.0, 4, i, 0.1 * i),
    "gallop": lambda i: gallop(0.0, 1.0, 0.2, 0.6, 18),
    "engine": _preset_engine,
    "heartbeat": _preset_heartbeat,
}


def preset_names():
    return sorted(PRESETS)


def make_preset(name, intensity=1.0):
    fn = PRESETS.get(_key(name))
    if fn is None:
        raise ValueError("preset desconhecido: %s" % name)
    return fn(_unit(intensity))


class DualSenseTriggers(object):
    def __init__(self, log=None, android=False, backend=None):
        self.log = log or (lambda s: None)
        self.backend = backend if backend is not None else default_backend(android, self.log)
        self.state = IDLE
        self._tracks = {LEFT: _Track(), RIGHT: _Track()}
        self._rumble = None
        self._lightbar = None
        self._player = None
        self._last = None
        self._dirty = True
        self._since = MIN_INTERVAL
        self._poll = 0.0
        self._wait = 0.0
        self._failures = 0
        self._suspended = False
        self._resume_connect = False

    @property
    def connected(self):
        return self.state == READY

    def connect(self):
        if self.backend is None:
            return False
        if self.state == READY:
            return True
        self._settle(self.backend.open())
        return self.connected

    def disconnect(self):
        if self.state == READY:
            self._flush(force=True, blank=True)
        if self.backend is not None:
            self.backend.close()
        self.state = IDLE
        self._last = None
        self._failures = 0

    def suspend(self):
        if self._suspended:
            return
        self._suspended = True
        self._resume_connect = self.state in (READY, PENDING)
        if self.state == READY:
            for _ in range(2):
                if self._flush(force=True, blank=True):
                    break
        if self.backend is not None:
            self.backend.close()
        self.state = IDLE
        self._last = None
        self._failures = 0

    def resume(self):
        if not self._suspended:
            return
        self._suspended = False
        self._last = None
        self._dirty = True
        if self._resume_connect:
            self._resume_connect = False
            self.connect()

    def _settle(self, state):
        previous = self.state
        self.state = state
        self._poll = 0.0
        if state == PENDING and previous != PENDING:
            self._wait = 0.0
            self.log("[dualsense.trigger] aguardando permissao USB")
        elif state == READY:
            self._dirty = True
            self._last = None
            self._failures = 0
            if previous != READY:
                self.log("[dualsense.trigger] conectado via %s" % self.backend.name)

    def set(self, side, effect, *args, **kwargs):
        built = as_effect(effect, *args, **kwargs)
        for s in sides(side):
            self._tracks[s].set(built)
        self._dirty = True
        self._push()
        return True

    def off(self, side=None):
        return self.set(side, OFF)

    def play(self, side, sequence):
        if not isinstance(sequence, Sequence):
            sequence = Sequence(sequence)
        for s in sides(side):
            self._tracks[s].play(sequence)
        self._dirty = True
        self._push()
        return True

    def hold(self, side, seconds, effect, *args, **kwargs):
        return self.play(side, Sequence([Hold(as_effect(effect, *args, **kwargs), seconds)]))

    def ramp(self, side, name, seconds, easing="linear", loop=False, times=0, **params):
        return self.play(side, Sequence([Ramp(name, seconds, easing, **params)], loop=loop, times=times))

    def preset(self, side, name, intensity=1.0):
        made = make_preset(name, intensity)
        if isinstance(made, Sequence):
            return self.play(side, made)
        return self.set(side, made)

    def stop(self, side=None):
        return self.off(side)

    def effect(self, side):
        return self._tracks[sides(side)[0]].effect

    def playing(self, side):
        return self._tracks[sides(side)[0]].playback is not None

    def rumble(self, left=0.0, right=None):
        right = left if right is None else right
        self._rumble = (_unit(left), _unit(right))
        self._dirty = True
        self._push()
        return True

    def lightbar(self, rgb):
        self._lightbar = tuple(_unit(c) for c in rgb)
        self._dirty = True
        self._push()
        return True

    def player(self, number):
        self._player = max(0, int(_num(number)))
        self._dirty = True
        self._push()
        return True

    def status(self):
        return {
            "state": self.state,
            "backend": self.backend.name if self.backend is not None else "none",
            "connected": self.connected,
            "L2": self._tracks[LEFT].effect.hex(),
            "R2": self._tracks[RIGHT].effect.hex(),
        }

    def _report(self, blank=False):
        left = OFF if blank else self._tracks[LEFT].effect
        right = OFF if blank else self._tracks[RIGHT].effect
        rumble = (0.0, 0.0) if blank and self._rumble is not None else self._rumble
        return build_report(left, right, rumble, self._lightbar, self._player)

    def _push(self):
        if self.state == READY and self._since >= MIN_INTERVAL:
            self._flush()

    def _flush(self, force=False, blank=False):
        report = self._report(blank)
        if not force and report == self._last:
            self._dirty = False
            return True
        if self.backend.send(report):
            self._last = report
            self._dirty = False
            self._since = 0.0
            self._failures = 0
            return True
        self._failures += 1
        if self._failures >= MAX_FAILURES and not force:
            self.log("[dualsense.trigger] conexao USB perdida")
            self.backend.close()
            self.state = FAILED
        return False

    def update(self, dt):
        if self._suspended:
            return
        self._since += dt
        for track in self._tracks.values():
            if track.tick(dt):
                self._dirty = True
        if self.state == PENDING:
            self._wait += dt
            self._poll += dt
            if self._poll >= POLL_INTERVAL:
                self._poll = 0.0
                if self._wait >= PERMISSION_TIMEOUT:
                    self.log("[dualsense.trigger] permissao USB nao concedida")
                    self.backend.close()
                    self.state = FAILED
                else:
                    self._settle(self.backend.open())
        if self._dirty:
            self._push()

    def reset(self):
        self._suspended = False
        self._resume_connect = False
        for track in self._tracks.values():
            track.set(OFF)
        self._rumble = None
        self._lightbar = None
        self._player = None
        self._dirty = True
        self.disconnect()

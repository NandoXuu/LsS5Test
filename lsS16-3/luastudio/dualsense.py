# -*- coding: utf-8 -*-
import colorsys
import math
import re

from .api import to_color, safe_float

SRC_GAMEPAD = 0x00000401
SRC_JOYSTICK = 0x01000010
LIGHT_PLAYER = 10002
SONY_VENDOR = 0x054C
DUALSENSE_PRODUCTS = (0x0CE6, 0x0DF2)
SCAN_INTERVAL = 2.0
SEND_INTERVAL = 0.05
BLACK = (0.0, 0.0, 0.0)
_HEX6 = re.compile(r"^(0x)?[0-9a-fA-F]{6}$")


def _clamp01(v):
    return max(0.0, min(1.0, v))


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def split_color(args):
    args = list(args)
    if not args or args[0] is None:
        return None, args[1:]
    first = args[0]
    if _is_number(first):
        nums = [safe_float(x) for x in args[:3] if _is_number(x)]
        while len(nums) < 3:
            nums.append(0.0)
        if max(nums) > 1.0:
            nums = [x / 255.0 for x in nums]
        return tuple(_clamp01(x) for x in nums), args[3:]
    if isinstance(first, str) and _HEX6.match(first.strip()):
        first = "#" + first.strip().lower().replace("0x", "")
    rgba = to_color(first, None)
    if rgba is None:
        return None, args[1:]
    return tuple(rgba[:3]), args[1:]


def to_hex(rgb):
    return "#%02X%02X%02X" % tuple(int(round(_clamp01(c) * 255)) for c in rgb)


def _argb(tone):
    r, g, b = tone
    value = (0xFF << 24) | (r << 16) | (g << 8) | b
    return value - 0x100000000 if value >= 0x80000000 else value


def _amplitude(strength):
    strength = _clamp01(safe_float(strength))
    return 0 if strength <= 0.0 else max(1, int(round(strength * 255)))


class Fade(object):
    name = "fade"

    def __init__(self, start, end, duration):
        self.start = start
        self.end = end
        self.final = end
        self.duration = max(0.01, duration)
        self.t = 0.0

    def tick(self, dt):
        self.t += dt
        k = min(1.0, self.t / self.duration)
        return tuple(a + (b - a) * k for a, b in zip(self.start, self.end)), k >= 1.0


class Pulse(object):
    name = "pulse"
    final = None

    def __init__(self, color, period):
        self.color = color
        self.period = max(0.1, period)
        self.t = 0.0

    def tick(self, dt):
        self.t += dt
        phase = (1.0 - math.cos(self.t / self.period * math.tau)) * 0.5
        level = 0.08 + 0.92 * phase
        return tuple(c * level for c in self.color), False


class Blink(object):
    name = "blink"
    final = None

    def __init__(self, color, interval, times):
        self.color = color
        self.interval = max(0.02, interval)
        self.times = max(0, int(times))
        self.t = 0.0

    def tick(self, dt):
        self.t += dt
        step = int(self.t / self.interval)
        if self.times and step >= self.times * 2:
            return BLACK, True
        return (self.color if step % 2 == 0 else BLACK), False


class Rainbow(object):
    name = "rainbow"
    final = None

    def __init__(self, period):
        self.period = max(0.2, period)
        self.t = 0.0

    def tick(self, dt):
        self.t += dt
        return colorsys.hsv_to_rgb((self.t / self.period) % 1.0, 1.0, 1.0), False


class _Target(object):
    def __init__(self, dev_id, device, name, dualsense):
        self.dev_id = dev_id
        self.device = device
        self.name = name
        self.dualsense = dualsense
        self.manager = None
        self.color_lights = []
        self.player_lights = []
        self.vib_manager = None
        self.vib_ids = []
        self.vibrator = None
        self.session = None

    def drop_session(self):
        session, self.session = self.session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


class DualSense(object):
    def __init__(self, log, android):
        self.log = log or (lambda s: None)
        self.android = android
        self._jni = None
        self._targets = []
        self._index = 0
        self._clock = 0.0
        self._last_scan = 0.0
        self._since_send = SEND_INTERVAL
        self._dirty = True
        self._wanted = False
        self._base = None
        self._out = None
        self._wire = None
        self._queued = False
        self._effect = None
        self._brightness = 1.0
        self._player = 0
        self._warned = set()

    def _warn(self, key, message):
        if key not in self._warned:
            self._warned.add(key)
            self.log("[dualsense] " + message)

    def _api(self):
        if self._jni is not None:
            return self._jni or None
        if not self.android:
            self._jni = False
            return None
        try:
            from jnius import autoclass
        except Exception as e:
            self._jni = False
            self.log("[dualsense] jnius indisponivel: %s" % e)
            return None

        def load(path):
            try:
                return autoclass(path)
            except Exception:
                return None

        self._jni = {
            "InputDevice": load("android.view.InputDevice"),
            "VibrationEffect": load("android.os.VibrationEffect"),
            "Combined": load("android.os.CombinedVibration"),
            "LightState": load("android.hardware.lights.LightState$Builder"),
            "LightsRequest": load("android.hardware.lights.LightsRequest$Builder"),
        }
        if self._jni["InputDevice"] is None:
            self._jni = False
            return None
        return self._jni

    def _ensure(self):
        if self._dirty or self._clock - self._last_scan >= SCAN_INTERVAL:
            self._scan()

    def _scan(self):
        self._dirty = False
        self._last_scan = self._clock
        api = self._api()
        previous = {t.dev_id: t for t in self._targets}
        if api is None:
            self._targets = []
            return
        found = []
        try:
            ids = list(api["InputDevice"].getDeviceIds())
        except Exception:
            ids = []
        for dev_id in ids:
            try:
                device = api["InputDevice"].getDevice(dev_id)
                if device is None:
                    continue
                sources = device.getSources()
                if not ((sources & SRC_GAMEPAD) == SRC_GAMEPAD or (sources & SRC_JOYSTICK) == SRC_JOYSTICK):
                    continue
                target = previous.get(dev_id) or self._build(dev_id, device)
                found.append(target)
            except Exception:
                continue
        found.sort(key=lambda t: not t.dualsense)
        for dev_id, target in previous.items():
            if dev_id not in ids:
                target.drop_session()
        if [t.dev_id for t in found] != [t.dev_id for t in self._targets]:
            self._wire = None
        self._targets = found

    def _build(self, dev_id, device):
        try:
            name = str(device.getName())
        except Exception:
            name = "?"
        try:
            sony = int(device.getVendorId()) == SONY_VENDOR
            known = int(device.getProductId()) in DUALSENSE_PRODUCTS
        except Exception:
            sony = known = False
        target = _Target(dev_id, device, name, sony and known)
        self._read_lights(target, device)
        self._read_vibrators(target, device)
        return target

    def _read_lights(self, target, device):
        try:
            manager = device.getLightsManager()
            lights = manager.getLights() if manager is not None else None
            count = int(lights.size()) if lights is not None else 0
        except Exception:
            return
        if count == 0:
            return
        target.manager = manager
        plain, rgb, players = [], [], []
        for i in range(count):
            light = lights.get(i)
            try:
                kind = int(light.getType())
            except Exception:
                kind = 0
            try:
                label = str(light.getName()).lower()
            except Exception:
                label = ""
            try:
                has_rgb = bool(light.hasRgbControl())
            except Exception:
                has_rgb = False
            if kind == LIGHT_PLAYER or ("player" in label and "id" in label):
                players.append(light)
            elif has_rgb:
                rgb.append(light)
            else:
                plain.append(light)
        target.color_lights = rgb or plain
        target.player_lights = players
        if not target.color_lights:
            target.color_lights = [lights.get(1 if count > 1 else 0)]
            target.player_lights = []

    def _read_vibrators(self, target, device):
        try:
            manager = device.getVibratorManager()
            ids = [int(i) for i in manager.getVibratorIds()]
            if ids:
                target.vib_manager = manager
                target.vib_ids = ids
        except Exception:
            pass
        try:
            vibrator = device.getVibrator()
            if vibrator is not None and vibrator.hasVibrator():
                target.vibrator = vibrator
        except Exception:
            pass
        if target.vibrator is None and target.vib_manager is not None:
            try:
                target.vibrator = target.vib_manager.getDefaultVibrator()
            except Exception:
                pass

    def _target(self):
        self._ensure()
        if not self._targets:
            return None
        return self._targets[min(self._index, len(self._targets) - 1)]

    def refresh(self):
        self._dirty = True
        self._ensure()
        return len(self._targets)

    def connected(self):
        return self._target() is not None

    def count(self):
        self._ensure()
        return len(self._targets)

    def name(self):
        target = self._target()
        return target.name if target else ""

    def devices(self):
        self._ensure()
        return [{"index": i + 1, "name": t.name, "dualsense": t.dualsense,
                 "rgb": bool(t.color_lights), "players": len(t.player_lights),
                 "vibration": bool(t.vib_ids or t.vibrator)}
                for i, t in enumerate(self._targets)]

    def select(self, index):
        self._ensure()
        i = int(index) - 1
        if i < 0 or i >= len(self._targets):
            return False
        if i != self._index:
            self._index = i
            self._wire = None
            self._redraw()
        return True

    def _wire_value(self, rgb):
        if rgb is None and not self._player:
            return None
        tone = None
        if rgb is not None:
            tone = tuple(int(round(_clamp01(c * self._brightness) * 255)) for c in rgb)
        return tone, self._player

    def _show(self, rgb, force=False):
        self._out = rgb
        if not force and self._since_send < SEND_INTERVAL:
            self._queued = True
            return True
        target = self._target()
        if target is None:
            if not self.android:
                self._warn("desktop", "disponivel apenas no Android")
            return False
        wire = self._wire_value(rgb)
        if wire is None:
            return False
        if wire == self._wire:
            self._queued = False
            return True
        if self._push(target, wire):
            self._wire = wire
            self._queued = False
            self._since_send = 0.0
            return True
        self._since_send = -1.0
        return False

    def _push(self, target, wire):
        api = self._api()
        if api is None or api["LightState"] is None or api["LightsRequest"] is None or target.manager is None:
            self._warn("lights", "controle sem luzes controlaveis (requer Android 12+)")
            return False
        tone, player = wire
        try:
            builder = api["LightsRequest"]()
            if tone is not None:
                state = api["LightState"]()
                state.setColor(_argb(tone))
                built = state.build()
                for light in target.color_lights:
                    builder.addLight(light, built)
            if player and target.player_lights:
                state = api["LightState"]()
                state.setPlayerId(int(player))
                built = state.build()
                for light in target.player_lights:
                    builder.addLight(light, built)
            request = builder.build()
        except Exception as e:
            self._warn("build", "falha ao montar requisicao: %s" % e)
            return False
        for _ in range(2):
            try:
                if target.session is None:
                    target.session = target.manager.openSession()
                target.session.requestLights(request)
                return True
            except Exception:
                target.drop_session()
        self._dirty = True
        return False

    def _redraw(self):
        if self._wanted and self._effect is None:
            self._show(self._base, True)

    def set_color(self, rgb):
        self._wanted = True
        self._effect = None
        self._base = rgb
        return self._show(rgb)

    def off(self):
        return self.set_color(BLACK)

    def color(self):
        return self._out if self._out is not None else self._base

    def set_brightness(self, value):
        self._brightness = _clamp01(safe_float(value, 1.0))
        self._wire = None
        self._redraw()

    def brightness(self):
        return self._brightness

    def set_player(self, number):
        self._wanted = True
        self._player = max(0, int(safe_float(number)))
        self._wire = None
        self._redraw()

    def player(self):
        return self._player

    def _start(self, effect):
        self._wanted = True
        self._effect = effect
        self._since_send = SEND_INTERVAL
        return True

    def fade(self, rgb, seconds):
        start = self.color() or BLACK
        return self._start(Fade(start, rgb, seconds))

    def pulse(self, rgb, period):
        return self._start(Pulse(rgb, period))

    def blink(self, rgb, interval, times):
        return self._start(Blink(rgb, interval, times))

    def rainbow(self, period):
        return self._start(Rainbow(period))

    def stop_effect(self):
        if self._effect is None:
            return False
        self._effect = None
        self._show(self._base or BLACK, True)
        return True

    def effect(self):
        return self._effect.name if self._effect is not None else None

    def _effects(self):
        api = self._api()
        return api["VibrationEffect"] if api is not None else None

    def _play(self, target, effect):
        if target.vibrator is not None:
            target.vibrator.vibrate(effect)
            return True
        return False

    def rumble(self, low, high, duration):
        target = self._target()
        effects = self._effects()
        if target is None or effects is None:
            return False
        low_amp, high_amp = _amplitude(low), _amplitude(high)
        if not (low_amp or high_amp):
            return self.stop_vibration()
        millis = max(1, int(safe_float(duration, 0.3) * 1000))
        try:
            api = self._api()
            if (low_amp != high_amp and target.vib_manager is not None
                    and len(target.vib_ids) >= 2 and api["Combined"] is not None):
                combo = api["Combined"].startParallel()
                if low_amp:
                    combo.addVibrator(target.vib_ids[0], effects.createOneShot(millis, low_amp))
                if high_amp:
                    combo.addVibrator(target.vib_ids[1], effects.createOneShot(millis, high_amp))
                target.vib_manager.vibrate(combo.combine())
                return True
            return self._play(target, effects.createOneShot(millis, max(low_amp, high_amp)))
        except Exception as e:
            self._warn("vibrate", "falha na vibracao: %s" % e)
            self._dirty = True
            return False

    def vibrate(self, duration, strength):
        return self.rumble(strength, strength, duration)

    def pattern(self, durations, strengths, loop=False):
        target = self._target()
        effects = self._effects()
        if target is None or effects is None:
            return False
        times = [max(0, int(safe_float(d) * 1000)) for d in durations]
        amps = [_amplitude(strengths[i]) if i < len(strengths) else 0 for i in range(len(times))]
        if not times or not any(a for a in amps):
            return False
        try:
            return self._play(target, effects.createWaveform(times, amps, 0 if loop else -1))
        except Exception as e:
            self._warn("pattern", "falha no padrao de vibracao: %s" % e)
            return False

    def _cancel(self, target):
        done = False
        for source in (target.vibrator, target.vib_manager):
            if source is None:
                continue
            try:
                source.cancel()
                done = True
            except Exception:
                pass
        return done

    def stop_vibration(self):
        target = self._target()
        return self._cancel(target) if target is not None else False

    def battery(self):
        target = self._target()
        if target is None:
            return None
        try:
            state = target.device.getBatteryState()
            if state is None or not state.isPresent():
                return None
            level = float(state.getCapacity())
            if level != level or level < 0.0:
                return None
            return level, int(state.getStatus()) == 2
        except Exception:
            return None

    def update(self, dt):
        self._clock += dt
        self._since_send += dt
        if not self._wanted:
            return
        self._ensure()
        effect = self._effect
        if effect is not None:
            rgb, finished = effect.tick(dt)
            if finished:
                self._effect = None
                if effect.final is not None:
                    self._base = effect.final
                rgb = self._base or BLACK
            self._show(rgb, finished)
        elif self._wire is None or self._queued:
            self._show(self._base)

    def reset(self):
        self._effect = None
        self._wanted = False
        self._base = None
        self._out = None
        self._wire = None
        self._player = 0
        self._brightness = 1.0
        for target in self._targets:
            self._cancel(target)
            target.drop_session()

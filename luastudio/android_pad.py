# -*- coding: utf-8 -*-
from . import permissions as perms

SRC_KEYBOARD = 0x00000101
SRC_DPAD = 0x00000201
SRC_GAMEPAD = 0x00000401
SRC_JOYSTICK = 0x01000010
ACTION_DOWN = 0
ACTION_UP = 1
REINSTALL_EVERY = 1.0

KEYCODES = {
    96: "A", 97: "B", 99: "X", 100: "Y",
    102: "LB", 103: "RB", 104: "LT", 105: "RT",
    106: "LS", 107: "RS",
    108: "START", 109: "SELECT", 110: "HOME", 4: "SELECT",
    19: "DPAD_UP", 20: "DPAD_DOWN", 21: "DPAD_LEFT", 22: "DPAD_RIGHT",
}


def is_pad_source(src):
    return ((src & SRC_GAMEPAD) == SRC_GAMEPAD
            or (src & SRC_JOYSTICK) == SRC_JOYSTICK
            or (src & SRC_DPAD) == SRC_DPAD)


def _make_listener(handler):
    from jnius import PythonJavaClass, java_method

    class KeyListener(PythonJavaClass):
        __javainterfaces__ = ["android/view/View$OnKeyListener"]
        __javacontext__ = "app"

        @java_method("(Landroid/view/View;ILandroid/view/KeyEvent;)Z")
        def onKey(self, view, key_code, event):
            return handler(key_code, event)

    return KeyListener()


class AndroidPadBridge(object):
    def __init__(self, runtime):
        self.rt = runtime
        self.surface = None
        self.listener = None
        self.ids = {}
        self._autoclass = None
        self._sdl = None
        self._fns = {}
        self._tick = None

    def attach(self):
        if not perms.ANDROID or self.listener is not None:
            return False
        try:
            from jnius import autoclass
            self._autoclass = autoclass
            self._sdl = autoclass("org.libsdl.app.SDLActivity")
            self.surface = self._find_surface()
            if self.surface is None:
                raise RuntimeError("superficie SDL nao encontrada")
            self.listener = _make_listener(self._on_key)
            self.surface.setOnKeyListener(self.listener)
        except Exception as ex:
            self.listener = None
            self.surface = None
            self.rt.log("[input] botoes nativos indisponiveis (%s: %s)" % (type(ex).__name__, ex))
            return False
        self.rt.input.native_buttons = True
        self._scan()
        try:
            from kivy.clock import Clock
            self._tick = Clock.schedule_interval(self._reinstall, REINSTALL_EVERY)
        except Exception:
            self._tick = None
        return True

    def detach(self):
        if self._tick is not None:
            try:
                self._tick.cancel()
            except Exception:
                pass
            self._tick = None
        if self.listener is None:
            return
        try:
            self.surface.setOnKeyListener(self.surface)
        except Exception:
            pass
        self.listener = None
        self.surface = None
        self.ids.clear()
        self.rt.input.native_buttons = False

    def _find_surface(self):
        try:
            layout = self._sdl.getContentView()
            for i in range(int(layout.getChildCount())):
                child = layout.getChildAt(i)
                if child is not None and str(child.getClass().getName()).endswith("SDLSurface"):
                    return child
        except Exception:
            pass
        activity = self._autoclass("org.kivy.android.PythonActivity").mActivity
        return activity.getCurrentFocus()

    def _reinstall(self, _dt):
        if self.listener is None or self.surface is None:
            return False
        try:
            self.surface.setOnKeyListener(self.listener)
        except Exception:
            pass
        return True

    def _live(self):
        return bool(getattr(self.rt, "running", False))

    def _register(self, dev_id, device=None):
        pid = self.ids.get(dev_id)
        if pid is not None:
            return pid
        used = set(self.ids.values())
        pid = next(i for i in range(64) if i not in used)
        self.ids[dev_id] = pid
        label = ""
        try:
            if device is None:
                device = self._autoclass("android.view.InputDevice").getDevice(dev_id)
            label = str(device.getName())
        except Exception:
            pass
        self.rt.input.push_native((pid, None, False, 0, label))
        return pid

    def _scan(self):
        try:
            InputDevice = self._autoclass("android.view.InputDevice")
            for dev_id in sorted(int(i) for i in InputDevice.getDeviceIds()):
                device = InputDevice.getDevice(dev_id)
                if device is not None and is_pad_source(int(device.getSources())):
                    self._register(dev_id, device)
        except Exception:
            pass

    def _on_key(self, code, ev):
        try:
            src = int(ev.getSource())
            if is_pad_source(src):
                name = KEYCODES.get(int(code))
                if name is not None and self._live():
                    action = int(ev.getAction())
                    pid = self._register(int(ev.getDeviceId()))
                    if action == ACTION_DOWN and int(ev.getRepeatCount()) == 0:
                        self.rt.input.push_native((pid, name, True, int(code), ""))
                    elif action == ACTION_UP:
                        self.rt.input.push_native((pid, name, False, int(code), ""))
                    return True
            return self._forward(int(code), ev, src)
        except Exception:
            return False

    def _pad_fn(self, down):
        key = "down" if down else "up"
        if key not in self._fns:
            fn = None
            for path in ("org.libsdl.app.SDLControllerManager", "org.libsdl.app.SDLActivity"):
                try:
                    fn = getattr(self._autoclass(path), "onNativePadDown" if down else "onNativePadUp")
                    break
                except Exception:
                    fn = None
            self._fns[key] = fn
        return self._fns[key]

    def _forward(self, code, ev, src):
        action = int(ev.getAction())
        if action not in (ACTION_DOWN, ACTION_UP):
            return False
        if is_pad_source(src):
            fn = self._pad_fn(action == ACTION_DOWN)
            if fn is not None and fn(int(ev.getDeviceId()), code) == 0:
                return True
        if src & SRC_KEYBOARD:
            (self._sdl.onNativeKeyDown if action == ACTION_DOWN else self._sdl.onNativeKeyUp)(code)
            return True
        return False

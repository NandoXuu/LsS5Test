# -*- coding: utf-8 -*-
import time

MODES = ("auto", "always", "never")

_state = {"mode": "auto", "hw": None, "hw_at": 0.0}


def _android():
    try:
        from kivy.utils import platform
        return platform == "android"
    except Exception:
        return False


def mode():
    return _state["mode"]


def set_mode(value):
    v = str(value if value is not None else "auto").strip().lower()
    if v not in MODES:
        return False
    _state["mode"] = v
    return True


def _detect_android():
    from jnius import autoclass
    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    InputDevice = autoclass("android.view.InputDevice")
    try:
        for dev_id in InputDevice.getDeviceIds():
            dev = InputDevice.getDevice(int(dev_id))
            if dev is None or dev.isVirtual():
                continue
            if (dev.getSources() & InputDevice.SOURCE_KEYBOARD) != InputDevice.SOURCE_KEYBOARD:
                continue
            if dev.getKeyboardType() == InputDevice.KEYBOARD_TYPE_ALPHABETIC:
                return True
        return False
    except Exception:
        Configuration = autoclass("android.content.res.Configuration")
        cfg = activity.getResources().getConfiguration()
        return (cfg.keyboard != Configuration.KEYBOARD_NOKEYS
                and cfg.hardKeyboardHidden == Configuration.HARDKEYBOARDHIDDEN_NO)


def has_hardware_keyboard(force=False):
    if not _android():
        return True
    now = time.monotonic()
    if not force and _state["hw"] is not None and now - _state["hw_at"] < 1.0:
        return _state["hw"]
    try:
        _state["hw"] = bool(_detect_android())
    except Exception:
        _state["hw"] = False
    _state["hw_at"] = now
    return _state["hw"]


def should_suppress():
    m = _state["mode"]
    if m == "never":
        return True
    if m == "always":
        return False
    return has_hardware_keyboard(True)


def hide_virtual():
    if not _android():
        return False
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass

        @run_on_ui_thread
        def _hide():
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            Context = autoclass("android.content.Context")
            imm = activity.getSystemService(Context.INPUT_METHOD_SERVICE)
            view = activity.getWindow().getDecorView()
            imm.hideSoftInputFromWindow(view.getWindowToken(), 0)
        _hide()
        return True
    except Exception:
        return False


SOFT_INPUT_ADJUST_NOTHING = 0x30


def lock_window_pan():
    if not _android():
        return False
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass

        @run_on_ui_thread
        def _lock():
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            activity.getWindow().setSoftInputMode(SOFT_INPUT_ADJUST_NOTHING)
        _lock()
        return True
    except Exception:
        return False


def _suppress_burst():
    try:
        from kivy.clock import Clock
    except Exception:
        return
    for delay in (0, 0.08, 0.2, 0.45):
        Clock.schedule_once(lambda *_a: hide_virtual(), delay)


def bind_textinput(ti):
    if not _android() or getattr(ti, "_ls_softkb", False):
        return ti
    ti._ls_softkb = True

    def _on_focus(_w, focused):
        if focused and should_suppress():
            _suppress_burst()
    ti.bind(focus=_on_focus)
    return ti


def any_text_focused():
    try:
        from kivy.core.window import Window
        from kivy.uix.textinput import TextInput
        for child in list(Window.children):
            for w in child.walk(restrict=False):
                if isinstance(w, TextInput) and w.focus:
                    return True
    except Exception:
        pass
    return False

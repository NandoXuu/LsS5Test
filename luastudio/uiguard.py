# -*- coding: utf-8 -*-
import time

from kivy.clock import Clock

try:
    from kivy.core.window import Window
except Exception:
    Window = None

STUCK_SECONDS = 1.2
CHECK_INTERVAL = 0.25


def lock_android_pan():
    try:
        from . import softkeyboard
        softkeyboard.lock_window_pan()
    except Exception:
        pass


def goto(sm, name, direction="left"):
    if sm is None or sm.current == name:
        return
    tr = sm.transition
    try:
        if getattr(tr, "is_active", False):
            tr.stop()
    except Exception:
        pass
    if hasattr(tr, "direction"):
        try:
            tr.direction = direction
        except Exception:
            pass
    sm.current = name
    try:
        # sem animacao: garante que a tela nova ja nasce no lugar certo
        cur = sm.current_screen
        if cur is not None:
            cur.pos = sm.pos
            cur.size = sm.size
            cur.opacity = 1
    except Exception:
        pass


class UIGuard(object):
    def __init__(self, app, sm=None):
        self.app = app
        self.sm = sm
        self._active_since = None
        self._ev = None

    def install(self):
        lock_android_pan()
        Clock.schedule_once(lambda *_a: lock_android_pan(), 1.0)
        if Window is not None:
            try:
                Window.softinput_mode = ""
            except Exception:
                pass
            for ev in ("on_resize", "on_rotate", "on_restore", "on_maximize"):
                try:
                    Window.bind(**{ev: self._schedule_snap})
                except Exception:
                    pass
        self._ev = Clock.schedule_interval(self._check, CHECK_INTERVAL)
        return self

    def remove(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None

    def _schedule_snap(self, *_a):
        lock_android_pan()
        Clock.schedule_once(self.snap, 0)
        Clock.schedule_once(self.snap, 0.3)

    def _root(self):
        return getattr(self.app, "root", None)

    def snap(self, *_a):
        root = self._root()
        if root is not None and Window is not None:
            try:
                if tuple(root.pos) != (0, 0):
                    root.pos = (0, 0)
                if tuple(root.size) != tuple(Window.size):
                    root.size = Window.size
                if root.opacity != 1:
                    root.opacity = 1
            except Exception:
                pass
        sm = self.sm
        if sm is None:
            return
        try:
            if getattr(sm.transition, "is_active", False):
                return
            cur = sm.current_screen
            if cur is None:
                return
            if tuple(cur.pos) != tuple(sm.pos):
                cur.pos = sm.pos
            if tuple(cur.size) != tuple(sm.size):
                cur.size = sm.size
            if cur.opacity != 1:
                cur.opacity = 1
            for scr in list(sm.screens):
                if scr is not cur and scr.parent is not None:
                    sm.real_remove_widget(scr)
        except Exception:
            pass

    def _check(self, _dt):
        sm = self.sm
        if sm is not None:
            try:
                active = bool(getattr(sm.transition, "is_active", False))
            except Exception:
                active = False
            now = time.monotonic()
            if active:
                if self._active_since is None:
                    self._active_since = now
                elif now - self._active_since > STUCK_SECONDS:
                    try:
                        sm.transition.stop()
                    except Exception:
                        pass
                    self._active_since = None
            else:
                self._active_since = None
        self.snap()


def install(app, sm=None):
    return UIGuard(app, sm).install()

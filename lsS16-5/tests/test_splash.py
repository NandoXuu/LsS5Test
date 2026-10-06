import os
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _Clock(object):
    def __init__(self):
        self.queue = []

    def schedule_once(self, fn, timeout=0):
        self.queue.append((timeout, fn))

    def run(self):
        while self.queue:
            self.queue.sort(key=lambda t: t[0])
            _t, fn = self.queue.pop(0)
            fn(0)


class _Animation(object):
    log = []

    def __init__(self, **kw):
        self.kw = kw
        self.cbs = []

    def bind(self, on_complete=None):
        self.cbs.append(on_complete)

    def start(self, widget):
        _Animation.log.append(sorted(k for k in self.kw if k != "d" and k != "t"))
        for k, v in self.kw.items():
            if k not in ("d", "t"):
                setattr(widget, k, v)
        for cb in self.cbs:
            cb(self, widget)


class _Window(object):
    def __init__(self):
        self.children = []

    def add_widget(self, w):
        w.parent = self
        self.children.append(w)

    def remove_widget(self, w):
        w.parent = None
        self.children.remove(w)


class _Widget(object):
    def __init__(self, **kw):
        self.parent = None
        self.pos = (0, 0)
        self.size = (100, 100)

    def bind(self, **kw):
        pass


class _Obj(object):
    def __init__(self, *a, **kw):
        self.a = 0


def _fake_modules(window, clock):
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        return m
    return {
        "kivy": mod("kivy"),
        "kivy.animation": mod("kivy.animation", Animation=_Animation),
        "kivy.clock": mod("kivy.clock", Clock=clock),
        "kivy.graphics": mod("kivy.graphics", Color=_Obj, Rectangle=_Obj),
        "kivy.metrics": mod("kivy.metrics", dp=lambda v: v),
        "kivy.properties": mod("kivy.properties", NumericProperty=lambda v: v),
        "kivy.uix": mod("kivy.uix"),
        "kivy.uix.widget": mod("kivy.uix.widget", Widget=_Widget),
        "kivy.core": mod("kivy.core"),
        "kivy.core.window": mod("kivy.core.window", Window=window),
    }


class SplashFlowTest(unittest.TestCase):
    def setUp(self):
        self.window = _Window()
        self.clock = _Clock()
        _Animation.log = []
        patcher = mock.patch.dict(sys.modules, _fake_modules(self.window, self.clock))
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.modules.pop("luastudio.splash", None)
        self.addCleanup(sys.modules.pop, "luastudio.splash", None)
        import luastudio.splash as sp
        # a classe de teste nao tem o Widget real: usa so a maquina de estados
        sp.Splash._redraw = lambda self, *a: None
        sp.Splash.__init__ = self._light_init(sp)
        self.sp = sp

    @staticmethod
    def _light_init(sp):
        def init(self, bg=(0, 0, 0, 1), image=None, fallback_text="", **kw):
            self.parent = None
            self.logo_alpha = 0.0
            self.logo_scale = sp.START_SCALE
            self.bg_alpha = 0.0
            self._work = None
            self._deferred = False
            self._on_done = None
            self._finished = False
            self._outro_started = False
            self._disposed = False
            self._shown = False
        return init

    def test_work_runs_between_intro_and_outro(self):
        order = []
        s = self.sp.Splash()
        s.run(work=lambda: order.append("work"), on_done=lambda: order.append("done"))
        self.clock.run()
        self.assertEqual(order, ["work", "done"])
        # entrada (logo_alpha/logo_scale -> 1) ANTES da saida (alpha 0)
        names = [tuple(x) for x in _Animation.log]
        self.assertIn(("logo_alpha", "logo_scale"), names)
        self.assertEqual(s.logo_alpha, 0.0)
        self.assertEqual(self.window.children, [])
        self.assertEqual(len(self.sp._ACTIVE), 0)

    def test_deferred_waits_for_done(self):
        box = {}
        s = self.sp.Splash()
        s.run(work=lambda done: box.setdefault("done", done), deferred=True)
        self.clock.run()
        self.assertIn(s, self.window.children)      # ainda carregando
        box["done"]()
        self.clock.run()
        self.assertEqual(self.window.children, [])

    def test_error_in_work_still_removes_splash(self):
        s = self.sp.Splash()

        def boom():
            raise RuntimeError("x")
        s.run(work=boom)
        self.clock.run()
        self.assertEqual(self.window.children, [])


if __name__ == "__main__":
    unittest.main()

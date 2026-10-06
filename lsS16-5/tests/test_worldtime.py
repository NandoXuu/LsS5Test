import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luastudio.runtime import Runtime
from luastudio.worldtime import WorldTime


def boot(script):
    logs = []
    rt = Runtime(log=logs.append)
    assert rt.run_source(script), "script falhou: %s" % logs
    rt.running = True
    rt.logs = logs
    return rt


def run(rt, seconds, step=0.05):
    n = int(round(seconds / step))
    for _ in range(n):
        rt.update(step)


SCRIPT = """
P = create.image.P{ Position = {0, 0}, Size = {10, 10}, Columns = 4, Rows = 1,
                    Frame = 0, FrameSpeed = 10 }
B = create.button.B{ Position = {0, 50}, Size = {10, 10}, Columns = 4 }
UI = create.image.U{ Position = {0, 90}, Size = {10, 10}, Columns = 4, Rows = 1,
                     Frame = 0, FrameSpeed = 10, TimeLayer = "ui" }
worldT, uiT, worldDt, afterW, afterUI = 0, 0, 0, 0, 0
app.onUpdate(function(dt, t, real) worldT = worldT + dt; worldDt = dt; REAL = real end)
app.onUIUpdate(function(dt) uiT = uiT + dt end)
timer.after(1, function() afterW = afterW + 1 end)
timer.afterUI(1, function() afterUI = afterUI + 1 end)
"""


class TestWorldTime(unittest.TestCase):
    def test_pure(self):
        w = WorldTime()
        self.assertEqual(w.tick(0.1)[0], 0.1)
        w.set_config({"TimeScale": 0.25})
        self.assertAlmostEqual(w.tick(0.4)[0], 0.1)
        w.set_config({"timescale": -3})
        self.assertEqual(w.time_scale, 0.0)
        self.assertEqual(w.set_config({"Foo": 1}), ["Foo"])
        w.set_config({"TimeScale": 1})
        w.pause(0.2)
        wdt, cb = w.tick(0.15)
        self.assertEqual(wdt, 0.0)
        self.assertTrue(w.paused)
        wdt, cb = w.tick(0.15)            # estoura em 0.05 -> sobra vai pro mundo
        self.assertFalse(w.paused)
        self.assertAlmostEqual(wdt, 0.10, places=6)

    def test_timescale(self):
        rt = boot(SCRIPT + "environment.setConfig({TimeScale = 0.25})")
        run(rt, 2.0)
        self.assertAlmostEqual(_g(rt, "worldT"), 0.5, places=3)
        self.assertAlmostEqual(_g(rt, "uiT"), 2.0, places=3)
        self.assertEqual(_g(rt, "afterW"), 0)      # 1s de mundo = 4s reais
        self.assertEqual(_g(rt, "afterUI"), 1)
        # animacao do mundo a 25%: 10fps * 0.5s = 5 frames (wrap em 4 -> 1)
        self.assertAlmostEqual(_f(rt, "P"), 1.0, places=3)
        # UI em velocidade normal: 10fps * 2s = 20 -> wrap -> 0
        self.assertAlmostEqual(_f(rt, "UI"), 0.0, places=3)

    def test_pause_world_and_resume(self):
        rt = boot(SCRIPT + "pause.world()")
        run(rt, 1.0)
        self.assertEqual(_g(rt, "worldT"), 0)
        self.assertAlmostEqual(_g(rt, "uiT"), 1.0, places=3)
        self.assertEqual(_f(rt, "P"), 0.0)          # mundo congelado
        self.assertEqual(_g(rt, "afterW"), 0)       # timer do mundo parado
        self.assertEqual(_g(rt, "afterUI"), 1)      # timer de UI correu
        rt.interp.execute("pause.resume()", "t")
        run(rt, 0.5)
        self.assertAlmostEqual(_g(rt, "worldT"), 0.5, places=3)

    def test_pause_for_seconds(self):
        rt = boot(SCRIPT + "RESUMED = false\n")
        rt.interp.execute("pause.world(1, function() RESUMED = true end)", "t")
        run(rt, 0.5)
        self.assertEqual(_g(rt, "worldT"), 0)
        self.assertFalse(_g(rt, "RESUMED"))
        run(rt, 1.0)                                 # pausa acaba 0.5s depois
        self.assertTrue(_g(rt, "RESUMED"))
        self.assertAlmostEqual(_g(rt, "worldT"), 0.5, places=2)  # so o que sobrou

    def test_pause_not_affected_by_timescale(self):
        rt = boot(SCRIPT + "environment.setConfig({TimeScale = 0.1}) pause.world(1)")
        run(rt, 1.05)
        self.assertFalse(rt.worldtime.paused)

    def test_ui_tween_and_physics(self):
        rt = boot(SCRIPT + "pause.world()\n"
                  "tween.to(B, {Position = {100, 50}}, 1)\n"
                  "tween.to(P, {Position = {100, 0}}, 1)\n")
        run(rt, 1.0)
        self.assertAlmostEqual(_pos(rt, "B"), 100.0, places=1)   # botao anima
        self.assertAlmostEqual(_pos(rt, "P"), 0.0, places=1)     # mundo parado

    def test_reset_clears_state(self):
        rt = boot(SCRIPT + "environment.setConfig({TimeScale = 0.5}) pause.world()")
        self.assertTrue(rt.worldtime.paused)
        rt.run_source("x = 1")
        self.assertFalse(rt.worldtime.paused)
        self.assertEqual(rt.worldtime.time_scale, 1.0)

    def test_get_config_and_errors(self):
        rt = boot("environment.setConfig({TimeScale = 2}) CFG = environment.getConfig().TimeScale\n"
                  "environment.setConfig({Bogus = 1})")
        self.assertEqual(_g(rt, "CFG"), 2.0)
        self.assertTrue(any("Bogus" in l for l in rt.logs))


def _g(rt, name):
    return rt.interp.get_global(name) if hasattr(rt.interp, "get_global") else rt.interp.globals[name]


def _f(rt, name):
    return float(_g(rt, name).props.get("Frame") or 0) % 4


def _pos(rt, name):
    return float(_g(rt, name).pos()[0])


if __name__ == "__main__":
    unittest.main()

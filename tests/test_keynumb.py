import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luastudio.runtime import Runtime


class FakeClock(object):
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def boot(script):
    rt = Runtime()
    rt.input.clock = FakeClock()
    assert rt.run_source(script), "script falhou"
    rt.running = True
    return rt


def frame(rt, dt=0.016):
    rt.input.clock.t += dt
    rt.update(dt)


def press(rt, key):
    rt.input.key_down(key)


def release(rt, key):
    rt.input.key_up(key)


SCRIPT = """
A = keynumb.IsPressed("Z", 1)
B = keynumb.IsPressed("X", 0.2)
log = {}
onUpdate(function(dt)
  if B.pressed and A then log[#log + 1] = "especial"
  elseif A.pressed then log[#log + 1] = "ataque1" end
  state = A and "on" or "off"
end)
"""


class KeynumbTests(unittest.TestCase):
    def test_starts_false(self):
        rt = boot(SCRIPT)
        frame(rt)
        self.assertEqual(rt.interp.globals.get("state"), "off")
        self.assertEqual(rt.interp.globals.get("type")(rt.interp.globals.get("A")), "boolean")

    def test_true_for_window_then_false(self):
        rt = boot(SCRIPT)
        press(rt, "z")
        frame(rt)
        release(rt, "z")
        self.assertEqual(rt.interp.globals.get("state"), "on")
        frame(rt, 0.9)
        self.assertEqual(rt.interp.globals.get("state"), "on")
        frame(rt, 0.2)
        self.assertEqual(rt.interp.globals.get("state"), "off")

    def test_combo_inside_window(self):
        rt = boot(SCRIPT)
        press(rt, "z")
        frame(rt)
        release(rt, "z")
        frame(rt, 0.5)
        press(rt, "x")
        frame(rt)
        log = rt.interp.globals.get("log")
        self.assertEqual(log.ipairs_list(), ["ataque1", "especial"])

    def test_no_combo_after_window(self):
        rt = boot(SCRIPT)
        press(rt, "z")
        frame(rt)
        release(rt, "z")
        frame(rt, 1.5)
        press(rt, "x")
        frame(rt)
        log = rt.interp.globals.get("log")
        self.assertEqual(log.ipairs_list(), ["ataque1"])

    def test_same_args_share_flag(self):
        rt = boot('a = keynumb.IsPressed("Z", 1)\nb = keynumb.IsPressed("Z", 1)\nsame = (a == b)')
        self.assertTrue(rt.interp.globals.get("same"))
        self.assertEqual(len(rt.input.key_flags), 1)

    def test_equals_true_and_tostring(self):
        rt = boot('a = keynumb.IsPressed("Z", 1)\nr1 = (a == false)\ns = tostring(a)')
        self.assertTrue(rt.interp.globals.get("r1"))
        self.assertEqual(rt.interp.globals.get("s"), "false")

    def test_typing_blocks_game_key(self):
        rt = boot(SCRIPT)
        from luastudio import inputs as inp
        bridge = inp.KivyBridge(None, rt, lambda: True)
        bridge._key_down(None, 122)
        frame(rt)
        self.assertEqual(rt.interp.globals.get("state"), "off")
        free = inp.KivyBridge(None, rt, lambda: False)
        free._key_down(None, 122)
        frame(rt)
        self.assertEqual(rt.interp.globals.get("state"), "on")

    def test_reset_on_stop(self):
        rt = boot(SCRIPT)
        press(rt, "z")
        frame(rt)
        rt.stop()
        rt.running = True
        frame(rt)
        self.assertEqual(rt.interp.globals.get("state"), "off")

    def test_keyboard_api(self):
        rt = boot('t = input.keyboard.isTyping()\nok = input.keyboard.setVirtual("never")\nm = input.keyboard.getVirtual()\ninput.keyboard.setVirtual("auto")')
        g = rt.interp.globals
        self.assertEqual(g.get("t"), False)
        self.assertTrue(g.get("ok"))
        self.assertEqual(g.get("m"), "never")


if __name__ == "__main__":
    unittest.main()


class PadBackTests(unittest.TestCase):
    def _bridge(self):
        from luastudio import inputs as inp
        rt = boot('x = 1')
        return rt, inp.KivyBridge(None, rt, lambda: False)

    def test_pad_button_swallows_back_key(self):
        rt, br = self._bridge()
        br._jb_down(None, 0, 1)
        self.assertTrue(br._keyboard(None, 27))
        rt.input.clock.t += 1.0
        self.assertFalse(br._keyboard(None, 27))

    def test_back_without_pad_is_not_swallowed(self):
        rt, br = self._bridge()
        self.assertFalse(br._keyboard(None, 27))

    def test_fallback_escape_not_registered_as_key(self):
        rt, br = self._bridge()
        br._jb_down(None, 0, 1)
        br._key_down(None, 27)
        self.assertFalse(rt.input._kq("ESCAPE", 0))
        rt.input.clock.t += 1.0
        br._key_down(None, 27)
        self.assertTrue(rt.input._kq("ESCAPE", 0))

    def test_bad_events_do_not_raise(self):
        rt, br = self._bridge()
        br._jb_down(None, "x", "y")
        br._jaxis(None, 0, "zz", object())
        br._jhat(None, 0, 0, None)
        br._jb_up(None)
        br._key_down(None, None)

    def test_user_example_with_pad(self):
        script = '''
local p = create.image.Player{ Source = "assets/I.png", Position = {400, 300}, Size = {64, 64}, Columns = 8, Rows = 1, FrameSpeed = 8 }
app.onUpdate(function(dt)
  if input.gamepad.isDown(0, "DPAD_LEFT") then p:Move(-250 * dt, 0) end
  if input.gamepad.isDown(0, "DPAD_RIGHT") then p:Move(250 * dt, 0) end
end)
'''
        rt = boot(script)
        br = __import__("luastudio.inputs", fromlist=["x"]).KivyBridge(None, rt, lambda: False)
        for b in range(0, 17):
            br._jb_down(None, 0, b)
            frame(rt)
            br._jb_up(None, 0, b)
            frame(rt)
        br._jhat(None, 0, 0, (1, 0))
        frame(rt)
        br._jhat(None, 0, 0, (0, 0))
        frame(rt)

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luastudio import dualsense_triggers as T


def reference_vibration(position, amplitude, frequency):
    zones = 0
    for z in range(position, 10):
        zones |= 1 << z
    strength = (amplitude - 1) & 7
    packed = 0
    for z in range(position, 10):
        packed |= strength << (3 * z)
    e = bytearray(11)
    e[0] = 0x26
    e[1] = zones & 0xFF
    e[2] = (zones >> 8) & 0xFF
    e[3] = packed & 0xFF
    e[4] = (packed >> 8) & 0xFF
    e[5] = (packed >> 16) & 0xFF
    e[6] = (packed >> 24) & 0xFF
    e[9] = frequency
    return bytes(e)


def connected():
    backend = T.RecordingBackend()
    ctl = T.DualSenseTriggers(backend=backend)
    assert ctl.connect()
    return ctl, backend


def run(ctl, seconds, step=0.02):
    for _ in range(int(round(seconds / step))):
        ctl.update(step)


class EffectTests(unittest.TestCase):
    def test_vibration_matches_reference(self):
        self.assertEqual(T.vibration(1 / 9.0, 7 / 8.0, 20).bytes(), reference_vibration(1, 7, 20))
        self.assertEqual(T.vibration(0.0, 0.5, 24).bytes(), reference_vibration(0, 4, 24))

    def test_zero_strength_is_off(self):
        self.assertTrue(T.feedback(0.0, 0.0).is_off())
        self.assertTrue(T.weapon(0.4, 0.7, 0.0).is_off())
        self.assertTrue(T.bow(0.1, 0.8, 0.0, 0.5).is_off())

    def test_weapon_layout(self):
        e = T.weapon(0.4, 0.7, 1.0)
        self.assertEqual(e.mode, 0x25)
        self.assertEqual(e.params[0] | (e.params[1] << 8), (1 << 4) | (1 << 6))
        self.assertEqual(e.params[2], 7)

    def test_bow_layout(self):
        e = T.bow(0.1, 0.8, 1.0, 0.5)
        self.assertEqual(e.mode, 0x22)
        force = e.params[2] | (e.params[3] << 8)
        self.assertEqual(force & 7, 7)
        self.assertEqual((force >> 3) & 7, 3)

    def test_spring_grows_with_travel(self):
        e = T.spring(0.0, 1.0, 0.1, 1.0)
        packed = sum(e.params[2 + i] << (8 * i) for i in range(4))
        levels = [((packed >> (3 * z)) & 7) for z in range(10)]
        self.assertEqual(levels, sorted(levels))
        self.assertLess(levels[0], levels[-1])

    def test_zones_mask_skips_zero(self):
        e = T.zones([0, 0, 1, 1])
        self.assertEqual(e.params[0] | (e.params[1] << 8), 0b1100)

    def test_machine_layout(self):
        e = T.machine(0.1, 1.0, 1.0, 0.0, 30, 4)
        self.assertEqual(e.mode, 0x27)
        self.assertEqual(e.params[2], 7)
        self.assertEqual(e.params[3:5], (30, 4))

    def test_build_aliases_and_errors(self):
        self.assertEqual(T.build("weapon", start=0.4, **{"end": 0.7}), T.weapon(0.4, 0.7))
        self.assertEqual(T.build("wall", 0.5, 1.0), T.feedback(0.5, 1.0))
        with self.assertRaises(ValueError):
            T.build("nao_existe")
        with self.assertRaises(ValueError):
            T.build("weapon", cor=1)

    def test_sides(self):
        self.assertEqual(T.sides("lt"), ["L2"])
        self.assertEqual(T.sides("both"), ["L2", "R2"])
        with self.assertRaises(ValueError):
            T.sides("X")


class ReportTests(unittest.TestCase):
    def test_trigger_offsets(self):
        left, right = T.weapon(0.4, 0.7, 1.0), T.bow()
        r = T.build_report(left, right)
        self.assertEqual(len(r), 64)
        self.assertEqual(r[0], 0x02)
        self.assertEqual(r[1], 0x0C)
        self.assertEqual(r[11:22], right.bytes())
        self.assertEqual(r[22:33], left.bytes())

    def test_extras_set_flags(self):
        r = T.build_report(T.OFF, T.OFF, rumble=(1.0, 0.5), lightbar=(1.0, 0.0, 0.0), player=1)
        self.assertEqual(r[1] & 0x03, 0x03)
        self.assertEqual(r[2] & 0x14, 0x14)
        self.assertEqual((r[4], r[3]), (255, 128))
        self.assertEqual((r[45], r[46], r[47]), (255, 0, 0))
        self.assertEqual(r[44], 0x04)


class ControllerTests(unittest.TestCase):
    def test_set_and_dedupe(self):
        ctl, backend = connected()
        ctl.set("R2", "weapon", 0.4, 0.7, 1.0)
        run(ctl, 0.2)
        count = len(backend.reports)
        run(ctl, 0.5)
        self.assertEqual(len(backend.reports), count)
        self.assertEqual(backend.reports[-1][11:22], T.weapon(0.4, 0.7, 1.0).bytes())

    def test_hold_turns_off(self):
        ctl, backend = connected()
        ctl.hold("L2", 0.2, "feedback", 0.0, 1.0)
        run(ctl, 0.1)
        self.assertFalse(ctl.effect("L2").is_off())
        run(ctl, 0.4)
        self.assertTrue(ctl.effect("L2").is_off())
        self.assertEqual(backend.reports[-1][22:33], T.OFF.bytes())

    def test_ramp_changes_frequency(self):
        ctl, backend = connected()
        ctl.ramp("R2", "vibration", 1.0, "linear", False, 0, position=0.0, amplitude=1.0, frequency=(10, 50))
        run(ctl, 0.1)
        early = ctl.effect("R2").params[8]
        run(ctl, 0.7)
        late = ctl.effect("R2").params[8]
        self.assertLess(early, late)
        run(ctl, 0.5)
        self.assertTrue(ctl.effect("R2").is_off())

    def test_sequence_loops(self):
        ctl, _ = connected()
        seq = T.Sequence([
            {"effect": "weapon", "duration": 0.1},
            {"effect": "off", "duration": 0.1},
        ], loop=True)
        ctl.play("R2", seq)
        seen = set()
        for _ in range(40):
            ctl.update(0.02)
            seen.add(ctl.effect("R2").is_off())
        self.assertEqual(seen, {True, False})
        self.assertTrue(ctl.playing("R2"))

    def test_sequence_times(self):
        ctl, _ = connected()
        ctl.play("R2", T.pulses(T.weapon(), 0.05, 0.05, 2))
        run(ctl, 0.6)
        self.assertFalse(ctl.playing("R2"))
        self.assertTrue(ctl.effect("R2").is_off())

    def test_presets_all_build(self):
        ctl, _ = connected()
        for name in T.preset_names():
            ctl.preset("both", name, 0.8)
            run(ctl, 0.1)
        ctl.stop()
        self.assertTrue(ctl.effect("R2").is_off())

    def test_reset_sends_blank_and_closes(self):
        ctl, backend = connected()
        ctl.set("both", "wall", 0.5, 1.0)
        run(ctl, 0.1)
        ctl.reset()
        self.assertEqual(backend.reports[-1][11:33], bytes(22))
        self.assertFalse(backend.opened)
        self.assertEqual(ctl.state, T.IDLE)

    def test_pending_permission_then_ready(self):
        class Slow(T.RecordingBackend):
            calls = 0

            def open(self):
                Slow.calls += 1
                return T.READY if Slow.calls >= 3 else T.PENDING

        ctl = T.DualSenseTriggers(backend=Slow())
        self.assertFalse(ctl.connect())
        self.assertEqual(ctl.state, T.PENDING)
        run(ctl, 1.0)
        self.assertTrue(ctl.connected)

    def test_permission_timeout(self):
        class Never(T.RecordingBackend):
            def open(self):
                return T.PENDING

        ctl = T.DualSenseTriggers(backend=Never())
        ctl.connect()
        run(ctl, 31.0, 0.25)
        self.assertEqual(ctl.state, T.FAILED)

    def test_send_failures_drop_connection(self):
        backend = T.RecordingBackend()
        ctl = T.DualSenseTriggers(backend=backend)
        ctl.connect()
        backend.accept = False
        for i in range(6):
            ctl.set("R2", "wall", i / 10.0 + 0.1, 1.0)
            run(ctl, 0.05)
        self.assertEqual(ctl.state, T.FAILED)

    def test_suspend_blanks_and_releases(self):
        ctl, backend = connected()
        ctl.preset("both", "engine")
        run(ctl, 0.3)
        ctl.suspend()
        self.assertEqual(backend.reports[-1][11:33], bytes(22))
        self.assertFalse(backend.opened)
        sent = len(backend.reports)
        run(ctl, 1.0)
        self.assertEqual(len(backend.reports), sent)

    def test_resume_reconnects_and_restores(self):
        ctl, backend = connected()
        ctl.set("R2", "weapon", 0.4, 0.7, 1.0)
        run(ctl, 0.1)
        ctl.suspend()
        ctl.resume()
        run(ctl, 0.1)
        self.assertTrue(ctl.connected)
        self.assertTrue(backend.opened)
        self.assertEqual(backend.reports[-1][11:22], T.weapon(0.4, 0.7, 1.0).bytes())

    def test_resume_without_prior_connection_stays_idle(self):
        backend = T.RecordingBackend()
        ctl = T.DualSenseTriggers(backend=backend)
        ctl.suspend()
        ctl.resume()
        self.assertEqual(ctl.state, T.IDLE)
        self.assertFalse(backend.opened)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Profiler leve: mede tempo por secao (update, 3D, 2D, audio...) e FPS,
com media movel pra nao "tremer" no overlay. Tambem guarda contadores que
os outros sistemas (pipeline, audio) alimentam, pra ajudar a achar gargalo."""

import time
from collections import deque


class Section(object):
    __slots__ = ("name", "samples", "_t0")

    def __init__(self, name, history=60):
        self.name = name
        self.samples = deque(maxlen=history)
        self._t0 = None

    def start(self):
        self._t0 = time.perf_counter()

    def stop(self):
        if self._t0 is not None:
            self.samples.append(time.perf_counter() - self._t0)
            self._t0 = None

    @property
    def avg_ms(self):
        if not self.samples:
            return 0.0
        return (sum(self.samples) / len(self.samples)) * 1000.0

    @property
    def last_ms(self):
        return self.samples[-1] * 1000.0 if self.samples else 0.0


class Profiler(object):
    def __init__(self, enabled=False, history=60):
        self.enabled = enabled
        self.history = history
        self.sections = {}
        self._frame_t0 = None
        self.frame_samples = deque(maxlen=history)
        self.counters = {}

    def section(self, name):
        s = self.sections.get(name)
        if s is None:
            s = Section(name, self.history)
            self.sections[name] = s
        return s

    class _Ctx(object):
        def __init__(self, prof, name):
            self.prof = prof
            self.name = name

        def __enter__(self):
            if self.prof.enabled:
                self.prof.section(self.name).start()
            return self

        def __exit__(self, *exc):
            if self.prof.enabled:
                self.prof.section(self.name).stop()
            return False

    def measure(self, name):
        """Uso: `with profiler.measure('render3d'): ...`"""
        return Profiler._Ctx(self, name)

    def frame_start(self):
        if self.enabled:
            self._frame_t0 = time.perf_counter()

    def frame_end(self):
        if self.enabled and self._frame_t0 is not None:
            self.frame_samples.append(time.perf_counter() - self._frame_t0)
            self._frame_t0 = None

    def count(self, name, value=1, mode="add"):
        if mode == "set":
            self.counters[name] = value
        else:
            self.counters[name] = self.counters.get(name, 0) + value

    @property
    def fps(self):
        if not self.frame_samples:
            return 0.0
        avg = sum(self.frame_samples) / len(self.frame_samples)
        return 1.0 / avg if avg > 0 else 0.0

    def report(self):
        """Texto pronto pra log/overlay, ordenado do estagio mais caro pro mais barato."""
        lines = ["FPS: %.1f (frame %.2fms)" % (self.fps, (sum(self.frame_samples) /
                 len(self.frame_samples) * 1000.0) if self.frame_samples else 0.0)]
        for name, sec in sorted(self.sections.items(), key=lambda kv: -kv[1].avg_ms):
            lines.append("  %-12s %.3fms (ult. %.3fms)" % (name, sec.avg_ms, sec.last_ms))
        for name, val in sorted(self.counters.items()):
            lines.append("  [%s] %s" % (name, val))
        return "\n".join(lines)

    def reset(self):
        self.sections.clear()
        self.frame_samples.clear()
        self.counters.clear()

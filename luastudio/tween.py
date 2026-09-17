# -*- coding: utf-8 -*-
"""TweenService: anima qualquer propriedade numerica ou vetorial (Position,
Size, Scale, Rotation, Color...) de um objeto ao longo do tempo. Usado tanto
pelo script do usuario (global `tween`) quanto internamente pelo efeito
Transition (Button:EnableTransition{}) pra animar o "click scale" sem o
usuario precisar escrever nada."""

from .lua import LuaTable
from .api import to_vec, vec_table, to_color


def _seq(v):
    """Extrai uma lista de floats de LuaTable/tupla/lista, ou None se nao for
    um valor 'vetorial' (Position, Size, Scale, Color como {r,g,b,a}...)."""
    if isinstance(v, LuaTable):
        arr = v.ipairs_list()
        if arr:
            return [float(x) for x in arr]
        x, y, z = v.get("x"), v.get("y"), v.get("z")
        if x is not None or y is not None or z is not None:
            return [float(x or 0), float(y or 0), float(z or 0)]
        return None
    if isinstance(v, (tuple, list)):
        try:
            return [float(x) for x in v]
        except (TypeError, ValueError):
            return None
    return None


EASINGS = {
    "linear": lambda t: t,
    "ease_in": lambda t: t * t,
    "ease_out": lambda t: 1.0 - (1.0 - t) * (1.0 - t),
    "ease_in_out": lambda t: t * t * (3.0 - 2.0 * t),
    "ease_out_back": lambda t: 1.0 + 2.70158 * (t - 1.0) ** 3 + 1.70158 * (t - 1.0) ** 2,
}


class _TweenItem(object):
    __slots__ = ("obj", "key", "start", "end", "duration", "elapsed",
                 "easing", "on_complete", "vec")

    def __init__(self, obj, key, start, end, duration, easing, on_complete, vec):
        self.obj = obj
        self.key = key
        self.start = start
        self.end = end
        self.duration = max(float(duration), 0.0001)
        self.elapsed = 0.0
        self.easing = easing
        self.on_complete = on_complete
        self.vec = vec


class TweenService(object):
    def __init__(self, runtime):
        self.runtime = runtime
        self.active = []

    def reset(self):
        self.active = []

    def to(self, obj, props, duration=0.3, easing="ease_out", on_complete=None):
        """props: LuaTable ou dict {Prop = valor_final}."""
        if obj is None or not getattr(obj, "alive", True):
            return
        ease_fn = EASINGS.get(str(easing or "ease_out"), EASINGS["ease_out"])
        items = props.items() if isinstance(props, LuaTable) else dict(props).items()
        # remove tweens anteriores nas mesmas propriedades pra nao "brigar"
        keys = [k for k, _ in items if isinstance(k, str)]
        self.active = [t for t in self.active if not (t.obj is obj and t.key in keys)]
        for key, endval in items:
            if not isinstance(key, str):
                continue
            cur = obj.props.get(key)
            cur_seq = _seq(cur)
            end_seq = _seq(endval)
            if cur_seq is None and end_seq is None:
                # nenhum dos dois e uma LuaTable/tupla numerica - tenta como
                # cor por nome/hex ("white" -> "red"), unico caso de string
                # que faz sentido animar; qualquer outra string e ignorada.
                c1 = to_color(cur, None) if cur is not None else None
                c2 = to_color(endval, None) if endval is not None else None
                if c1 is not None or c2 is not None:
                    cur_seq = list(c1) if c1 is not None else list(c2)
                    end_seq = list(c2) if c2 is not None else list(cur_seq)
            if cur_seq is not None or end_seq is not None:
                if cur_seq is None:
                    cur_seq = list(end_seq)
                if end_seq is None:
                    end_seq = list(cur_seq)
                n = max(len(cur_seq), len(end_seq))
                while len(cur_seq) < n:
                    cur_seq.append(0.0)
                while len(end_seq) < n:
                    end_seq.append(cur_seq[len(end_seq)])
                self.active.append(_TweenItem(obj, key, tuple(cur_seq), tuple(end_seq),
                                              duration, ease_fn, on_complete, True))
            else:
                try:
                    start = float(cur) if cur is not None else 0.0
                    end = float(endval)
                except (TypeError, ValueError):
                    continue
                self.active.append(_TweenItem(obj, key, start, end, duration, ease_fn, on_complete, False))

    def cancel(self, obj, key=None):
        self.active = [t for t in self.active if not (t.obj is obj and (key is None or t.key == key))]

    def step(self, dt):
        if not self.active:
            return
        still = []
        finished = []
        for t in self.active:
            if not getattr(t.obj, "alive", True):
                continue
            t.elapsed += dt
            frac = min(1.0, t.elapsed / t.duration)
            e = t.easing(frac)
            if t.vec:
                vals = tuple(s0 + (s1 - s0) * e for s0, s1 in zip(t.start, t.end))
                if len(vals) >= 4:
                    t.obj.props[t.key] = vals    # cor RGBA - mantem como tupla (to_color aceita)
                else:
                    x = vals[0] if len(vals) > 0 else 0.0
                    y = vals[1] if len(vals) > 1 else 0.0
                    z = vals[2] if len(vals) > 2 else 0.0
                    t.obj.props[t.key] = vec_table(x, y, z)
            else:
                t.obj.props[t.key] = t.start + (t.end - t.start) * e
            t.obj.scene.dirty = True
            if frac >= 1.0:
                if t.on_complete is not None:
                    finished.append((t.on_complete, t.obj))
            else:
                still.append(t)
        self.active = still
        for cb, obj in finished:
            self.runtime.call(cb, obj)

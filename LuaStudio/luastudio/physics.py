# -*- coding: utf-8 -*-
"""Fisica 2D simples e leve (Stable.Physics / Area2D / CollisionBox / RayCast2D).

Nao e um motor de fisica "de verdade" (sem solver de impulsos, sem rotacao
por torque) - e deliberadamente simples pra rodar bem em celular: gravidade,
colisao AABB com separacao + quique (Bounce), e areas sensor (Area2D) que
disparam OnAreaEnter/OnAreaExit. Da pra "cuidar da fisica" de um jogo 2D
comum (plataforma, bolinha quicando, coletaveis) sem pesar no Pydroid.
"""

from .lua import LuaTable, truthy
from .api import to_vec, vec_table


class Physics2D(object):
    def __init__(self, runtime):
        self.runtime = runtime
        self.gravity = (0.0, 900.0, 0.0)   # px/s^2, Y para baixo (como no Lua daqui)
        self._overlaps = {}                # (id(area), id(other)) -> bool

    # ------------------------------------------------------------- config
    def set_gravity(self, x=0.0, y=900.0, z=0.0):
        self.gravity = (float(x or 0.0), float(y or 0.0), float(z or 0.0))

    def get_gravity(self):
        return self.gravity

    def reset(self):
        self._overlaps = {}

    # --------------------------------------------------------------- util
    def _box(self, obj):
        x, y, _ = obj.pos()
        w, h, _ = obj.eff_size()
        return x, y, x + w, y + h

    @staticmethod
    def _overlap(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1

    # -------------------------------------------------------------- passo
    def step(self, dt):
        if dt <= 0:
            return
        dt = min(dt, 1.0 / 20.0)  # evita "explodir" apos um travamento/lag
        scene = self.runtime.scene
        bodies = [o for o in scene.objects if o.alive and truthy(o.props.get("Physics"))]
        if not bodies:
            return

        movers = []
        for obj in bodies:
            if truthy(obj.props.get("IsArea")):
                continue
            if truthy(obj.props.get("Static")):
                movers.append(obj)
                continue
            vx, vy, vz = to_vec(obj.props.get("Velocity"), (0.0, 0.0, 0.0))
            if truthy(obj.props.get("UseGravity", True)):
                g = obj.props.get("Gravity")
                gx, gy, gz = to_vec(g, self.gravity) if g is not None else self.gravity
                vx += gx * dt
                vy += gy * dt
                vz += gz * dt
            friction = float(obj.props.get("Friction") or 0.0)
            if friction:
                damp = max(0.0, 1.0 - friction * dt)
                vx *= damp
                vz *= damp
            x, y, z = obj.pos()
            obj.props["Velocity"] = vec_table(vx, vy, vz)
            obj.props["Position"] = vec_table(x + vx * dt, y + vy * dt, z + vz * dt)
            movers.append(obj)
        scene.dirty = True

        # ---- colisao solida (AABB) entre corpos que colidem ----
        solids = [o for o in movers if truthy(o.props.get("Collidable", True))]
        for i, a in enumerate(solids):
            if truthy(a.props.get("Static")):
                continue
            box_a = self._box(a)
            for b in solids:
                if b is a:
                    continue
                box_b = self._box(b)
                if self._overlap(box_a, box_b):
                    self._resolve(a, box_a, b, box_b)
                    box_a = self._box(a)

        # ---- areas sensor (Area2D): so avisa, nao empurra ----
        areas = [o for o in scene.objects if o.alive and truthy(o.props.get("IsArea"))]
        if areas:
            targets = [o for o in scene.objects if o.alive and truthy(o.props.get("Physics")) and not truthy(o.props.get("IsArea"))]
            seen = set()
            for area in areas:
                box_area = self._box(area)
                for other in targets:
                    if other is area:
                        continue
                    key = (id(area), id(other))
                    seen.add(key)
                    overlapping = self._overlap(box_area, self._box(other))
                    was = self._overlaps.get(key, False)
                    if overlapping and not was:
                        cb = area.props.get("OnAreaEnter")
                        if cb is not None:
                            self.runtime.call(cb, area, other)
                    elif was and not overlapping:
                        cb = area.props.get("OnAreaExit")
                        if cb is not None:
                            self.runtime.call(cb, area, other)
                    self._overlaps[key] = overlapping
            for key in list(self._overlaps.keys()):
                if key not in seen:
                    del self._overlaps[key]

    # -------------------------------------------------------- resolucao
    def _resolve(self, a, box_a, b, box_b):
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        overlap_x = min(ax2, bx2) - max(ax1, bx1)
        overlap_y = min(ay2, by2) - max(ay1, by1)
        if overlap_x <= 0 or overlap_y <= 0:
            return

        a_static = truthy(a.props.get("Static"))
        b_static = truthy(b.props.get("Static"))
        if a_static and b_static:
            return

        bounce = max(float(a.props.get("Bounce") or 0.0), float(b.props.get("Bounce") or 0.0))
        ax, ay, az = a.pos()
        bx, by, bz = b.pos()
        avx, avy, avz = to_vec(a.props.get("Velocity"), (0.0, 0.0, 0.0))
        bvx, bvy, bvz = to_vec(b.props.get("Velocity"), (0.0, 0.0, 0.0))

        if overlap_x < overlap_y:
            dirx = 1.0 if (ax1 + ax2) < (bx1 + bx2) else -1.0
            if a_static:
                b.props["Position"] = vec_table(bx + dirx * overlap_x, by, bz)
                b.props["Velocity"] = vec_table(-bvx * bounce, bvy, bvz)
            elif b_static:
                a.props["Position"] = vec_table(ax - dirx * overlap_x, ay, az)
                a.props["Velocity"] = vec_table(-avx * bounce, avy, avz)
            else:
                a.props["Position"] = vec_table(ax - dirx * overlap_x / 2.0, ay, az)
                b.props["Position"] = vec_table(bx + dirx * overlap_x / 2.0, by, bz)
                a.props["Velocity"] = vec_table(-avx * bounce, avy, avz)
                b.props["Velocity"] = vec_table(-bvx * bounce, bvy, bvz)
        else:
            diry = 1.0 if (ay1 + ay2) < (by1 + by2) else -1.0
            if a_static:
                b.props["Position"] = vec_table(bx, by + diry * overlap_y, bz)
                b.props["Velocity"] = vec_table(bvx, -bvy * bounce, bvz)
            elif b_static:
                a.props["Position"] = vec_table(ax, ay - diry * overlap_y, az)
                a.props["Velocity"] = vec_table(avx, -avy * bounce, avz)
            else:
                a.props["Position"] = vec_table(ax, ay - diry * overlap_y / 2.0, az)
                b.props["Position"] = vec_table(bx, by + diry * overlap_y / 2.0, bz)
                a.props["Velocity"] = vec_table(avx, -avy * bounce, avz)
                b.props["Velocity"] = vec_table(bvx, -bvy * bounce, bvz)

        cb_a = a.props.get("OnCollide")
        if cb_a is not None:
            self.runtime.call(cb_a, a, b)
        cb_b = b.props.get("OnCollide")
        if cb_b is not None:
            self.runtime.call(cb_b, b, a)

    # -------------------------------------------------------- RayCast2D
    def raycast(self, x1, y1, x2, y2, exclude=None):
        scene = self.runtime.scene
        best_obj, best_t = None, 1.0
        for obj in scene.objects:
            if not obj.alive or obj is exclude:
                continue
            if not (truthy(obj.props.get("Physics")) or truthy(obj.props.get("IsArea"))):
                continue
            t = self._ray_box_t(x1, y1, x2, y2, *self._box(obj))
            if t is not None and t < best_t:
                best_t, best_obj = t, obj
        if best_obj is None:
            return None
        return best_obj, x1 + (x2 - x1) * best_t, y1 + (y2 - y1) * best_t

    @staticmethod
    def _ray_box_t(x1, y1, x2, y2, bx1, by1, bx2, by2):
        dx, dy = x2 - x1, y2 - y1
        tmin, tmax = 0.0, 1.0
        for p, d, lo, hi in ((x1, dx, bx1, bx2), (y1, dy, by1, by2)):
            if d == 0:
                if p < lo or p > hi:
                    return None
                continue
            t1, t2 = (lo - p) / d, (hi - p) / d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
            if tmin > tmax:
                return None
        return tmin

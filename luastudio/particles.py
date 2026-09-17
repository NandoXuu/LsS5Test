# -*- coding: utf-8 -*-
"""Sistema de particulas simples (CPU, sem node por particula). Um objeto
`create.particles.Nome{...}` e um EMISSOR: as particulas em si nao sao
Instance nem aparecem em app.all() - ficam guardadas dentro do proprio
emissor (obj._particles) e sao desenhadas direto pelo Stage. Isso evita
criar centenas de objetos Lua por segundo so pra fazer fumaca/faisca."""

import random
import math

from .lua import truthy
from .api import to_vec, to_color


class ParticleSystem(object):
    def __init__(self, runtime):
        self.runtime = runtime

    def reset(self):
        for obj in self.runtime.scene.objects:
            if obj.cls == "particles":
                obj._particles = []
                obj._emit_acc = 0.0

    def burst(self, obj, count=10):
        if obj is None or obj.cls != "particles":
            return
        if not hasattr(obj, "_particles"):
            obj._particles = []
        for _ in range(int(count or 0)):
            self._spawn(obj)

    def _spawn(self, obj):
        maxp = int(obj.props.get("MaxParticles") or 200)
        if len(obj._particles) >= maxp:
            return
        x, y, z = obj.pos()
        # espalha a origem numa pequena area (EmitBox), se configurada
        ebx, eby, ebz = to_vec(obj.props.get("EmitBox"), (0.0, 0.0, 0.0))
        x += random.uniform(-ebx, ebx)
        y += random.uniform(-eby, eby)

        direction = float(obj.props.get("Direction") or -90.0)   # -90 = "pra cima" (Y menor)
        spread = float(obj.props.get("SpreadAngle") or 30.0)
        ang = math.radians(direction + random.uniform(-spread, spread))
        speed_lo, speed_hi, _ = to_vec(obj.props.get("Speed"), (60.0, 60.0, 0.0))
        speed = random.uniform(speed_lo, speed_hi if speed_hi else speed_lo)
        vx = math.cos(ang) * speed
        vy = math.sin(ang) * speed

        life_lo, life_hi, _ = to_vec(obj.props.get("Life"), (1.0, 1.0, 0.0))
        life = random.uniform(life_lo, life_hi if life_hi else life_lo)

        size_start = float(obj.props.get("SizeStart") or 10.0)
        size_end = obj.props.get("SizeEnd")
        size_end = float(size_end) if size_end is not None else size_start * 0.2

        c1 = to_color(obj.props.get("Color1"), (1.0, 0.8, 0.3, 1.0))
        c2default = (c1[0], c1[1], c1[2], 0.0)
        c2 = to_color(obj.props.get("Color2"), c2default) if obj.props.get("Color2") is not None else c2default

        obj._particles.append({
            "x": x, "y": y, "vx": vx, "vy": vy,
            "age": 0.0, "life": max(life, 0.05),
            "size0": size_start, "size1": size_end,
            "c1": c1, "c2": c2,
        })

    def step(self, dt):
        gx_default, gy_default, _ = self.runtime.physics.gravity
        for obj in self.runtime.scene.objects:
            if obj.cls != "particles" or not obj.alive:
                continue
            if not hasattr(obj, "_particles"):
                obj._particles = []
                obj._emit_acc = 0.0

            if truthy(obj.props.get("Emitting", True)):
                rate = float(obj.props.get("Rate") or 20.0)
                obj._emit_acc += rate * dt
                while obj._emit_acc >= 1.0:
                    self._spawn(obj)
                    obj._emit_acc -= 1.0

            gx, gy, _ = to_vec(obj.props.get("Gravity"), (gx_default, gy_default, 0.0)) \
                if obj.props.get("Gravity") is not None else (gx_default, gy_default, 0.0)
            alive = []
            for p in obj._particles:
                p["age"] += dt
                if p["age"] >= p["life"]:
                    continue
                p["vx"] += gx * dt
                p["vy"] += gy * dt
                p["x"] += p["vx"] * dt
                p["y"] += p["vy"] * dt
                alive.append(p)
            obj._particles = alive
            if obj._particles or truthy(obj.props.get("Emitting", True)):
                self.runtime.scene.dirty = True

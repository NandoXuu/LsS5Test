# -*- coding: utf-8 -*-
"""Iluminacao em tempo real para o motor 3D (renderizador puro-Python).

Sistemas:
  - Light: luzes Directional / Point / Spot
  - shade_point: acumula a contribuicao de varias luzes num ponto/normal
  - light mapping: cache de iluminacao "baked" para objetos marcados Static
  - light filtering: corte de luzes por distancia/camada/limite maximo
  - sombras: projecao plana (planar shadow) barata, com suavizacao por
    amostras multiplas (soft shadow) e mistura de varias luzes (advanced shadows)
"""

import math

from . import render3d as r3d

MAX_LIGHTS_DEFAULT = 8


class Light(object):
    """type: 'directional' | 'point' | 'spot'"""

    def __init__(self, type="directional", position=(0, 5, 0), direction=(-0.4, -0.9, -0.5),
                 color=(1, 1, 1), intensity=1.0, range=20.0, spot_angle=45.0,
                 casts_shadow=False, layer=0, enabled=True):
        self.type = str(type or "directional").lower()
        self.position = tuple(position)
        self.direction = r3d.normalize(tuple(direction))
        self.color = tuple(color)
        self.intensity = float(intensity)
        self.range = float(range)
        self.spot_angle = float(spot_angle)
        self.casts_shadow = bool(casts_shadow)
        self.layer = layer
        self.enabled = bool(enabled)

    def contribution(self, point, normal):
        """Retorna (light_dir_unit, atten, color*intensity) para um ponto/normal do mundo."""
        if not self.enabled:
            return None
        if self.type == "directional":
            ldir = r3d.normalize((-self.direction[0], -self.direction[1], -self.direction[2]))
            atten = 1.0
        else:
            to_l = r3d.sub(self.position, point)
            dist = math.sqrt(r3d.dot(to_l, to_l)) or 1e-6
            if dist > self.range:
                return None
            ldir = (to_l[0] / dist, to_l[1] / dist, to_l[2] / dist)
            atten = max(0.0, 1.0 - dist / self.range)
            atten *= atten  # falloff quadratico aproximado
            if self.type == "spot":
                cos_cut = math.cos(math.radians(self.spot_angle))
                facing = r3d.dot((-ldir[0], -ldir[1], -ldir[2]), self.direction)
                if facing < cos_cut:
                    return None
                edge = max(0.0, (facing - cos_cut) / max(1e-4, 1.0 - cos_cut))
                atten *= edge
        return ldir, atten, (self.color[0] * self.intensity,
                              self.color[1] * self.intensity,
                              self.color[2] * self.intensity)


def filter_lights(lights, point=None, max_lights=MAX_LIGHTS_DEFAULT, layer=None):
    """Light filtering: descarta luzes desligadas/fora de camada e mantem
    apenas as N mais relevantes (mais proximas/intensas) por objeto, pra nao
    pagar o custo de somar dezenas de luzes em cada face."""
    usable = [l for l in lights if l.enabled and (layer is None or l.layer == layer)]
    if point is None or len(usable) <= max_lights:
        return usable[:max_lights]

    def score(l):
        if l.type == "directional":
            return 1e9
        d = r3d.sub(l.position, point)
        dist = math.sqrt(r3d.dot(d, d)) + 1e-4
        return l.intensity / dist
    usable.sort(key=score, reverse=True)
    return usable[:max_lights]


def shade_point(point, normal, base_color, lights, ambient=0.12, shadow_factor=1.0):
    """Soma a contribuicao difusa de todas as luzes filtradas num ponto."""
    r, g, b = base_color[0] * ambient, base_color[1] * ambient, base_color[2] * ambient
    for light in lights:
        c = light.contribution(point, normal)
        if c is None:
            continue
        ldir, atten, lcol = c
        ndotl = max(0.0, r3d.dot(normal, ldir))
        if ndotl <= 0 or atten <= 0:
            continue
        f = ndotl * atten * shadow_factor
        r += base_color[0] * lcol[0] * f
        g += base_color[1] * lcol[1] * f
        b += base_color[2] * lcol[2] * f
    a = base_color[3] if len(base_color) > 3 else 1.0
    return (min(1.0, r), min(1.0, g), min(1.0, b), a)


# ------------------------------------------------------------- sombras
def shadow_factor_for_point(point, lights, occluders, ground_y=None, samples=1, softness=0.0):
    """Sombra planar barata: para cada luz que projeta sombra, verifica se
    'point' cai dentro da sombra projetada de algum ocluidor sobre o plano
    ground_y (ou o Y do proprio ponto, se None). 'samples'>1 faz jitter na
    direcao da luz pra suavizar a borda (soft shadow / advanced shadows)."""
    if not occluders:
        return 1.0
    factor = 1.0
    gy = ground_y if ground_y is not None else point[1]
    for light in lights:
        if not getattr(light, "casts_shadow", False):
            continue
        hits = 0
        total = max(1, samples)
        for s in range(total):
            jitter = (0.0, 0.0, 0.0)
            if softness > 0 and total > 1:
                a = (s / float(total)) * 2 * math.pi
                jitter = (math.cos(a) * softness, 0.0, math.sin(a) * softness)
            if light.type == "directional":
                d = light.direction
            else:
                d = r3d.normalize(r3d.sub(point, light.position))
            if abs(d[1]) < 1e-4:
                continue
            t = (gy - point[1]) / d[1]
            if t <= 0:
                continue
            hit = (point[0] + d[0] * t + jitter[0], gy, point[2] + d[2] * t + jitter[2])
            for occ in occluders:
                ox, oy, oz = occ["pos"]
                rx, rz = occ.get("radius", (0.5, 0.5))
                if abs(hit[0] - ox) <= rx and abs(hit[2] - oz) <= rz:
                    hits += 1
                    break
        if total:
            factor *= max(0.15, 1.0 - 0.8 * (hits / float(total)))
    return factor


# ------------------------------------------------------- light mapping
class LightmapCache(object):
    """Iluminacao 'assada' (baked) para objetos estaticos: calcula a
    contribuicao das luzes uma vez e reusa nos frames seguintes, ate que a
    cena (posicao/luzes) mude. Reduz custo de shade_point pra geometria
    Static, funcionando junto com o batching do render pipeline."""

    def __init__(self):
        self._cache = {}
        self._light_sig = None

    def signature(self, lights):
        return tuple((l.type, l.position, l.direction, l.color, l.intensity, l.range,
                      l.spot_angle, l.enabled, l.casts_shadow) for l in lights)

    def invalidate_if_lights_changed(self, lights):
        sig = self.signature(lights)
        if sig != self._light_sig:
            self._light_sig = sig
            self._cache.clear()
            return True
        return False

    def get_or_shade(self, key, point, normal, base_color, lights, ambient=0.12,
                      shadow_factor=1.0):
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = shade_point(point, normal, base_color, lights, ambient, shadow_factor)
        self._cache[key] = result
        return result

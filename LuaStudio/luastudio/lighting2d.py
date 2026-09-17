# -*- coding: utf-8 -*-
"""Iluminacao 2D: os mesmos conceitos de lighting.py (3D), adaptados pro
plano XY do palco 2D.

Sistemas:
  - Light2D: luzes Point / Directional / Spot (Spot usa um angulo 2D)
  - shade_point2d: acumula a contribuicao de varias luzes + ambient num
    ponto do palco
  - light filtering: corte de luzes por camada/limite maximo, igual ao 3D
  - sombras: oclusao por segmento-vs-retangulo (AABB) dos objetos com
    CastShadow=true, com jitter opcional pra suavizar a borda
"""

import math

MAX_LIGHTS_2D_DEFAULT = 8


class Light2D(object):
    """type: 'point' | 'directional' | 'spot'. Direction em graus (2D)."""

    def __init__(self, type="point", position=(0, 0), direction=0.0, color=(1, 1, 1),
                 intensity=1.0, range=220.0, spot_angle=45.0, casts_shadow=False,
                 layer=0, enabled=True):
        self.type = str(type or "point").lower()
        self.position = (float(position[0]), float(position[1]))
        self.direction = float(direction)
        self.color = tuple(color)
        self.intensity = float(intensity)
        self.range = float(range)
        self.spot_angle = float(spot_angle)
        self.casts_shadow = bool(casts_shadow)
        self.layer = layer
        self.enabled = bool(enabled)

    def contribution(self, point):
        """Retorna (atten, color*intensity) pra um ponto do palco, ou None
        se a luz nao alcanca esse ponto."""
        if not self.enabled:
            return None
        lcol = (self.color[0] * self.intensity, self.color[1] * self.intensity,
                self.color[2] * self.intensity)
        if self.type == "directional":
            return 1.0, lcol
        dx = point[0] - self.position[0]
        dy = point[1] - self.position[1]
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > self.range:
            return None
        atten = max(0.0, 1.0 - dist / max(1e-6, self.range))
        atten *= atten  # falloff quadratico aproximado, igual ao 3D
        if self.type == "spot":
            ang_to_point = math.degrees(math.atan2(dy, dx))
            diff = abs(((ang_to_point - self.direction + 180.0) % 360.0) - 180.0)
            if diff > self.spot_angle:
                return None
            edge = max(0.0, 1.0 - diff / max(1e-4, self.spot_angle))
            atten *= edge
        return atten, lcol


def filter_lights2d(lights, point=None, max_lights=MAX_LIGHTS_2D_DEFAULT, layer=None):
    """Mantem so as N luzes mais relevantes por objeto (mais proximas ou
    intensas), pra nao pagar o custo de somar dezenas de luzes por widget."""
    usable = [l for l in lights if l.enabled and (layer is None or l.layer == layer)]
    if point is None or len(usable) <= max_lights:
        return usable[:max_lights]

    def score(l):
        if l.type == "directional":
            return 1e9
        dx = point[0] - l.position[0]
        dy = point[1] - l.position[1]
        dist = math.sqrt(dx * dx + dy * dy) + 1e-4
        return l.intensity / dist
    usable.sort(key=score, reverse=True)
    return usable[:max_lights]


def shade_point2d(point, base_color, lights, ambient=1.0, ambient_color=(1, 1, 1),
                   shadow_factor=1.0):
    """Soma a contribuicao de todas as luzes filtradas + luz ambiente num
    ponto 2D. ambient=1.0 (padrao) preserva a cor original quando a cena
    nao tem create.light2d, mantendo retrocompatibilidade total."""
    r = base_color[0] * ambient_color[0] * ambient
    g = base_color[1] * ambient_color[1] * ambient
    b = base_color[2] * ambient_color[2] * ambient
    for light in lights:
        c = light.contribution(point)
        if c is None:
            continue
        atten, lcol = c
        f = atten * shadow_factor
        if f <= 0:
            continue
        r += base_color[0] * lcol[0] * f
        g += base_color[1] * lcol[1] * f
        b += base_color[2] * lcol[2] * f
    a = base_color[3] if len(base_color) > 3 else 1.0
    return (min(1.0, r), min(1.0, g), min(1.0, b), a)


# ------------------------------------------------------------- sombras 2D
def _segment_hits_aabb(x1, y1, x2, y2, box):
    """Teste segmento-vs-retangulo (slab method). box = (minx,miny,maxx,maxy)."""
    minx, miny, maxx, maxy = box
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - minx), (dx, maxx - x1), (-dy, y1 - miny), (dy, maxy - y1)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return False
            if t > t0:
                t0 = t
        else:
            if t < t0:
                return False
            if t < t1:
                t1 = t
    return t0 <= t1


def shadow_factor2d(point, lights, occluders, samples=1, softness=0.0):
    """Sombra 2D por oclusao: pra cada luz com CastShadow=true, verifica se
    o segmento luz->ponto atravessa algum ocluidor (retangulo de objeto
    com CastShadow=true). 'samples'>1 faz jitter leve na origem da luz pra
    suavizar a borda (soft shadow), igual ao shadow_factor_for_point 3D."""
    if not occluders:
        return 1.0
    factor = 1.0
    for light in lights:
        if not getattr(light, "casts_shadow", False) or light.type == "directional":
            continue
        hits = 0
        total = max(1, samples)
        for s in range(total):
            jitter = 0.0
            if softness > 0 and total > 1:
                jitter = (s / float(total) - 0.5) * softness
            lx = light.position[0] + jitter
            ly = light.position[1] + jitter
            blocked = False
            for box in occluders:
                if _segment_hits_aabb(lx, ly, point[0], point[1], box):
                    blocked = True
                    break
            if blocked:
                hits += 1
        if total:
            factor *= max(0.1, 1.0 - 0.85 * (hits / float(total)))
    return factor

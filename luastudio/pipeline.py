# -*- coding: utf-8 -*-
"""Render pipeline: organiza o desenho da cena 3D em estagios claros
(cull -> geometria/G-Buffer -> sombras -> deferred shading -> saida) e
cuida de batching/caching pra nao reprocessar objetos estaticos toda hora.
"""

from . import render3d as r3d
from . import shading
from . import lighting as light_mod


class RenderStats(object):
    __slots__ = ("draw_calls", "faces", "cached_hits", "lights_used")

    def __init__(self):
        self.draw_calls = 0
        self.faces = 0
        self.cached_hits = 0
        self.lights_used = 0


class RenderPipeline(object):
    def __init__(self, ambient=0.12, max_lights=light_mod.MAX_LIGHTS_DEFAULT):
        self.ambient = ambient
        self.max_lights = max_lights
        self.lightmap = light_mod.LightmapCache()
        self.stats = RenderStats()
        self._occluder_cache = []
        self._static_cache = {}   # chave do objeto estatico -> ultimo frame renderizado
        self._batches = {}        # (shape, shader) -> lista de instancias (batching por material/malha)

    # ---------------------------------------------------------- batching
    def batch(self, parts):
        """Agrupa instancias por (malha, shader) — objetos do mesmo tipo sao
        processados em sequencia, o que melhora localidade de cache e permite,
        no futuro, reaproveitar a mesma malha transformada base entre eles."""
        self._batches.clear()
        for inst in parts:
            key = (str(inst.props.get("Shape") or "cube").lower(),
                   str(inst.props.get("Shader") or "lambert").lower())
            self._batches.setdefault(key, []).append(inst)
        ordered = []
        for key in sorted(self._batches):
            ordered.extend(self._batches[key])
        return ordered

    def _cache_key(self, inst):
        return (id(inst), inst.pos(), inst.rot3(), inst.size(), inst.color())

    def is_static(self, inst):
        return bool(inst.props.get("Static"))

    # ------------------------------------------------------------ frame
    def render(self, parts, lights, camera, width, height, occluders=None, ground_y=None):
        self.stats = RenderStats()
        if not parts:
            return []

        lights = [l for l in lights if getattr(l, "enabled", True)]
        lights_changed = self.lightmap.invalidate_if_lights_changed(lights)
        occluders = occluders or []
        self._occluder_cache = occluders

        ordered = self.batch(parts)
        gbuf = shading.build_gbuffer(ordered, camera, width, height)
        self.stats.faces = len(gbuf)
        self.stats.draw_calls = len(self._batches)

        def shadow_lookup(pos, near_lights):
            if not occluders:
                return 1.0
            return light_mod.shadow_factor_for_point(
                pos, near_lights, occluders, ground_y=ground_y, samples=3, softness=0.15)

        out = []
        for entry in gbuf:
            near_lights = light_mod.filter_lights(lights, point=entry.pos, max_lights=self.max_lights)
            self.stats.lights_used = max(self.stats.lights_used, len(near_lights))
            static = self.is_static(entry.obj)
            if static:
                key = (id(entry.obj), entry.face_idx)
                cached = self.lightmap._cache.get(key)
                if cached is not None:
                    self.stats.cached_hits += 1
                    color = cached
                else:
                    shadow = shadow_lookup(entry.pos, near_lights)
                    shader_fn = shading.get_shader(entry.material["shader"])
                    ctx = {"pos": entry.pos, "normal": entry.normal, "albedo": entry.albedo,
                           "lights": near_lights, "ambient": self.ambient, "shadow": shadow,
                           "view_dir": entry.material["view_dir"], "ao": entry.material["ao"]}
                    color = shader_fn(ctx)
                    self.lightmap._cache[key] = color
            else:
                shadow = shadow_lookup(entry.pos, near_lights)
                shader_fn = shading.get_shader(entry.material["shader"])
                ctx = {"pos": entry.pos, "normal": entry.normal, "albedo": entry.albedo,
                       "lights": near_lights, "ambient": self.ambient, "shadow": shadow,
                       "view_dir": entry.material["view_dir"], "ao": entry.material["ao"]}
                color = shader_fn(ctx)
            out.append({"points": entry.points, "color": color, "depth": entry.depth, "obj": entry.obj})

        out.sort(key=lambda d: -d["depth"])
        return out

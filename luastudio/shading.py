# -*- coding: utf-8 -*-
"""Shader system + pipeline deferred para o renderizador puro-Python.

Como o motor rasteriza por FACE (nao por pixel/GPU), o "G-Buffer" aqui e
por-face: a passada de geometria preenche um buffer com posicao, normal,
albedo, material e profundidade de cada face visivel; uma segunda passada
(deferred) consome esse buffer e resolve a iluminacao. Isso reproduz o
padrao real do deferred shading (separar geometria de iluminacao) no nivel
de granularidade que esse motor consegue oferecer.
"""

import math

from . import render3d as r3d
from . import lighting as light_mod

SPECULAR_DEFAULT = 0.35
RIM_DEFAULT = 0.0


# ------------------------------------------------------------- shaders
def shader_unlit(ctx):
    return ctx["albedo"]


def shader_lambert(ctx):
    return light_mod.shade_point(ctx["pos"], ctx["normal"], ctx["albedo"], ctx["lights"],
                                  ctx["ambient"], ctx["shadow"])


def shader_toon(ctx):
    r, g, b, a = shader_lambert(ctx)
    steps = 4.0
    r = math.ceil(r * steps) / steps
    g = math.ceil(g * steps) / steps
    b = math.ceil(b * steps) / steps
    return (min(1.0, r), min(1.0, g), min(1.0, b), a)


def shader_pbr_lite(ctx):
    """Difuso + especular Blinn-Phong + rim light + AO por face (advanced lighting)."""
    base = shader_lambert(ctx)
    normal, view = ctx["normal"], ctx["view_dir"]
    spec_power = ctx.get("shininess", 32.0)
    spec_strength = ctx.get("specular", SPECULAR_DEFAULT)
    rim_strength = ctx.get("rim", RIM_DEFAULT)
    r, g, b, a = base
    for lt in ctx["lights"]:
        c = lt.contribution(ctx["pos"], normal)
        if c is None:
            continue
        ldir, atten, lcol = c
        half_v = r3d.normalize((ldir[0] + view[0], ldir[1] + view[1], ldir[2] + view[2]))
        spec = max(0.0, r3d.dot(normal, half_v)) ** spec_power * spec_strength * atten
        r += lcol[0] * spec
        g += lcol[1] * spec
        b += lcol[2] * spec
    if rim_strength > 0:
        rim = (1.0 - max(0.0, r3d.dot(normal, view))) ** 2.0 * rim_strength
        r += rim
        g += rim
        b += rim
    ao = ctx.get("ao", 1.0)
    return (min(1.0, r) * ao, min(1.0, g) * ao, min(1.0, b) * ao, a)


SHADERS = {
    "unlit": shader_unlit,
    "lambert": shader_lambert,
    "toon": shader_toon,
    "cel": shader_toon,
    "pbr": shader_pbr_lite,
    "pbr_lite": shader_pbr_lite,
    "advanced": shader_pbr_lite,
}


def get_shader(name):
    return SHADERS.get(str(name or "lambert").lower(), shader_lambert)


def approx_ao(face_normal, mesh_faces_normals):
    """AO barata por face: quanto mais faces vizinhas com normal proxima
    (concavidade), mais escurecido. Aproximacao O(n) sem geometria real de
    oclusao — suficiente para dar profundidade em cantos/dobras."""
    if not mesh_faces_normals:
        return 1.0
    close = sum(1 for n in mesh_faces_normals if r3d.dot(n, face_normal) < 0.15)
    return max(0.55, 1.0 - close * 0.06)


# ------------------------------------------------------------- G-Buffer
class GBufferEntry(object):
    __slots__ = ("points", "depth", "pos", "normal", "albedo", "material", "obj", "face_idx")

    def __init__(self, points, depth, pos, normal, albedo, material, obj, face_idx=0):
        self.points = points
        self.depth = depth
        self.pos = pos
        self.normal = normal
        self.albedo = albedo
        self.material = material
        self.obj = obj
        self.face_idx = face_idx


def build_gbuffer(parts, camera, width, height):
    """Passada de geometria: projeta as faces e guarda seus atributos
    (posicao no mundo, normal, albedo, material) SEM aplicar iluminacao."""
    right, up, forward = camera.basis()
    cam = camera.position
    fov = max(10.0, min(160.0, camera.fov))
    f = (0.5 * min(width, height)) / math.tan(math.radians(fov) / 2.0)
    near = 0.15
    gbuf = []

    for inst in parts:
        verts, faces = r3d.get_mesh(inst.props.get("Shape"))
        bx, by, bz = inst.size()
        axx, axy, axz = inst.axis_scale() if hasattr(inst, "axis_scale") else (1.0, 1.0, 1.0)
        sx, sy, sz = bx * axx, by * axy, bz * axz
        px, py, pz = inst.pos()
        rx, ry, rz = [math.radians(a) for a in inst.rot3()]
        base_color = inst.color()
        material = str(inst.props.get("Shader") or inst.props.get("Material") or "lambert")
        mirrored = ((1 if sx < 0 else 0) + (1 if sy < 0 else 0) + (1 if sz < 0 else 0)) % 2 == 1

        world, view = [], []
        for v in verts:
            wx, wy, wz = v[0] * sx, v[1] * sy, v[2] * sz
            wx, wy, wz = r3d.rotate_xyz((wx, wy, wz), rx, ry, rz)
            wx, wy, wz = wx + px, wy + py, wz + pz
            world.append((wx, wy, wz))
            d = (wx - cam[0], wy - cam[1], wz - cam[2])
            view.append((r3d.dot(d, right), r3d.dot(d, up), r3d.dot(d, forward)))

        face_normals = []
        for face in faces:
            f2 = face[::-1] if mirrored else face
            a, b, c = [world[i] for i in f2[:3]]
            face_normals.append(r3d.normalize(r3d.cross(r3d.sub(b, a), r3d.sub(c, a))))

        for idx, face in enumerate(faces):
            f2 = face[::-1] if mirrored else face
            pts_view = [view[i] for i in f2]
            if any(p[2] <= near for p in pts_view):
                continue
            a, b, c = [world[i] for i in f2[:3]]
            normal = face_normals[idx]
            to_cam = r3d.normalize(r3d.sub(cam, a))
            if r3d.dot(normal, to_cam) <= 0:
                continue
            centroid = tuple(sum(world[i][k] for i in f2) / len(f2) for k in range(3))
            pts = [(width * 0.5 + p[0] * f / p[2], height * 0.5 + p[1] * f / p[2]) for p in pts_view]
            depth = sum(p[2] for p in pts_view) / len(pts_view)
            ao = approx_ao(normal, face_normals)
            gbuf.append(GBufferEntry(pts, depth, centroid, normal, base_color,
                                     {"shader": material, "ao": ao, "view_dir": to_cam}, inst, idx))
    return gbuf


def deferred_shade(gbuf, lights, ambient=0.12, shadow_lookup=None):
    """Passada de iluminacao: consome o G-Buffer e resolve a cor final de
    cada face, ja com todas as luzes filtradas/aplicadas (deferred shading)."""
    out = []
    for entry in gbuf:
        near_lights = light_mod.filter_lights(lights, point=entry.pos)
        shadow = shadow_lookup(entry.pos, near_lights) if shadow_lookup else 1.0
        shader_fn = get_shader(entry.material["shader"])
        ctx = {
            "pos": entry.pos, "normal": entry.normal, "albedo": entry.albedo,
            "lights": near_lights, "ambient": ambient, "shadow": shadow,
            "view_dir": entry.material["view_dir"], "ao": entry.material["ao"],
        }
        color = shader_fn(ctx)
        out.append({"points": entry.points, "color": color, "depth": entry.depth, "obj": entry.obj})
    out.sort(key=lambda d: -d["depth"])
    return out

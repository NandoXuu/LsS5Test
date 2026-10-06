# -*- coding: utf-8 -*-
"""Motor 3D em matematica pura (sem OpenGL): malhas, transformacoes,
projecao em perspectiva, back-face culling e painter's algorithm."""

import math

# --------------------------------------------------------------- primitivas
def cube():
    v = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
         (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    f = [(0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7),
         (1, 5, 6, 2), (4, 5, 1, 0), (3, 2, 6, 7)]
    return v, f


def pyramid():
    v = [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1), (0, 1, 0)]
    f = [(0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    return v, f


def plane():
    v = [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)]
    return v, [(0, 1, 2, 3)]


def sphere(seg=10, rings=7):
    verts = []
    for i in range(rings + 1):
        phi = math.pi * i / rings
        for j in range(seg):
            th = 2 * math.pi * j / seg
            verts.append((math.sin(phi) * math.cos(th), math.cos(phi), math.sin(phi) * math.sin(th)))
    faces = []
    for i in range(rings):
        for j in range(seg):
            a = i * seg + j
            b = i * seg + (j + 1) % seg
            c = (i + 1) * seg + (j + 1) % seg
            d = (i + 1) * seg + j
            faces.append((a, b, c, d))
    return verts, faces


def cylinder(seg=14):
    verts = []
    for j in range(seg):
        th = 2 * math.pi * j / seg
        verts.append((math.cos(th), -1, math.sin(th)))
    for j in range(seg):
        th = 2 * math.pi * j / seg
        verts.append((math.cos(th), 1, math.sin(th)))
    faces = []
    for j in range(seg):
        k = (j + 1) % seg
        faces.append((j, k, seg + k, seg + j))
    faces.append(tuple(range(seg - 1, -1, -1)))
    faces.append(tuple(range(seg, 2 * seg)))
    return verts, faces


MESHES = {
    "cube": cube(), "box": cube(), "block": cube(),
    "pyramid": pyramid(), "cone": pyramid(),
    "plane": plane(), "floor": plane(),
    "sphere": sphere(), "ball": sphere(),
    "cylinder": cylinder(),
}


def get_mesh(name):
    return MESHES.get(str(name or "cube").lower(), MESHES["cube"])


# ------------------------------------------------------------ transformacoes
def rotate_xyz(p, rx, ry, rz):
    x, y, z = p
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    y, z = y * cx - z * sx, y * sx + z * cx
    x, z = x * cy + z * sy, -x * sy + z * cy
    x, y = x * cz - y * sz, x * sz + y * cz
    return (x, y, z)


def normalize(v):
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


class Camera(object):
    def __init__(self, position=(0, 2, -8), target=(0, 0, 0), fov=70.0, rot=(0, 0, 0)):
        self.position = position
        self.target = target
        self.fov = fov
        self.rot = rot

    def basis(self):
        forward = normalize(sub(self.target, self.position))
        if abs(forward[1]) > 0.999:
            up_ref = (0, 0, 1)
        else:
            up_ref = (0, 1, 0)
        right = normalize(cross(up_ref, forward))
        up = cross(forward, right)
        # rotacao extra da camera (yaw/pitch/roll em graus)
        rx, ry, rz = [math.radians(a) for a in self.rot]
        if rx or ry or rz:
            forward = rotate_xyz(forward, rx, ry, rz)
            right = rotate_xyz(right, rx, ry, rz)
            up = rotate_xyz(up, rx, ry, rz)
        return right, up, forward


def project_scene(parts, camera, width, height, lights=None, pipeline=None, occluders=None,
                   ground_y=None):
    """Retorna lista de faces prontas para desenhar:
    [{'points': [(x,y)...], 'color': (r,g,b,a), 'depth': float, 'obj': inst}]

    Compativel com chamadas antigas (sem lights/pipeline): usa a luz direcional
    fixa de sempre. Se 'lights' for passado, delega pro RenderPipeline (shaders,
    G-Buffer/deferred, sombras, batching/caching) em pipeline.py."""
    if lights is not None:
        if pipeline is None:
            from . import pipeline as pipeline_mod
            pipeline = pipeline_mod.RenderPipeline()
        return pipeline.render(parts, lights, camera, width, height,
                               occluders=occluders, ground_y=ground_y)
    right, up, forward = camera.basis()
    cam = camera.position
    fov = max(10.0, min(160.0, camera.fov))
    f = (0.5 * min(width, height)) / math.tan(math.radians(fov) / 2.0)
    near = 0.15
    out = []
    light = normalize((-0.4, 0.9, -0.5))

    for inst in parts:
        verts, faces = get_mesh(inst.props.get("Shape"))
        bx, by, bz = inst.size()
        if hasattr(inst, "axis_scale"):
            axx, axy, axz = inst.axis_scale()
        else:
            axx, axy, axz = (1.0, 1.0, 1.0)
        sx, sy, sz = bx * axx, by * axy, bz * axz
        px, py, pz = inst.pos()
        rx, ry, rz = [math.radians(a) for a in inst.rot3()]
        base_color = inst.color()
        # numero impar de eixos espelhados inverte o sentido das faces (winding);
        # sem isso, malhas espelhadas em 1 eixo (ex.: FlipX) apareceriam "de dentro pra fora"
        mirrored = ((1 if sx < 0 else 0) + (1 if sy < 0 else 0) + (1 if sz < 0 else 0)) % 2 == 1

        world = []
        view = []
        for v in verts:
            wx, wy, wz = v[0] * sx, v[1] * sy, v[2] * sz
            wx, wy, wz = rotate_xyz((wx, wy, wz), rx, ry, rz)
            wx, wy, wz = wx + px, wy + py, wz + pz
            world.append((wx, wy, wz))
            d = (wx - cam[0], wy - cam[1], wz - cam[2])
            view.append((dot(d, right), dot(d, up), dot(d, forward)))

        for face in faces:
            face = face[::-1] if mirrored else face
            pts_view = [view[i] for i in face]
            if any(p[2] <= near for p in pts_view):
                continue
            a, b, c = [world[i] for i in face[:3]]
            normal = normalize(cross(sub(b, a), sub(c, a)))
            to_cam = normalize(sub(cam, a))
            if dot(normal, to_cam) <= 0:
                continue
            shade = 0.35 + 0.65 * max(0.0, dot(normal, light))
            col = (min(1.0, base_color[0] * shade), min(1.0, base_color[1] * shade),
                   min(1.0, base_color[2] * shade), base_color[3])
            pts = []
            for (vx, vy, vz) in pts_view:
                pts.append((width * 0.5 + vx * f / vz, height * 0.5 + vy * f / vz))
            depth = sum(p[2] for p in pts_view) / len(pts_view)
            out.append({"points": pts, "color": col, "depth": depth, "obj": inst})

    out.sort(key=lambda d: -d["depth"])   # painter's algorithm
    return out

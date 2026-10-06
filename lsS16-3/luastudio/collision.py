# -*- coding: utf-8 -*-
import math

from .lua import LuaTable, LuaError, truthy, tostring
from .api import to_vec


MARGIN = 0.25


class Material(object):
    def __init__(self, name, friction=0.5, restitution=0.2):
        self.name = name
        self.friction = float(friction)
        self.restitution = float(restitution)

    def lua_index(self, key):
        k = str(key)
        if k == "Name":
            return self.name
        if k == "Friction":
            return self.friction
        if k in ("Restitution", "Bounce"):
            return self.restitution
        return None

    def lua_newindex(self, key, value):
        k = str(key)
        if k == "Friction":
            self.friction = max(0.0, _num(value, self.friction))
        elif k in ("Restitution", "Bounce"):
            self.restitution = max(0.0, _num(value, self.restitution))
        elif k == "Name":
            self.name = tostring(value)

    def lua_call(self, args):
        if args and isinstance(args[0], LuaTable):
            for k, v in args[0].items():
                if isinstance(k, str):
                    self.lua_newindex(k, v)
        return [self]

    def __repr__(self):
        return "<PhysicsMaterial %s>" % self.name


DEFAULT_MATERIALS = (
    ("Default", 0.5, 0.2),
    ("Ice", 0.02, 0.05),
    ("Rubber", 0.9, 0.85),
    ("Metal", 0.4, 0.1),
    ("Wood", 0.6, 0.25),
    ("Sand", 0.95, 0.0),
    ("Bouncy", 0.3, 0.98),
)


class MaterialRegistry(object):
    def __init__(self):
        self.items = {}
        for name, f, r in DEFAULT_MATERIALS:
            self.items[name.lower()] = Material(name, f, r)

    def get(self, key):
        return self.items.get(str(key).lower())

    def lua_index(self, key):
        k = str(key)
        m = self.items.get(k.lower())
        if m is None:
            m = Material(k)
            self.items[k.lower()] = m
        return m

    def lua_newindex(self, key, value):
        if isinstance(value, Material):
            self.items[str(key).lower()] = value
        elif isinstance(value, LuaTable):
            self.lua_index(key).lua_call([value])


def _num(v, default=0.0):
    try:
        f = float(v)
    except Exception:
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    return f


def _opt(spec, name, default=None):
    v = spec.get(name)
    if v is None:
        v = spec.get(name.lower())
    return default if v is None else v


def cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(pts):
    pts = sorted(set((round(float(x), 6), round(float(y), 6)) for x, y in pts))
    if len(pts) < 3:
        return pts
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _in_tri(p, a, b, c):
    d1 = cross(a, b, p)
    d2 = cross(b, c, p)
    d3 = cross(c, a, p)
    return d1 >= -1e-9 and d2 >= -1e-9 and d3 >= -1e-9


def triangulate(pts):
    n = len(pts)
    if n < 3:
        return []
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    if area < 0:
        pts = list(reversed(pts))
    idx = list(range(n))
    tris = []
    guard = 0
    while len(idx) > 3 and guard < 5000:
        guard += 1
        found = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if cross(a, b, c) <= 1e-9:
                continue
            blocked = False
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                q = pts[j]
                if q == a or q == b or q == c:
                    continue
                if _in_tri(q, a, b, c):
                    blocked = True
                    break
            if blocked:
                continue
            tris.append((a, b, c))
            idx.pop(k)
            found = True
            break
        if not found:
            return []
    if len(idx) == 3:
        a, b, c = pts[idx[0]], pts[idx[1]], pts[idx[2]]
        if cross(a, b, c) > 1e-9:
            tris.append((a, b, c))
    return tris


def poly_props(v):
    a = 0.0
    cx = cy = 0.0
    inertia = 0.0
    n = len(v)
    for i in range(n):
        x1, y1 = v[i]
        x2, y2 = v[(i + 1) % n]
        cr = x1 * y2 - x2 * y1
        a += cr * 0.5
        cx += cr * (x1 + x2) / 6.0
        cy += cr * (y1 + y2) / 6.0
        inertia += cr * (x1 * x1 + x1 * x2 + x2 * x2 + y1 * y1 + y1 * y2 + y2 * y2) / 12.0
    if a <= 1e-9:
        return 0.0, 0.0, 0.0, 0.0
    return a, cx / a, cy / a, inertia


class Shape(object):
    __slots__ = ("kind", "lv", "ln", "wv", "wn", "lc", "wc", "r", "minx", "miny",
                 "maxx", "maxy", "body", "collider", "sensor", "friction",
                 "restitution", "layer", "mask", "id", "area", "centroid", "inertia")

    _next_id = 1

    def __init__(self, kind):
        self.kind = kind
        self.lv = self.ln = self.wv = self.wn = None
        self.lc = self.wc = None
        self.r = 0.0
        self.minx = self.miny = self.maxx = self.maxy = 0.0
        self.body = None
        self.collider = None
        self.sensor = False
        self.friction = 0.5
        self.restitution = 0.2
        self.layer = 1
        self.mask = 0xFFFF
        self.area = 0.0
        self.centroid = (0.0, 0.0)
        self.inertia = 0.0
        self.id = Shape._next_id
        Shape._next_id += 1

    @staticmethod
    def poly(verts):
        verts = convex_hull(verts)
        if len(verts) < 3:
            return None
        s = Shape("poly")
        s.lv = [(float(x), float(y)) for x, y in verts]
        s.area, cx, cy, inertia = poly_props(s.lv)
        if s.area <= 1e-6:
            return None
        s.centroid = (cx, cy)
        s.inertia = inertia
        s._normals()
        s.wv = list(s.lv)
        s.wn = list(s.ln)
        return s

    @staticmethod
    def circle(cx, cy, r):
        r = max(float(r), 0.01)
        s = Shape("circle")
        s.lc = (float(cx), float(cy))
        s.wc = s.lc
        s.r = r
        s.area = math.pi * r * r
        s.centroid = s.lc
        s.inertia = s.area * (0.5 * r * r + (cx * cx + cy * cy))
        return s

    def _normals(self):
        n = len(self.lv)
        out = []
        for i in range(n):
            x1, y1 = self.lv[i]
            x2, y2 = self.lv[(i + 1) % n]
            ex, ey = x2 - x1, y2 - y1
            ln = math.hypot(ex, ey) or 1.0
            out.append((ey / ln, -ex / ln))
        self.ln = out

    def shift(self, dx, dy):
        if self.kind == "poly":
            self.lv = [(x + dx, y + dy) for x, y in self.lv]
        else:
            self.lc = (self.lc[0] + dx, self.lc[1] + dy)

    def extent(self):
        if self.kind == "circle":
            return self.r
        xs = [p[0] for p in self.lv]
        ys = [p[1] for p in self.lv]
        return 0.5 * min(max(xs) - min(xs), max(ys) - min(ys))

    def transform(self, x, y, c, s):
        if self.kind == "poly":
            wv = [(x + c * px - s * py, y + s * px + c * py) for px, py in self.lv]
            self.wv = wv
            self.wn = [(c * nx - s * ny, s * nx + c * ny) for nx, ny in self.ln]
            xs = [p[0] for p in wv]
            ys = [p[1] for p in wv]
            self.minx, self.maxx = min(xs), max(xs)
            self.miny, self.maxy = min(ys), max(ys)
        else:
            lx, ly = self.lc
            wx = x + c * lx - s * ly
            wy = y + s * lx + c * ly
            self.wc = (wx, wy)
            self.minx, self.maxx = wx - self.r, wx + self.r
            self.miny, self.maxy = wy - self.r, wy + self.r


SHAPE_ALIASES = {
    "box": "box", "rect": "box", "rectangle": "box", "square": "box", "cube": "box",
    "circle": "circle", "ball": "circle", "sphere": "circle",
    "capsule": "capsule",
    "polygon": "polygon", "poly": "polygon", "convex": "polygon", "hull": "polygon",
    "mesh": "mesh", "concave": "mesh", "trimesh": "mesh",
}


def _points(v, who):
    pts = []
    if isinstance(v, LuaTable):
        for p in v.ipairs_list():
            x, y, _ = to_vec(p, (0.0, 0.0, 0.0))
            pts.append((x, y))
    if len(pts) < 3:
        raise LuaError("%s: Points precisa de pelo menos 3 pontos {x, y}" % who)
    return pts


class Collider(object):
    def __init__(self, spec, registry):
        if spec is None:
            spec = LuaTable()
        if not isinstance(spec, LuaTable):
            raise LuaError("AddCollider: o argumento precisa ser uma tabela { Shape = ... }")
        shape = tostring(_opt(spec, "Shape", "box")).lower()
        if shape not in SHAPE_ALIASES:
            raise LuaError("AddCollider: Shape '%s' desconhecido (box, circle, capsule, polygon, mesh)" % shape)
        self.shape = SHAPE_ALIASES[shape]
        size = _opt(spec, "Size")
        self.size = None
        if size is not None:
            w, h, _ = to_vec(size, (0.0, 0.0, 0.0))
            self.size = (abs(w), abs(h))
        r = _opt(spec, "Radius")
        self.radius = abs(_num(r)) if r is not None else None
        hgt = _opt(spec, "Height")
        self.height = abs(_num(hgt)) if hgt is not None else None
        ox, oy, _ = to_vec(_opt(spec, "Offset"), (0.0, 0.0, 0.0))
        self.offset = (ox, oy)
        self.angle = _num(_opt(spec, "Angle", 0.0))
        d = _opt(spec, "Direction")
        self.direction = tostring(d).lower() if d is not None else None
        self.points = None
        if self.shape in ("polygon", "mesh"):
            self.points = _points(_opt(spec, "Points"), "AddCollider")
        self.sensor = truthy(_opt(spec, "IsSensor", _opt(spec, "Sensor", False)))
        mat = _opt(spec, "Material")
        if isinstance(mat, str):
            found = registry.get(mat)
            if found is None:
                raise LuaError("AddCollider: material '%s' nao existe" % mat)
            mat = found
        self.material = mat if isinstance(mat, Material) else None
        f = _opt(spec, "Friction")
        self.friction = max(0.0, _num(f)) if f is not None else None
        e = _opt(spec, "Restitution", _opt(spec, "Bounce"))
        self.restitution = max(0.0, _num(e)) if e is not None else None
        lay = _opt(spec, "CollisionLayer", _opt(spec, "Layer"))
        self.layer = int(_num(lay)) if lay is not None else None
        msk = _opt(spec, "CollisionMask", _opt(spec, "Mask"))
        self.mask = int(_num(msk)) if msk is not None else None

    def signature(self):
        m = (self.material.friction, self.material.restitution) if self.material else None
        return (id(self), m)

    def _xf(self, pts, sx, sy):
        a = math.radians(self.angle)
        c, s = math.cos(a), math.sin(a)
        ox, oy = self.offset[0] * sx, self.offset[1] * sy
        return [(ox + c * x - s * y, oy + s * x + c * y) for x, y in pts]

    def make_shapes(self, obj):
        sx, sy, _ = obj.axis_scale()
        ax, ay = abs(sx), abs(sy)
        w0, h0, _ = obj.size()
        out = []
        if self.shape == "box":
            w, h = self.size if self.size else (w0, h0)
            w, h = w * ax, h * ay
            hw, hh = w / 2.0, h / 2.0
            s = Shape.poly(self._xf([(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)], 1.0, 1.0))
            if s is not None:
                out.append(s)
        elif self.shape == "circle":
            r = self.radius if self.radius is not None else min(w0 * ax, h0 * ay) / 2.0
            if self.radius is not None:
                r *= (ax + ay) / 2.0
            cx, cy = self._xf([(0.0, 0.0)], 1.0, 1.0)[0]
            out.append(Shape.circle(cx, cy, r))
        elif self.shape == "capsule":
            if self.radius is not None and self.height is not None:
                w, h = self.radius * 2.0, self.height
            elif self.size:
                w, h = self.size
            else:
                w, h = w0, h0
            w, h = w * ax, h * ay
            vertical = (self.direction != "horizontal") if self.direction else (h >= w)
            if vertical:
                r = w / 2.0
                seg = max(h / 2.0 - r, 0.0)
                rect = [(-r, -seg), (r, -seg), (r, seg), (-r, seg)]
                centers = [(0.0, -seg), (0.0, seg)]
            else:
                r = h / 2.0
                seg = max(w / 2.0 - r, 0.0)
                rect = [(-seg, -r), (seg, -r), (seg, r), (-seg, r)]
                centers = [(-seg, 0.0), (seg, 0.0)]
            if seg > 1e-6:
                s = Shape.poly(self._xf(rect, 1.0, 1.0))
                if s is not None:
                    out.append(s)
                for cx, cy in self._xf(centers, 1.0, 1.0):
                    out.append(Shape.circle(cx, cy, r))
            else:
                cx, cy = self._xf([(0.0, 0.0)], 1.0, 1.0)[0]
                out.append(Shape.circle(cx, cy, r))
        elif self.shape == "polygon":
            pts = [(x * sx, y * sy) for x, y in self.points]
            s = Shape.poly(self._xf(pts, 1.0, 1.0))
            if s is None:
                raise LuaError("AddCollider: Points formam um poligono degenerado")
            out.append(s)
        elif self.shape == "mesh":
            pts = self._xf([(x * sx, y * sy) for x, y in self.points], 1.0, 1.0)
            tris = triangulate(pts)
            if not tris:
                s = Shape.poly(pts)
                if s is not None:
                    out.append(s)
            for tri in tris:
                s = Shape.poly(list(tri))
                if s is not None:
                    out.append(s)
        return out


def circle_circle(a, b):
    ax, ay = a.wc
    bx, by = b.wc
    dx, dy = bx - ax, by - ay
    rs = a.r + b.r
    d2 = dx * dx + dy * dy
    if d2 > (rs + MARGIN) * (rs + MARGIN):
        return None
    d = math.sqrt(d2)
    if d > 1e-9:
        nx, ny = dx / d, dy / d
    else:
        nx, ny = 0.0, -1.0
    pen = rs - d
    k = a.r - pen * 0.5
    return nx, ny, [(ax + nx * k, ay + ny * k, pen)]


def poly_circle(p, c):
    cx, cy = c.wc
    r = c.r
    wv, wn = p.wv, p.wn
    n = len(wv)
    best = -1e18
    idx = 0
    for i in range(n):
        nx, ny = wn[i]
        vx, vy = wv[i]
        s = nx * (cx - vx) + ny * (cy - vy)
        if s > r + MARGIN:
            return None
        if s > best:
            best = s
            idx = i
    v1 = wv[idx]
    v2 = wv[(idx + 1) % n]
    ex, ey = v2[0] - v1[0], v2[1] - v1[1]
    if best < 1e-9:
        nx, ny = wn[idx]
        pen = r - best
        k = r - pen * 0.5
        return nx, ny, [(cx - nx * k, cy - ny * k, pen)]
    u1 = (cx - v1[0]) * ex + (cy - v1[1]) * ey
    u2 = (cx - v2[0]) * (-ex) + (cy - v2[1]) * (-ey)
    if u1 <= 0.0 or u2 <= 0.0:
        vx, vy = v1 if u1 <= 0.0 else v2
        dx, dy = cx - vx, cy - vy
        d = math.hypot(dx, dy)
        if d > r + MARGIN:
            return None
        if d > 1e-9:
            nx, ny = dx / d, dy / d
        else:
            nx, ny = wn[idx]
    else:
        nx, ny = wn[idx]
        d = best
    pen = r - d
    k = r - pen * 0.5
    return nx, ny, [(cx - nx * k, cy - ny * k, pen)]


def _max_sep(a, b):
    best = -1e18
    idx = 0
    av, an, bv = a.wv, a.wn, b.wv
    for i in range(len(av)):
        nx, ny = an[i]
        vx, vy = av[i]
        m = 1e18
        for x, y in bv:
            d = nx * (x - vx) + ny * (y - vy)
            if d < m:
                m = d
                if m < best:
                    break
        if m > best:
            best = m
            idx = i
    return best, idx


def _clip_ge(pts, dx, dy, c):
    d0 = dx * pts[0][0] + dy * pts[0][1] - c
    d1 = dx * pts[1][0] + dy * pts[1][1] - c
    out = []
    if d0 >= 0.0:
        out.append(pts[0])
    if d1 >= 0.0:
        out.append(pts[1])
    if d0 * d1 < 0.0:
        t = d0 / (d0 - d1)
        out.append((pts[0][0] + t * (pts[1][0] - pts[0][0]),
                    pts[0][1] + t * (pts[1][1] - pts[0][1])))
    return out


def poly_poly(a, b):
    sep_a, ia = _max_sep(a, b)
    if sep_a > MARGIN:
        return None
    sep_b, ib = _max_sep(b, a)
    if sep_b > MARGIN:
        return None
    if sep_b > sep_a + 1e-4:
        ref, inc, iref, flip = b, a, ib, True
    else:
        ref, inc, iref, flip = a, b, ia, False
    nx, ny = ref.wn[iref]
    best = 1e18
    ii = 0
    for i, (mx, my) in enumerate(inc.wn):
        d = nx * mx + ny * my
        if d < best:
            best = d
            ii = i
    nv = len(inc.wv)
    p1 = inc.wv[ii]
    p2 = inc.wv[(ii + 1) % nv]
    v1 = ref.wv[iref]
    v2 = ref.wv[(iref + 1) % len(ref.wv)]
    tx, ty = v2[0] - v1[0], v2[1] - v1[1]
    ln = math.hypot(tx, ty) or 1.0
    tx, ty = tx / ln, ty / ln
    pts = _clip_ge([p1, p2], tx, ty, tx * v1[0] + ty * v1[1])
    if len(pts) < 2:
        return None
    pts = _clip_ge(pts, -tx, -ty, -(tx * v2[0] + ty * v2[1]))
    if len(pts) < 2:
        return None
    front = nx * v1[0] + ny * v1[1]
    out = []
    for px, py in pts:
        sep = nx * px + ny * py - front
        if sep <= MARGIN:
            out.append((px - nx * sep * 0.5, py - ny * sep * 0.5, -sep))
    if not out:
        return None
    if flip:
        nx, ny = -nx, -ny
    return nx, ny, out


def collide(a, b):
    if a.kind == "circle":
        if b.kind == "circle":
            return circle_circle(a, b)
        m = poly_circle(b, a)
        if m is None:
            return None
        return -m[0], -m[1], m[2]
    if b.kind == "circle":
        return poly_circle(a, b)
    return poly_poly(a, b)

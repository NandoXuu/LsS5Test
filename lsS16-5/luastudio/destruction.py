# -*- coding: utf-8 -*-
import math

from .lua import LuaTable

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except Exception:
    HAS_PIL = False


def _vec(x, y, z=0.0):
    t = LuaTable()
    x = float(x); y = float(y); z = float(z)
    t.set("x", x); t.set("y", y); t.set("z", z)
    t.set(1.0, x); t.set(2.0, y); t.set(3.0, z)
    return t


def image_size(path, fallback=(128, 128)):
    if not HAS_PIL or not path:
        return fallback
    try:
        with PILImage.open(path) as im:
            return im.size
    except Exception:
        return fallback


def grid_dims(fragments):
    n = max(1, int(fragments))
    side = max(1, int(round(math.sqrt(n))))
    return side, side


def build_grid(w, h, cols, rows):
    cols = max(1, int(cols))
    rows = max(1, int(rows))
    verts = []
    uvs = []
    for r in range(rows + 1):
        for c in range(cols + 1):
            verts.append([w * c / float(cols), h * r / float(rows)])
            uvs.append([c / float(cols), 1.0 - r / float(rows)])
    tris = []
    stride = cols + 1
    for r in range(rows):
        for c in range(cols):
            a = r * stride + c
            b = a + 1
            d = a + stride
            e = d + 1
            tris.append((a, b, e))
            tris.append((a, e, d))
    return verts, uvs, tris


def group_pieces(cols, rows, fragments):
    n_cells = max(1, cols * rows)
    target = max(1, min(int(fragments), n_cells))
    chunk = max(1, n_cells // target)
    pieces = []
    i = 0
    while i < n_cells:
        j = min(i + chunk, n_cells)
        tri = []
        for cell in range(i, j):
            tri.append(cell * 2)
            tri.append(cell * 2 + 1)
        pieces.append(tri)
        i = j
    return pieces


def build_instance_mesh(inst, resolve_fn, fragments=None):
    src = str(inst.props.get("Source") or "")
    path = resolve_fn(src) if src else None
    iw, ih = image_size(path, (128, 128))
    inst.props["Size"] = _vec(iw, ih, 1)
    if fragments is None:
        fragments = inst.props.get("Fragments") or 24
    fragments = float(fragments)
    inst.props["Fragments"] = fragments
    cols, rows = grid_dims(fragments)
    verts, uvs, tris = build_grid(float(iw), float(ih), cols, rows)
    pieces = group_pieces(cols, rows, fragments)
    inst._mesh_vertices = verts
    inst._mesh_uvs = uvs
    inst._mesh_tris = tris
    inst._mesh_pieces = pieces
    inst._mesh_cols = cols
    inst._mesh_rows = rows
    inst._render_tris = [
        [(verts[i][0] / float(iw), verts[i][1] / float(ih), uvs[i][0], uvs[i][1]) for i in tri]
        for tri in tris
    ]


def piece_box(verts, tris, uvs, tri_indices):
    idxs = []
    for ti in tri_indices:
        idxs.extend(tris[ti])
    if not idxs:
        return None
    xs = [verts[i][0] for i in idxs]
    ys = [verts[i][1] for i in idxs]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    bw = max(max_x - min_x, 1.0)
    bh = max(max_y - min_y, 1.0)
    render_tris = []
    for ti in tri_indices:
        tri_pts = []
        for vi in tris[ti]:
            vx, vy = verts[vi]
            u, v = uvs[vi]
            tri_pts.append(((vx - min_x) / bw, (vy - min_y) / bh, u, v))
        render_tris.append(tri_pts)
    return min_x, min_y, bw, bh, render_tris


def cut_pieces(verts, tris, pieces, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return pieces

    def side(vi):
        vx, vy = verts[vi]
        return dx * (vy - y1) - dy * (vx - x1)

    new_pieces = []
    for tri_indices in pieces:
        side_a, side_b = [], []
        for ti in tri_indices:
            svals = [side(vi) for vi in tris[ti]]
            positives = sum(1 for s in svals if s >= 0)
            if positives >= 2:
                side_a.append(ti)
            else:
                side_b.append(ti)
        if side_a:
            new_pieces.append(side_a)
        if side_b:
            new_pieces.append(side_b)
    return new_pieces or pieces

# -*- coding: utf-8 -*-
"""Calculo central de spritesheet (Columns x Rows x Frame) para `create.image`.

Fonte UNICA da verdade para o recorte de frame: o mesmo indice/UV e usado
pelo `Source` (albedo) e pelo `NormalMap`. O recorte e normalizado (0..1) e
baseado apenas na divisao logica Columns x Rows, entao o NormalMap pode ter
resolucao diferente do Source, desde que tenha a mesma grade.

Modulo puro (sem Kivy) para poder ser testado sem janela/GPU.
"""

# tolerancia na comparacao de proporcao Source x NormalMap (2%)
ASPECT_TOLERANCE = 0.02


def grid_from_props(props):
    """(cols, rows) validos (>= 1) a partir das props de um `image`."""
    cols = max(1, int(props.get("Columns") or 1))
    rows = max(1, int(props.get("Rows") or 1))
    return cols, rows


def frame_index(frame, cols, rows):
    """Indice inteiro do frame, com wrap em [0, cols*rows)."""
    total = max(1, int(cols)) * max(1, int(rows))
    return int(float(frame or 0)) % total


def frame_uvs(frame, cols, rows):
    """tex_coords (u0,v0,u1,v0,u1,v1,u0,v1) do frame, ou None se a imagem
    nao e um spritesheet (cols == rows == 1)."""
    cols, rows = max(1, int(cols)), max(1, int(rows))
    if cols <= 1 and rows <= 1:
        return None
    idx = frame_index(frame, cols, rows)
    fx, fy = idx % cols, idx // cols
    u0, u1 = fx / float(cols), (fx + 1) / float(cols)
    v1, v0 = 1.0 - fy / float(rows), 1.0 - (fy + 1) / float(rows)
    return (u0, v0, u1, v0, u1, v1, u0, v1)


def frame_uvs_from_props(props):
    """UVs do frame ATUAL do objeto. E o unico ponto onde o renderer calcula
    o frame; o resultado e passado tanto ao Source quanto ao NormalMap."""
    cols, rows = grid_from_props(props)
    return frame_uvs(props.get("Frame"), cols, rows)


def aspect_mismatch(size_a, size_b, tol=ASPECT_TOLERANCE):
    """True se duas texturas (w, h) tem proporcao diferente. Com a mesma
    grade Columns x Rows, isso significa que os frames nao se alinham."""
    try:
        aw, ah = float(size_a[0]), float(size_a[1])
        bw, bh = float(size_b[0]), float(size_b[1])
    except (TypeError, ValueError, IndexError):
        return False
    if min(aw, ah, bw, bh) <= 0:
        return False
    ra, rb = aw / ah, bw / bh
    return abs(ra - rb) / max(ra, rb) > tol

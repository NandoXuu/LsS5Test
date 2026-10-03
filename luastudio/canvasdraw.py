# -*- coding: utf-8 -*-
"""Immediate-mode drawing: contexto `draw` passado pro callback `OnDraw`
de um `create.canvas.Nome`.

Isso e o que da "liberdade" pra construir interface: em vez de montar uma
arvore de nodes (button, frame, label...) o script desenha ele mesmo,
quadro a quadro, formas primitivas (linha, arco, circulo, poligono, texto)
num espaco local ao canvas - exatamente o mesmo papel do `_draw()` +
`draw_arc/draw_line/draw_circle` de outras engines (ex.: Godot's Control).

Convencao de coordenadas: igual ao resto do LuaStudio - (0,0) e o canto
superior esquerdo do canvas, X cresce pra direita, Y cresce pra baixo.
Angulos em graus, 0 aponta pra direita (3h) e crescem no sentido horario
(pois Y cresce pra baixo) - mesma convencao usada nos exemplos de
draw_arc de outras engines, entao um `start_angle=0, end_angle=180` da o
semicirculo de BAIXO, igual no exemplo original."""

from kivy.graphics import Color, Line, Rectangle, RoundedRectangle, Ellipse, Mesh
from kivy.core.text import Label as CoreLabel

from .lua import LuaTable, LuaError, tostring, truthy
from .api import to_color, safe_float


class CanvasDrawContext(object):
    """Um objeto novo desses e criado a cada frame, pra cada `canvas` que
    tiver `OnDraw` definido, e passado como segundo argumento do callback:

        create.canvas.Medidor{ Size = {160, 160}, OnDraw = function(self, draw)
            draw.arc(80, 80, 70, 0, 180, "purple", 14)
        end }

    Todos os metodos desenham IMEDIATAMENTE no frame atual (nao criam
    nenhuma Instance nova na cena) e aceitam cor no mesmo formato do resto
    da API (nome tipo "purple", "#rrggbb"/"#rrggbbaa", ou {r,g,b[,a]})."""

    __slots__ = ("_stage", "_ox", "_oy")

    def __init__(self, stage, origin_x, origin_y):
        self._stage = stage
        self._ox = origin_x
        self._oy = origin_y

    # -------------------------------------------------- integracao Lua
    _METHODS = ("line", "rect", "rect_outline", "circle", "ring", "arc",
                "polygon", "polyline", "text", "color")

    def lua_index(self, key):
        name = str(key)
        if name in self._METHODS:
            return getattr(self, "m_" + name)
        return None

    def lua_newindex(self, key, value):
        raise LuaError("draw.%s e somente leitura (contexto de desenho)" % key)

    # -------------------------------------------------------- utilidades
    def _pt(self, lx, ly):
        """Converte um ponto local do canvas (Y pra baixo) pra coordenada
        real de desenho (Kivy, Y pra cima) - mesma logica de Stage.to_stage,
        so que com origem no canto do canvas em vez do canto do Stage."""
        return self._stage.to_stage(self._ox + safe_float(lx), self._oy + safe_float(ly))

    @staticmethod
    def _angles(start_deg, end_deg):
        """Converte um intervalo de angulos "estilo Godot" (0=direita,
        cresce no sentido horario porque Y e pra baixo) pro intervalo que
        o Kivy espera (0=direita, cresce sentido anti-horario, Y pra
        cima)."""
        a1 = safe_float(start_deg)
        a2 = safe_float(end_deg)
        k1, k2 = -a2, -a1
        if k1 > k2:
            k1, k2 = k2, k1
        return k1, k2

    def _flatten_points(self, points):
        """Aceita uma lista Lua de pontos como {{x=..,y=..}, ...} ou
        {x1,y1, x2,y2, ...} e devolve uma lista de pontos ja convertidos
        pro espaco de desenho."""
        pts = []
        if not isinstance(points, LuaTable):
            return pts
        arr = points.ipairs_list()
        if not arr:
            return pts
        if isinstance(arr[0], LuaTable):
            for p in arr:
                px = p.get("x")
                py = p.get("y")
                if px is None:
                    px = p.get(1.0)
                if py is None:
                    py = p.get(2.0)
                pts.append(self._pt(px, py))
        else:
            flat = [safe_float(v) for v in arr]
            for i in range(0, len(flat) - 1, 2):
                pts.append(self._pt(flat[i], flat[i + 1]))
        return pts

    # ------------------------------------------------------- primitivas
    def m_color(self, color=None, *_a):
        """draw.color(cor) - muda a cor usada pelas formas seguintes ate
        a proxima chamada de cor (util pra desenhar varias formas com a
        mesma cor sem repetir o parametro)."""
        Color(*to_color(color))

    def m_line(self, x1=0, y1=0, x2=0, y2=0, color=None, thickness=1.5, *_a):
        px1, py1 = self._pt(x1, y1)
        px2, py2 = self._pt(x2, y2)
        if color is not None:
            Color(*to_color(color))
        Line(points=[px1, py1, px2, py2], width=safe_float(thickness, 1.5))

    def m_rect(self, x=0, y=0, w=0, h=0, color=None, radius=0.0, *_a):
        w = safe_float(w); h = safe_float(h)
        px, py = self._pt(x, safe_float(y) + h)
        if color is not None:
            Color(*to_color(color))
        r = safe_float(radius)
        if r > 0:
            RoundedRectangle(pos=(px, py), size=(w, h), radius=[r])
        else:
            Rectangle(pos=(px, py), size=(w, h))

    def m_rect_outline(self, x=0, y=0, w=0, h=0, color=None, thickness=1.5, radius=0.0, *_a):
        w = safe_float(w); h = safe_float(h)
        px, py = self._pt(x, safe_float(y) + h)
        if color is not None:
            Color(*to_color(color))
        r = max(safe_float(radius), 0.01)
        Line(rounded_rectangle=(px, py, w, h, r), width=safe_float(thickness, 1.5))

    def m_circle(self, cx=0, cy=0, radius=0, color=None, *_a):
        """Circulo CHEIO. Pra so o contorno, use draw.ring()."""
        pcx, pcy = self._pt(cx, cy)
        r = safe_float(radius)
        if color is not None:
            Color(*to_color(color))
        Ellipse(pos=(pcx - r, pcy - r), size=(r * 2, r * 2))

    def m_ring(self, cx=0, cy=0, radius=0, color=None, thickness=2.0, segments=64, *_a):
        """Contorno de um circulo completo (equivalente a um arco de 0 a
        360). Boa base pra medidores/barras de carregamento circulares."""
        pcx, pcy = self._pt(cx, cy)
        r = safe_float(radius)
        if color is not None:
            Color(*to_color(color))
        Line(circle=(pcx, pcy, r, 0, 360, max(3, int(segments))),
             width=safe_float(thickness, 2.0))

    def m_arc(self, cx=0, cy=0, radius=0, start_deg=0, end_deg=0, color=None,
             thickness=2.0, segments=48, filled=False, *_a):
        """draw.arc(cx, cy, raio, angulo_inicio, angulo_fim, cor, espessura,
        segmentos, preenchido). Angulos em graus: 0 = direita, cresce no
        sentido horario (0->180 = semicirculo de baixo, igual Godot)."""
        pcx, pcy = self._pt(cx, cy)
        r = safe_float(radius)
        k1, k2 = self._angles(start_deg, end_deg)
        if color is not None:
            Color(*to_color(color))
        if truthy(filled):
            Ellipse(pos=(pcx - r, pcy - r), size=(r * 2, r * 2),
                    angle_start=k1, angle_end=k2)
        else:
            Line(circle=(pcx, pcy, r, k1, k2, max(2, int(segments))),
                 width=safe_float(thickness, 2.0))

    def m_polygon(self, points=None, color=None, *_a):
        """Poligono CHEIO (convexo - desenhado como leque de triangulos a
        partir do primeiro ponto). points: {{x=..,y=..}, ...} ou
        {x1,y1, x2,y2, ...}."""
        pts = self._flatten_points(points)
        n = len(pts)
        if n < 3:
            return
        if color is not None:
            Color(*to_color(color))
        flat = []
        for p in pts:
            flat.extend([p[0], p[1], 0, 0])
        indices = []
        for i in range(1, n - 1):
            indices.extend([0, i, i + 1])
        Mesh(vertices=flat, indices=indices, mode="triangles")

    def m_polyline(self, points=None, color=None, thickness=1.5, closed=False, *_a):
        """Contorno ligando os pontos em sequencia (sem preencher)."""
        pts = self._flatten_points(points)
        if len(pts) < 2:
            return
        if color is not None:
            Color(*to_color(color))
        flat = [c for p in pts for c in p]
        Line(points=flat, width=safe_float(thickness, 1.5), close=truthy(closed))

    def m_text(self, x=0, y=0, text="", color=None, size=20.0, font=None, align="left", *_a):
        """draw.text(x, y, texto, cor, tamanho, fonte, alinhamento).
        (x,y) e o ponto de ancora; `align` decide se o texto comeca, fica
        centrado, ou termina nesse ponto ("left"/"center"/"right")."""
        px, py = self._pt(x, y)
        fs = safe_float(size, 20.0)
        txt = tostring(text)
        if not txt:
            return
        kw = dict(text=txt, font_size=fs, color=to_color(color, (1, 1, 1, 1)))
        font_path = None
        if font:
            font_path = self._stage.runtime.fonts.get(tostring(font))
        if font_path:
            kw["font_name"] = font_path
        lbl = CoreLabel(**kw)
        lbl.refresh()
        tex = lbl.texture
        align = str(align or "left").lower()
        tx = px
        if align == "center":
            tx = px - tex.width / 2.0
        elif align == "right":
            tx = px - tex.width
        Color(1, 1, 1, 1)
        Rectangle(pos=(tx, py - tex.height), size=tex.size, texture=tex)

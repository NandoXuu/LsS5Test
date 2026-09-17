# -*- coding: utf-8 -*-
"""Paleta de cores + widgets reutilizaveis da IDE (nao afeta o app gerado
pelo script Lua - so a interface do editor em si)."""

from kivy.uix.button import Button
from kivy.graphics import Color, RoundedRectangle, Rectangle
from kivy.properties import ListProperty, NumericProperty

# ---------------------------------------------------------------- paleta
BG = (0.071, 0.078, 0.102, 1)         # fundo geral da janela
SURFACE = (0.114, 0.125, 0.165, 1)    # paineis (toolbar, barra de simbolos)
SURFACE_2 = (0.165, 0.180, 0.235, 1)  # botoes neutros
SURFACE_HOVER = (0.205, 0.220, 0.280, 1)
BORDER = (0.22, 0.24, 0.32, 1)

TEXT = (0.93, 0.95, 1, 1)
TEXT_DIM = (0.52, 0.57, 0.68, 1)

ACCENT = (0.30, 0.55, 0.95, 1)        # azul (Palco / acao principal)
PLAY = (0.16, 0.68, 0.42, 1)          # verde (Play)
STOP = (0.91, 0.33, 0.40, 1)          # vermelho-coral (Stop)
WARN = (0.95, 0.66, 0.25, 1)          # laranja (Perms)

EDITOR_BG = (0.094, 0.104, 0.145, 1)
CONSOLE_BG = (0.055, 0.062, 0.086, 1)
CURSOR = (0.45, 0.75, 1, 1)


class RoundButton(Button):
    """Botao flat com cantos arredondados de verdade (em vez do bevel
    quadrado padrao do Kivy) e um leve escurecimento ao pressionar."""

    bg_color = ListProperty(list(SURFACE_2))
    radius = NumericProperty(14)

    def __init__(self, **kw):
        kw.setdefault("background_normal", "")
        kw.setdefault("background_down", "")
        kw.setdefault("background_color", (0, 0, 0, 0))
        kw.setdefault("color", TEXT)
        Button.__init__(self, **kw)
        with self.canvas.before:
            self._c = Color(*self.bg_color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                          radius=[self.radius])
        self.bind(pos=self._sync, size=self._sync, state=self._sync,
                  bg_color=self._sync, radius=self._sync)

    def _sync(self, *_a):
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._rect.radius = [self.radius]
        r, g, b, a = self.bg_color
        if self.state == "down":
            r, g, b = r * 0.78, g * 0.78, b * 0.78
        self._c.rgba = (r, g, b, a)


class Panel(object):
    """Mixin simples: desenha um fundo solido atras de um layout (pra
    diferenciar toolbar/barra de simbolos do resto da tela)."""

    def paint_panel(self, widget, color=SURFACE):
        with widget.canvas.before:
            Color(*color)
            rect = Rectangle(pos=widget.pos, size=widget.size)
        widget.bind(pos=lambda *a: setattr(rect, "pos", widget.pos),
                   size=lambda *a: setattr(rect, "size", widget.size))
        return rect

# -*- coding: utf-8 -*-
"""Paleta de cores + widgets reutilizaveis da IDE (nao afeta o app gerado
pelo script Lua - so a interface do editor em si).

Visual: dark neutro (cinza grafite), com UMA cor de destaque suave. As
cores de estado (play/stop/aviso) sao dessaturadas pra nao "gritar".
Tambem tem os helpers de animacao leve (fade, botao, popup)."""

import os

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Rectangle
from kivy.properties import ListProperty, NumericProperty
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.metrics import dp
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex

# ---------------------------------------------------------------- paleta
BG = (0.067, 0.067, 0.075, 1)          # fundo geral da janela
SURFACE = (0.098, 0.098, 0.110, 1)     # paineis (toolbar, cards, barra de simbolos)
SURFACE_2 = (0.145, 0.145, 0.160, 1)   # botoes neutros
SURFACE_HOVER = (0.190, 0.190, 0.210, 1)
BORDER = (0.180, 0.180, 0.200, 1)

TEXT = (0.91, 0.91, 0.93, 1)
TEXT_DIM = (0.55, 0.55, 0.60, 1)

ACCENT = (0.40, 0.50, 0.85, 1)         # azul-acinzentado suave (acao principal)
PLAY = (0.30, 0.62, 0.46, 1)           # verde fosco (Play)
STOP = (0.80, 0.38, 0.40, 1)           # vermelho fosco (Stop / apagar)
WARN = (0.82, 0.66, 0.36, 1)           # ambar fosco (avisos)

EDITOR_BG = (0.082, 0.082, 0.090, 1)
CONSOLE_BG = (0.055, 0.055, 0.062, 1)
INPUT_BG = (0.075, 0.075, 0.085, 1)
CURSOR = (0.65, 0.72, 0.95, 1)


MONO_BG = (0.0, 0.0, 0.0, 1)
MONO_BG_DARK = (0.0, 0.0, 0.0, 1)
MONO_FG = (1.0, 1.0, 1.0, 1)
MONO_DIM = (0.36, 0.36, 0.38, 1)
MONO_SEL = (0.20, 0.20, 0.23, 1)
MONO_BTN = (0.10, 0.10, 0.11, 1)

INDENT_COLORS = [
    (1.000, 0.560, 0.760),  # rosa pastel vivo
    (0.420, 0.900, 1.000),  # ciano pastel
    (0.760, 0.680, 1.000),  # lilas pastel
    (0.500, 1.000, 0.720),  # verde menta
    (1.000, 0.850, 0.480),  # amarelo pastel
    (0.820, 0.560, 1.000),  # violeta
    (1.000, 0.680, 0.430),  # pêssego
    (0.520, 0.800, 1.000),  # azul pastel
]


def _build_tolerant(cls, optional, **kw):
    """Cria `cls(**kw)`; se essa versao do Kivy nao conhecer alguma
    propriedade OPCIONAL (so enfeite visual), tenta de novo sem ela em vez
    de derrubar o app."""
    kw = dict(kw)
    while True:
        try:
            return cls(**kw)
        except TypeError:
            dropped = False
            for key in optional:
                if key in kw:
                    kw.pop(key)
                    dropped = True
                    break
            if not dropped:
                raise


def hex_to_rgba(value, default=SURFACE_2):
    """'#RRGGBB' -> (r, g, b, a) do Kivy. Devolve `default` se invalido."""
    try:
        return tuple(get_color_from_hex(value))
    except Exception:
        return default


# ------------------------------------------------------------ animacoes
def fade_in(widget, delay=0.0, duration=0.22):
    """Fade-in leve de um widget (opcionalmente atrasado, pra escalonar
    varios itens - efeito 'cascata')."""
    widget.opacity = 0
    anim = Animation(opacity=1, d=duration, t="out_quad")
    if delay > 0:
        Clock.schedule_once(lambda *_a: anim.start(widget), delay)
    else:
        anim.start(widget)


def styled_popup(title, content, size_hint=(0.9, 0.8), **kw):
    """Popup flat, escuro, com fade-in rapido (em vez do popup padrao do
    Kivy, com a moldura em bevel)."""
    kw.setdefault("title_color", TEXT)
    kw.setdefault("title_size", 16)
    kw.setdefault("separator_color", BORDER)
    kw.setdefault("separator_height", 1)
    kw.setdefault("background", "")
    kw.setdefault("background_color", SURFACE)
    kw.setdefault("overlay_color", (0, 0, 0, 0.62))
    popup = _build_tolerant(Popup, ("overlay_color", "separator_height",
                                    "background"),
                            title=title, content=content, size_hint=size_hint, **kw)
    popup.opacity = 0
    popup.bind(on_pre_open=lambda *_a: Animation(
        opacity=1, d=0.16, t="out_quad").start(popup))
    return popup


def make_input(**kw):
    """TextInput flat combinando com o resto do tema."""
    kw.setdefault("multiline", False)
    kw.setdefault("background_normal", "")
    kw.setdefault("background_active", "")
    kw.setdefault("background_disabled_normal", "")
    kw.setdefault("background_color", INPUT_BG)
    kw.setdefault("foreground_color", TEXT)
    kw.setdefault("hint_text_color", TEXT_DIM[:3] + (0.7,))
    kw.setdefault("cursor_color", CURSOR)
    kw.setdefault("selection_color", ACCENT[:3] + (0.35,))
    kw.setdefault("padding", (14, 14, 14, 14))
    kw.setdefault("font_size", 16)
    return _build_tolerant(TextInput, ("hint_text_color", "background_disabled_normal",
                                       "selection_color"), **kw)


def paint_rounded(widget, color=SURFACE, radius=14, border=None, border_w=1):
    """Desenha um fundo arredondado (com borda fina opcional) atras de
    `widget`. Devolve a instrucao Color do preenchimento (pra trocar a cor
    depois, se precisar)."""
    with widget.canvas.before:
        if border:
            Color(*border)
            brect = RoundedRectangle(pos=widget.pos, size=widget.size,
                                     radius=[radius])
        else:
            brect = None
        fill = Color(*color)
        rect = RoundedRectangle(pos=widget.pos, size=widget.size,
                                radius=[radius])

    def _sync(*_a):
        x, y = widget.pos
        w, h = widget.size
        if brect is not None:
            brect.pos = (x, y)
            brect.size = (w, h)
            rect.pos = (x + border_w, y + border_w)
            rect.size = (max(w - 2 * border_w, 0), max(h - 2 * border_w, 0))
        else:
            rect.pos = (x, y)
            rect.size = (w, h)

    widget.bind(pos=_sync, size=_sync)
    _sync()
    return fill


class RoundButton(Button):
    """Botao flat com cantos arredondados de verdade (em vez do bevel
    quadrado padrao do Kivy). Ao tocar, a cor escurece com uma transicao
    suave (em vez de piscar de uma vez)."""

    bg_color = ListProperty(list(SURFACE_2))
    radius = NumericProperty(14)
    press_t = NumericProperty(0.0)   # 0 = solto, 1 = pressionado (animado)

    def __init__(self, **kw):
        kw.setdefault("background_normal", "")
        kw.setdefault("background_down", "")
        kw.setdefault("background_color", (0, 0, 0, 0))
        kw.setdefault("color", TEXT)
        Button.__init__(self, **kw)
        with self.canvas.before:
            self._c = Color(*self._current_rgba())
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                          radius=[self.radius])
        self.bind(pos=self._sync_geom, size=self._sync_geom,
                  radius=self._sync_geom,
                  bg_color=self._sync_color, press_t=self._sync_color,
                  disabled=self._sync_color, state=self._on_state)

    def _current_rgba(self):
        r, g, b, a = self.bg_color
        k = 1.0 - 0.22 * self.press_t
        if self.disabled:
            a = a * 0.45
        return (r * k, g * k, b * k, a)

    def _sync_geom(self, *_a):
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._rect.radius = [self.radius]

    def _sync_color(self, *_a):
        self._c.rgba = self._current_rgba()

    def _on_state(self, _w, value):
        down = (value == "down")
        Animation.cancel_all(self, "press_t")
        Animation(press_t=1.0 if down else 0.0,
                  d=0.07 if down else 0.20, t="out_quad").start(self)


ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")

class IconButton(RoundButton):
    """RoundButton com icone PNG real. O icone e desenhado como imagem,
    evitando emojis/glifos dependentes da fonte do dispositivo."""
    def __init__(self, icon=None, icon_size=22, icon_left=True, **kw):
        self.icon_name = icon
        self.icon_size = dp(icon_size)
        self.icon_left = icon_left
        super().__init__(**kw)
        self._icon_img = None
        if icon:
            path = os.path.join(ICON_DIR, str(icon) + ".png")
            if os.path.isfile(path):
                self._icon_img = Image(source=path, size_hint=(None, None),
                                       size=(self.icon_size, self.icon_size),
                                       allow_stretch=True, keep_ratio=True)
                self.add_widget(self._icon_img)
                self.bind(pos=self._sync_icon, size=self._sync_icon)
                Clock.schedule_once(lambda *_: self._sync_icon(), 0)

    def _sync_icon(self, *_):
        if not self._icon_img:
            return
        if self.text:
            self._icon_img.pos = (self.x + dp(8), self.y + (self.height - self.icon_size) / 2)
            self.text_size = (max(0, self.width - self.icon_size - dp(18)), None)
            self.padding = (self.icon_size + dp(14), 0)
        else:
            self._icon_img.pos = (self.x + (self.width - self.icon_size) / 2,
                                  self.y + (self.height - self.icon_size) / 2)



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

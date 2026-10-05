# -*- coding: utf-8 -*-
"""Sistema de tela: fullscreen + proporcao de tela fixa (aspect ratio),
igual ao "modo cinema" de emuladores/engines - o jogo e desenhado numa
caixa com a proporcao escolhida (16:9, 9:16, 4:3...), essa caixa fica
CENTRALIZADA na tela real, escalada de forma UNIFORME (mesma escala em X
e Y - nunca estica/deforma) e o espaco sobrando vira barras (letterbox
horizontal ou pillarbox vertical, dependendo do caso).

Tambem aplica o travamento de orientacao (retrato/paisagem/automatico) e
o fullscreen de verdade (Window + imersivo no Android), reaproveitando o
que ja existe em `permissions.py`.

Usado por:
  - `player_app.py`   - roda o jogo exportado (.Lsp) nessa caixa.
  - `app.py`           - preview do Palco dentro do proprio editor (so a
                          proporcao/letterbox; fullscreen real so faz
                          sentido rodando o jogo de verdade, no Player).
"""

from kivy.uix.floatlayout import FloatLayout
from kivy.graphics import Color, Rectangle

from . import permissions as perms

try:
    from kivy.core.window import Window
except Exception:
    Window = None


# proporcoes prontas (largura, altura) na orientacao LANDSCAPE - pra
# portrait a gente so inverte width/height na hora de calcular.
ASPECT_PRESETS = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "21:9": (21, 9),
    "1:1": (1, 1),
    "auto": None,   # sem proporcao fixa: usa o tamanho real da janela
}
ASPECT_ORDER = ["16:9", "4:3", "1:1", "21:9", "9:16", "3:4", "auto"]

ORIENTATIONS = ("landscape", "portrait", "auto")
FIT_MODES = ("letterbox", "pixel_perfect")


def default_screen_config():
    return {"fullscreen": True, "aspect": "16:9", "orientation": "landscape",
            "fit": "letterbox"}


def resolve_virtual_size(aspect, orientation, base=720.0):
    """(largura, altura) alvo pra uma proporcao (ex: '16:9') numa
    orientacao (landscape/portrait/auto)."""
    ratio = ASPECT_PRESETS.get(str(aspect or "16:9"))
    if ratio is None:
        if Window is not None and Window.height:
            return float(Window.width), float(Window.height)
        return 1280.0, 720.0
    rw, rh = ratio
    orientation = str(orientation or "landscape")
    if orientation == "portrait" and rw > rh:
        rw, rh = rh, rw
    elif orientation == "landscape" and rh > rw:
        rw, rh = rh, rw
    h = float(base)
    w = h * (rw / float(rh))
    return w, h


def apply_screen_mode(cfg):
    """Aplica fullscreen de verdade + trava a orientacao, a partir de um
    dict tipo {'fullscreen':True,'orientation':'landscape',...}. Chamado
    na hora de RODAR o jogo de verdade (LuaStudio Player) - dentro do
    editor o preview so usa a proporcao (ver FitContainer), sem mexer na
    janela real do app."""
    cfg = cfg or {}
    orientation = str(cfg.get("orientation") or "auto")
    if orientation in ("landscape", "portrait"):
        perms.set_orientation(orientation)
    else:
        perms.set_orientation("sensor")
    if bool(cfg.get("fullscreen", True)):
        if Window is not None:
            try:
                Window.fullscreen = "auto"
            except Exception:
                pass
        perms.hide_system_bars()
    elif Window is not None:
        try:
            Window.fullscreen = False
        except Exception:
            pass


def restore_screen_mode():
    """Desfaz `apply_screen_mode`: solta a trava de orientacao, sai do
    fullscreen e devolve as barras do sistema. Chamado quando o Play
    (tela de jogo do proprio editor) termina."""
    try:
        perms.set_orientation("sensor")
    except Exception:
        pass
    if Window is not None:
        try:
            Window.fullscreen = False
        except Exception:
            pass
    try:
        perms.show_system_bars()
    except Exception:
        pass


class FitContainer(FloatLayout):
    """Encaixa um widget filho (Stage) numa caixa com proporcao fixa,
    centralizada, com escala UNIFORME (nunca estica) - o resto vira
    barras da cor `bars_color`. `pixel_perfect=True` arredonda a escala
    pro inteiro mais proximo (bom pra jogos/tilemaps em pixel art, evita
    tiles borrados/com linhas de costura por escala fracionaria)."""

    def __init__(self, child, virtual_w=1280.0, virtual_h=720.0,
                bars_color=(0, 0, 0, 1), pixel_perfect=False, **kw):
        FloatLayout.__init__(self, **kw)
        self.virtual_w = float(virtual_w or 1280.0)
        self.virtual_h = float(virtual_h or 720.0)
        self.pixel_perfect = bool(pixel_perfect)
        with self.canvas.before:
            self._bars_c = Color(*bars_color)
            self._bars_rect = Rectangle(pos=self.pos, size=self.size)
        self.child = child
        child.size_hint = (None, None)
        self.add_widget(child)
        self.bind(pos=self._refit, size=self._refit)
        self._refit()

    def set_bars_color(self, rgba):
        self._bars_c.rgba = rgba

    def set_virtual_size(self, w, h, pixel_perfect=None):
        self.virtual_w = float(w or self.virtual_w)
        self.virtual_h = float(h or self.virtual_h)
        if pixel_perfect is not None:
            self.pixel_perfect = bool(pixel_perfect)
        self._refit()

    def set_from_config(self, cfg, base=720.0):
        """Configura direto a partir de um dict `project.screen` (aspect +
        orientation + fit)."""
        cfg = cfg or {}
        w, h = resolve_virtual_size(cfg.get("aspect"), cfg.get("orientation"), base=base)
        self.set_virtual_size(w, h, pixel_perfect=(cfg.get("fit") == "pixel_perfect"))

    def _refit(self, *_a):
        self._bars_rect.pos = self.pos
        self._bars_rect.size = self.size
        if self.width <= 0 or self.height <= 0 or self.virtual_w <= 0 or self.virtual_h <= 0:
            return
        scale = min(self.width / self.virtual_w, self.height / self.virtual_h)
        if self.pixel_perfect and scale > 1.0:
            scale = float(int(scale)) or 1.0
        w = self.virtual_w * scale
        h = self.virtual_h * scale
        self.child.size = (w, h)
        self.child.pos = (self.x + (self.width - w) / 2.0, self.y + (self.height - h) / 2.0)

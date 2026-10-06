# -*- coding: utf-8 -*-
"""Splash screens de carregamento (engine, projeto e jogo).

A engine e pesada pra rodar no celular, entao antes de cada carregamento
pesado aparece uma splash: a imagem `icons/splash.png` nasce invisivel e
pequena no centro da tela, cresce com fade in, FICA ali enquanto o
trabalho pesado roda e so depois sai com fade out.

Como o Kivy e single-thread, o trabalho pesado trava a tela enquanto roda.
Por isso a ordem e sempre:

    1. splash aparece e toca a animacao de entrada (tela ainda fluida)
    2. so DEPOIS da animacao o trabalho pesado roda (a logo ja esta
       inteira na tela, entao o congelamento nao aparece como "travada")
    3. fade out revelando o que foi carregado

Uso:

    from .splash import Splash
    Splash(bg=theme.BG).run(work=minha_funcao_pesada)

Se `splash.png` nao existir (ainda), a splash usa o texto `fallback_text`
no lugar da imagem - nunca derruba o carregamento por causa disso.
"""

import os

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.widget import Widget

try:
    from kivy.core.window import Window
except Exception:  # pragma: no cover - ambiente sem janela
    Window = None

SPLASH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "icons", "splash.png")

INTRO_TIME = 0.8      # fade in + crescer
OUTRO_TIME = 0.5      # fade out
BG_FADE_TIME = 0.2    # fundo cobrindo a tela atual
MIN_HOLD = 0.2        # tempo minimo com a logo inteira depois do trabalho
START_SCALE = 0.35    # tamanho inicial (fracao do tamanho final)
END_SCALE = 1.0
OUTRO_SCALE = 1.06    # leve "estufada" na saida
BOX_FRACTION = 0.5    # a logo cabe numa caixa de 50% x 50% da tela

# splashes em andamento (mantem uma referencia forte ate o fade out acabar)
_ACTIVE = set()


def _load_texture(path, fallback_text):
    """Textura da splash. Sem arquivo (ou com erro), vira um texto simples."""
    if path and os.path.isfile(path):
        try:
            from kivy.core.image import Image as CoreImage
            tex = CoreImage(path).texture
            if tex is not None:
                return tex
        except Exception:
            pass
    if not fallback_text:
        return None
    try:
        from kivy.core.text import Label as CoreLabel
        lbl = CoreLabel(text=fallback_text, font_size=dp(40), bold=True)
        lbl.refresh()
        return lbl.texture
    except Exception:
        return None


class Splash(Widget):
    """Overlay de tela cheia (filho direto da Window, sempre por cima)."""

    logo_alpha = NumericProperty(0.0)
    logo_scale = NumericProperty(START_SCALE)
    bg_alpha = NumericProperty(0.0)

    def __init__(self, bg=(0, 0, 0, 1), image=SPLASH_PATH, fallback_text="LuaStudio",
                 **kw):
        Widget.__init__(self, **kw)
        self._bg_rgb = tuple(bg[:3])
        self._bg_max = float(bg[3]) if len(bg) > 3 else 1.0
        self._texture = _load_texture(image, fallback_text)
        self._work = None
        self._deferred = False
        self._on_done = None
        self._finished = False
        self._outro_started = False
        self._disposed = False
        self._shown = False

        with self.canvas:
            self._bg_color = Color(self._bg_rgb[0], self._bg_rgb[1],
                                   self._bg_rgb[2], 0)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
            self._logo_color = Color(1, 1, 1, 0)
            self._logo_rect = Rectangle(texture=self._texture, pos=(0, 0),
                                        size=(0, 0))
        self.bind(pos=self._redraw, size=self._redraw, logo_alpha=self._redraw,
                  logo_scale=self._redraw, bg_alpha=self._redraw)

    # ------------------------------------------------------------ desenho
    def _base_logo_size(self):
        tex = self._texture
        if tex is None or not self.width or not self.height:
            return 0.0, 0.0
        tw, th = float(tex.width), float(tex.height)
        if tw <= 0 or th <= 0:
            return 0.0, 0.0
        box_w = self.width * BOX_FRACTION
        box_h = self.height * BOX_FRACTION
        k = min(box_w / tw, box_h / th)   # "contain": nunca estica nem corta
        return tw * k, th * k

    def _redraw(self, *_a):
        self._bg_color.a = self.bg_alpha * self._bg_max
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        bw, bh = self._base_logo_size()
        w, h = bw * self.logo_scale, bh * self.logo_scale
        self._logo_rect.size = (w, h)
        self._logo_rect.pos = (self.center_x - w / 2.0, self.center_y - h / 2.0)
        self._logo_color.a = max(0.0, min(1.0, self.logo_alpha))

    # ------------------------------------------------------------- toques
    # enquanto a splash existe, ela engole os toques (nada por baixo reage)
    def on_touch_down(self, touch):
        return True

    def on_touch_move(self, touch):
        return True

    def on_touch_up(self, touch):
        return True

    # ---------------------------------------------------------------- fluxo
    def run(self, work=None, deferred=False, on_done=None):
        """Mostra a splash e roda `work` no meio dela.

        work     - funcao pesada (carregar engine/projeto/jogo). Roda DEPOIS
                   da animacao de entrada.
        deferred - se True, `work(done)` recebe uma funcao `done` e a splash
                   so sai quando `done()` for chamada (pra trabalho que
                   termina em frames futuros). Se False, sai assim que
                   `work()` retorna.
        on_done  - chamada depois que a splash sumiu.
        """
        self._work = work
        self._deferred = deferred
        self._on_done = on_done
        _ACTIVE.add(self)
        # 1 frame de atraso: quando chamada dentro de App.build(), a raiz do
        # app ainda nao entrou na Window - assim a splash entra por cima.
        Clock.schedule_once(self._start, 0)
        return self

    def _start(self, _dt):
        if Window is None:
            self._run_work(0)
            return
        self._bring_to_front()
        self._shown = True
        Animation(bg_alpha=1.0, d=BG_FADE_TIME, t="out_quad").start(self)
        intro = Animation(logo_alpha=1.0, logo_scale=END_SCALE, d=INTRO_TIME,
                          t="out_cubic")
        # 0.08s depois do fim da animacao: garante que o ultimo frame dela
        # foi desenhado antes do trabalho pesado travar a thread.
        intro.bind(on_complete=lambda *_a: Clock.schedule_once(self._run_work, 0.08))
        intro.start(self)

    def _bring_to_front(self):
        """(Re)coloca a splash como ultimo filho da Window: assim ela fica por
        cima de qualquer coisa que o trabalho pesado tenha adicionado."""
        if Window is None or self._disposed:
            return
        try:
            if self.parent is not None:
                Window.remove_widget(self)
            Window.add_widget(self)
        except Exception:
            pass

    def _run_work(self, _dt):
        if self._work is None:
            self._finish()
            return
        if self._deferred:
            try:
                self._work(self._finish)
            except Exception:
                self._report()
                self._finish()
            return
        try:
            self._work()
        except Exception:
            self._report()
        self._finish()

    @staticmethod
    def _report():
        import traceback
        print("[splash] erro durante o carregamento:\n%s" % traceback.format_exc())

    def _finish(self, *_a):
        """Fim do carregamento: segura a logo um instante e faz o fade out."""
        if self._finished:
            return
        self._finished = True
        Clock.schedule_once(self._outro, MIN_HOLD if self._shown else 0)

    def _outro(self, _dt):
        if self._outro_started:
            return
        self._outro_started = True
        if Window is None or not self._shown:
            self._dispose()
            return
        self._bring_to_front()
        out = Animation(logo_alpha=0.0, bg_alpha=0.0, logo_scale=OUTRO_SCALE,
                        d=OUTRO_TIME, t="in_quad")
        out.bind(on_complete=lambda *_a: self._dispose())
        out.start(self)

    def _dispose(self):
        if self._disposed:
            return
        self._disposed = True
        _ACTIVE.discard(self)
        try:
            if self.parent is not None:
                self.parent.remove_widget(self)
        except Exception:
            pass
        cb, self._on_done = self._on_done, None
        if cb is not None:
            try:
                cb()
            except Exception:
                self._report()


def show(work=None, bg=(0, 0, 0, 1), deferred=False, on_done=None,
         fallback_text="LuaStudio"):
    """Atalho: cria uma Splash e ja inicia."""
    return Splash(bg=bg, fallback_text=fallback_text).run(
        work=work, deferred=deferred, on_done=on_done)

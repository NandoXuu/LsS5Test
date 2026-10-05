# -*- coding: utf-8 -*-
"""Tempo do MUNDO separado do tempo da UI.

Dois relogios:
  - UI (real): sempre corre na velocidade normal. Menus, botoes, HUD,
    inputs, timers de UI e `app.onUIUpdate` usam ele.
  - MUNDO: o real multiplicado por `TimeScale` (e 0 enquanto pausado).
    Fisica, animacao de sprites, tweens, particulas, timers, camera e
    `app.onUpdate` usam ele.

Um objeto e considerado UI (usa o relogio real) quando:
  - tem `TimeLayer = "ui"` (ou `"world"` pra forcar o mundo), ou
  - sem TimeLayer: e um controle (button, label, slider, toggle,
    textbox...) ou tem `IgnoreCamera = true` (HUD preso na tela).

Modulo puro (sem Kivy) - testavel sem janela.
"""

MAX_TIME_SCALE = 20.0

# controles de interface: sempre no tempo da UI por padrao
UI_CLASSES = frozenset((
    "button", "label", "text", "slider", "toggle",
    "textbox", "textedit", "codeedit",
))

_CONFIG_KEYS = {"timescale": "TimeScale"}


def _truthy(v):
    return v is not None and v is not False and v != 0 and v != ""


class WorldTime(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.time_scale = 1.0
        self.paused = False
        self.pause_left = None      # segundos REAIS ate retomar (None = indefinido)
        self.on_resume = None       # callback Lua opcional de pause.world(s, fn)
        self.world_time = 0.0       # segundos de mundo decorridos
        self.ui_time = 0.0          # segundos reais decorridos

    # ------------------------------------------------------------ config
    def set_config(self, cfg):
        """Aplica so as chaves presentes. Devolve a lista de chaves
        desconhecidas (pro runtime avisar no log)."""
        unknown = []
        for key, value in cfg.items():
            canon = _CONFIG_KEYS.get(str(key).lower())
            if canon is None:
                unknown.append(str(key))
                continue
            if canon == "TimeScale":
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    continue
                if v != v:                      # NaN
                    continue
                self.time_scale = max(0.0, min(MAX_TIME_SCALE, v))
        return unknown

    def get_config(self):
        return {"TimeScale": self.time_scale}

    # ------------------------------------------------------------- pausa
    def pause(self, seconds=None, on_resume=None):
        try:
            secs = float(seconds) if seconds is not None else None
        except (TypeError, ValueError):
            secs = None
        if secs is not None and secs <= 0:
            return                              # pausa de 0s = nada
        self.paused = True
        self.pause_left = secs
        self.on_resume = on_resume

    def resume(self):
        """Retoma o mundo. Devolve o callback pendente (ou None)."""
        was = self.paused
        cb = self.on_resume
        self.paused = False
        self.pause_left = None
        self.on_resume = None
        return cb if was else None

    # ------------------------------------------------------------- frame
    def tick(self, real_dt):
        """Avanca os relogios. Devolve (world_dt, callback_de_retomada).
        A pausa temporizada conta em tempo REAL (nao e afetada por
        TimeScale), e o tempo que sobrou do frame ja corre no mundo."""
        real_dt = max(0.0, float(real_dt))
        self.ui_time += real_dt
        cb = None
        world_dt = 0.0
        if self.paused:
            if self.pause_left is not None:
                self.pause_left -= real_dt
                if self.pause_left <= 0.0:
                    leftover = -self.pause_left
                    cb = self.resume()
                    world_dt = leftover * self.time_scale
        else:
            world_dt = real_dt * self.time_scale
        self.world_time += world_dt
        return world_dt, cb

    # ---------------------------------------------------------- objetos
    @staticmethod
    def is_ui(obj):
        props = getattr(obj, "props", None)
        if props is None:
            return False
        layer = props.get("TimeLayer")
        if isinstance(layer, str) and layer.strip():
            return layer.strip().lower() in ("ui", "real", "unscaled")
        if getattr(obj, "cls", None) in UI_CLASSES:
            return True
        return _truthy(props.get("IgnoreCamera"))

    def dt_for(self, obj, world_dt, ui_dt):
        return ui_dt if self.is_ui(obj) else world_dt

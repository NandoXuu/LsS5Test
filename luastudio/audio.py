# -*- coding: utf-8 -*-
"""Audio via pygame.mixer, carregado SOB DEMANDA.

Nunca importe pygame no topo do modulo: no Pydroid 3 o pygame inicializa o
SDL2 e o Kivy deixa de encontrar um provider de janela.

Agora inclui: Mixer com buses/roteamento, Volume em dB, Pitch, EQ, DSP
(Reverb/Compressor) e Audio espacial (pan + atenuacao por distancia). Tudo
isso fica em audio_dsp.py; este arquivo cuida do ciclo de vida com o
pygame.mixer (load/play/stop) e aplica os parametros calculados.
"""

import math
import os

from . import audio_dsp as dsp

_mixer = None
_tried = False


def _get_mixer(log):
    """Importa apenas pygame.mixer (sem video) na primeira vez que precisar."""
    global _mixer, _tried
    if _tried:
        return _mixer
    _tried = True
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    try:
        import pygame.mixer as mixer  # noqa: WPS433
        mixer.pre_init(44100, -16, 2, 512)
        mixer.init()
        _mixer = mixer
    except Exception as ex:
        log("[audio] som desativado (%s)" % ex)
        _mixer = None
    return _mixer


class Audio(object):
    def __init__(self, log=None, base_dir="."):
        self.log = log or (lambda s: None)
        self.base_dir = base_dir
        self.cache = {}                 # path -> Sound original (sem DSP)
        self._processed_cache = {}      # (path, dsp_signature) -> Sound processado
        self.channels = {}              # nome do objeto -> Channel
        self.mixer_bus = dsp.Mixer(self.log)
        self.listener_pos = (0.0, 0.0, 0.0)
        self.listener_forward = (0.0, 0.0, 1.0)
        self.listener_vel = (0.0, 0.0, 0.0)
        # ---- HRTF 2D (pan X + elevacao Y por camera2d, em tempo real) ----
        self._hrtf_layer_cache = {}     # assinatura -> {"dry","muffled","bright"}
        self.hrtf_sources = {}          # nome do objeto -> estado (canais, smoothing)
        self.camera2d_pos = (0.0, 0.0)
        self.camera2d_zoom = 1.0

    @property
    def mixer(self):
        return _get_mixer(self.log)

    @property
    def ready(self):
        return self.mixer is not None

    def resolve(self, source):
        if not source:
            return None
        if os.path.isabs(source) and os.path.exists(source):
            return source
        p = os.path.join(self.base_dir, source)
        return p if os.path.exists(p) else None

    def load(self, source):
        mixer = self.mixer
        if mixer is None:
            return None
        path = self.resolve(source)
        if not path:
            self.log("[audio] arquivo nao encontrado: %s" % source)
            return None
        if path in self.cache:
            return self.cache[path]
        try:
            snd = mixer.Sound(path)
            self.cache[path] = snd
            return snd
        except Exception as ex:
            self.log("[audio] falha ao carregar %s: %s" % (source, ex))
            return None

    # -------------------------------------------------------------- DSP
    def _dsp_sound(self, path, base_snd, fx):
        """Aplica pitch/EQ/reverb/compressor e cacheia o resultado pela
        assinatura dos parametros, pra nao reprocessar o mesmo som toda vez."""
        if not fx:
            return base_snd
        sig = (path, tuple(sorted(fx.items())))
        cached = self._processed_cache.get(sig)
        if cached is not None:
            return cached
        snd = base_snd
        if fx.get("pitch"):
            snd = dsp.pitch_shift(snd, fx["pitch"], self.log)
        if any(fx.get(k) for k in ("eq_low", "eq_mid", "eq_high")):
            snd = dsp.apply_eq(snd, fx.get("eq_low", 0.0), fx.get("eq_mid", 0.0),
                               fx.get("eq_high", 0.0), log=self.log)
        if fx.get("reverb"):
            snd = dsp.apply_reverb(snd, mix=fx["reverb"], room_size=fx.get("reverb_room", 0.6),
                                   damping=fx.get("reverb_damping", 0.4), log=self.log)
        if fx.get("compress"):
            snd = dsp.apply_compressor(snd, threshold_db=fx.get("comp_threshold", -18.0),
                                       ratio=fx.get("comp_ratio", 4.0), log=self.log)
        self._processed_cache[sig] = snd
        return snd

    # -------------------------------------------------------------- play
    def play(self, inst, bus="SFX", fx=None, spatial=False):
        if not self.ready:
            self.log("[audio] play ignorado (mixer off): %s" % inst.name)
            return
        source = str(inst.props.get("Source") or "")
        base_snd = self.load(source)
        if base_snd is None:
            return
        path = self.resolve(source)
        snd = self._dsp_sound(path, base_snd, fx) if fx else base_snd
        try:
            src_vol = float(inst.props.get("Volume") or 1.0)
            self.mixer_bus.route(inst.name, bus)
            final_vol = self.mixer_bus.resolve_volume(inst.name, src_vol)

            pan = 0.0
            if spatial:
                pos = inst.pos() if hasattr(inst, "pos") else (0, 0, 0)
                params = dsp.spatial_params(self.listener_pos, self.listener_forward, pos,
                                            listener_vel=self.listener_vel)
                final_vol *= params["volume"]
                pan = params["pan"]

            loops = -1 if inst.props.get("Loop") else 0
            channel = snd.play(loops=loops)
            if channel is not None:
                if pan:
                    left, right = dsp.stereo_volumes(pan, final_vol)
                    channel.set_volume(left, right)
                else:
                    channel.set_volume(final_vol)
                self.channels[inst.name] = channel
        except Exception as ex:
            self.log("[audio] erro ao tocar: %s" % ex)

    def update_spatial(self, inst, min_dist=1.0, max_dist=30.0):
        """Chame a cada frame pra objetos 3D em movimento: reposiciona pan e
        volume no canal ja tocando, conforme o listener se move."""
        ch = self.channels.get(inst.name)
        if ch is None or not hasattr(inst, "pos"):
            return
        src_vol = float(inst.props.get("Volume") or 1.0)
        bus_vol = self.mixer_bus.resolve_volume(inst.name, src_vol)
        params = dsp.spatial_params(self.listener_pos, self.listener_forward, inst.pos(),
                                    min_dist=min_dist, max_dist=max_dist,
                                    listener_vel=self.listener_vel)
        left, right = dsp.stereo_volumes(params["pan"], bus_vol * params["volume"])
        try:
            ch.set_volume(left, right)
        except Exception:
            pass

    def set_listener(self, position=None, forward=None, velocity=None):
        if position is not None:
            self.listener_pos = tuple(position)
        if forward is not None:
            self.listener_forward = tuple(forward)
        if velocity is not None:
            self.listener_vel = tuple(velocity)

    def stop(self, inst):
        ch = self.channels.get(inst.name)
        if ch is not None:
            try:
                ch.stop()
            except Exception:
                pass
        if inst.name in self.hrtf_sources:
            self._stop_hrtf2d_name(inst.name)

    def stop_all(self):
        if _mixer is not None:
            try:
                _mixer.stop()
            except Exception:
                pass
        self.channels.clear()
        self.hrtf_sources.clear()

    # ---------------------------------------------------------- HRTF 2D
    def set_camera2d(self, position=None, zoom=None):
        """Atualiza a posicao/zoom da 'camera' usada como referencia pro
        audio HRTF 2D. Chamado automaticamente a cada frame pelo runtime
        (a partir do objeto camera2d da cena), mas pode ser setado na mao."""
        if position is not None:
            self.camera2d_pos = (float(position[0]), float(position[1]))
        if zoom is not None:
            self.camera2d_zoom = max(0.0001, float(zoom))

    def _hrtf_layers(self, path, dry_snd, fx_sig, muffle_cutoff, bright_gain, bright_freq):
        sig = (path, fx_sig, round(float(muffle_cutoff), 1),
               round(float(bright_gain), 2), round(float(bright_freq), 1))
        layers = self._hrtf_layer_cache.get(sig)
        if layers is not None:
            return layers
        muffled_snd = dsp.apply_lowpass(dry_snd, cutoff=muffle_cutoff, log=self.log)
        bright_snd = dsp.apply_highshelf(dry_snd, freq=bright_freq, gain_db=bright_gain, log=self.log)
        layers = {"dry": dry_snd, "muffled": muffled_snd, "bright": bright_snd}
        self._hrtf_layer_cache[sig] = layers
        return layers

    def play_hrtf2d(self, inst, bus="SFX", fx=None, pan_range=480.0, elev_range=480.0,
                     min_dist=0.0, max_dist=900.0, smooth=0.12,
                     muffle_cutoff=650.0, bright_gain=5.0, bright_freq=5000.0):
        """Toca um som com panning 2D (X) + 'HRTF' de elevacao (Y) em tempo
        real, acompanhando a posicao do objeto em relacao a camera2d a cada
        frame (chame update_hrtf2d_all, ja plugado no loop do runtime).

        Usa 3 canais em paralelo pro mesmo som (seco / abafado / brilhante)
        e faz cross-fade de volume entre eles conforme a elevacao — assim
        da pra mudar o timbre (abafado <-> claro) em tempo real sem
        reprocessar audio a cada frame, so ajustando volume dos canais.
        """
        if not self.ready:
            self.log("[audio] playHRTF2D ignorado (mixer off): %s" % inst.name)
            return
        source = str(inst.props.get("Source") or "")
        base_snd = self.load(source)
        if base_snd is None:
            return
        path = self.resolve(source)
        fx_sig = tuple(sorted((fx or {}).items()))
        dry_snd = self._dsp_sound(path, base_snd, fx) if fx else base_snd
        layers = self._hrtf_layers(path, dry_snd, fx_sig, muffle_cutoff, bright_gain, bright_freq)

        self._stop_hrtf2d_name(inst.name)
        self.mixer_bus.route(inst.name, bus)
        loops = -1 if inst.props.get("Loop") else 0
        channels = {}
        try:
            for key, snd in layers.items():
                ch = snd.play(loops=loops)
                if ch is not None:
                    ch.set_volume(0.0, 0.0)
                    channels[key] = ch
        except Exception as ex:
            self.log("[audio] erro ao iniciar HRTF2D: %s" % ex)
            return
        if not channels:
            return

        pos = inst.pos() if hasattr(inst, "pos") else (0.0, 0.0, 0.0)
        cx, cy = self.camera2d_pos
        zoom = self.camera2d_zoom or 1.0
        rel_x = (pos[0] - cx) * zoom
        rel_y = (pos[1] - cy) * zoom

        self.hrtf_sources[inst.name] = {
            "channels": channels, "sx": rel_x, "sy": rel_y,
            "tau": max(0.0, float(smooth)),
            "pan_range": max(1.0, float(pan_range)),
            "elev_range": max(1.0, float(elev_range)),
            "min_dist": max(0.0, float(min_dist)),
            "max_dist": max(float(min_dist) + 1.0, float(max_dist)),
        }
        self.update_hrtf2d(inst, 0.0)  # aplica volume/pan iniciais sem esperar o proximo frame

    def update_hrtf2d(self, inst, dt):
        """Recalcula pan/elevacao/volume de UM som HRTF 2D ja tocando,
        suavizando (tween continuo) a posicao relativa a camera. Chame a
        cada frame — o runtime ja faz isso sozinho via update_hrtf2d_all."""
        st = self.hrtf_sources.get(inst.name)
        if st is None:
            return
        pos = inst.pos() if hasattr(inst, "pos") else (0.0, 0.0, 0.0)
        cx, cy = self.camera2d_pos
        zoom = self.camera2d_zoom or 1.0
        target_x = (pos[0] - cx) * zoom
        target_y = (pos[1] - cy) * zoom
        tau = st["tau"]
        if tau <= 0.0 or dt <= 0.0:
            st["sx"], st["sy"] = target_x, target_y
        else:
            k = 1.0 - math.exp(-dt / tau)
            st["sx"] += (target_x - st["sx"]) * k
            st["sy"] += (target_y - st["sy"]) * k

        params = dsp.hrtf2d_params(st["sx"], st["sy"], pan_range=st["pan_range"],
                                    elev_range=st["elev_range"], min_dist=st["min_dist"],
                                    max_dist=st["max_dist"])
        src_vol = float(inst.props.get("Volume") or 1.0)
        base_vol = self.mixer_bus.resolve_volume(inst.name, src_vol) * params["volume"]
        pan = params["pan"]
        for key, weight in (("dry", params["dry_mix"]), ("muffled", params["muffle_mix"]),
                            ("bright", params["bright_mix"])):
            ch = st["channels"].get(key)
            if ch is None:
                continue
            try:
                if weight <= 0.001:
                    ch.set_volume(0.0, 0.0)
                else:
                    left, right = dsp.stereo_volumes(pan, base_vol * weight)
                    ch.set_volume(left, right)
            except Exception:
                pass

    def update_hrtf2d_all(self, scene, dt):
        """Atualiza todos os sons HRTF 2D ativos num frame. `scene` precisa
        ter um metodo find(nome); objetos que sumiram/morreram sao limpos."""
        if not self.hrtf_sources:
            return
        for name in list(self.hrtf_sources.keys()):
            inst = scene.find(name) if scene is not None else None
            if inst is None or not getattr(inst, "alive", True):
                self._stop_hrtf2d_name(name)
                continue
            self.update_hrtf2d(inst, dt)

    def stop_hrtf2d(self, inst):
        self._stop_hrtf2d_name(inst.name if hasattr(inst, "name") else inst)

    def _stop_hrtf2d_name(self, name):
        st = self.hrtf_sources.pop(name, None)
        if not st:
            return
        for ch in st["channels"].values():
            try:
                ch.stop()
            except Exception:
                pass

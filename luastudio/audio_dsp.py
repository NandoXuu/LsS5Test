# -*- coding: utf-8 -*-
"""DSP e mixagem de audio, construidos por cima do pygame.mixer.

pygame nao tem pitch/EQ/reverb/compressor nativos, entao processamos o
array de samples com numpy (dependencia OPCIONAL, importada sob demanda,
igual pygame): se numpy nao estiver disponivel, essas funcoes viram no-ops
que so logam um aviso e devolvem o som original, pra nunca quebrar o jogo.

Sistemas:
  - dB <-> linear
  - Mixer: buses (Master/Music/SFX/Voice/UI), volume, mute, roteamento
  - Pitch shifting (resample)
  - EQ de 3 bandas (low shelf / mid peak / high shelf, biquad)
  - DSP: Reverb (Schroeder: comb + allpass) e Compressor (envelope follower)
  - Audio espacial: pan estereo + atenuacao por distancia (+ doppler leve)
"""

import math

_np = None
_np_tried = False


def _numpy():
    global _np, _np_tried
    if _np_tried:
        return _np
    _np_tried = True
    try:
        import numpy as np
        _np = np
    except Exception:
        _np = None
    return _np


# --------------------------------------------------------------- dB utils
def db_to_linear(db):
    return 10.0 ** (float(db) / 20.0)


def linear_to_db(lin, floor_db=-80.0):
    lin = max(1e-6, float(lin))
    return max(floor_db, 20.0 * math.log10(lin))


# ------------------------------------------------------------------ Mixer
class Bus(object):
    def __init__(self, name, parent=None, volume=1.0):
        self.name = name
        self.parent = parent
        self.volume = float(volume)
        self.muted = False
        self.solo = False

    def effective_volume(self, any_solo=False):
        if self.muted:
            return 0.0
        if any_solo and not self.solo:
            return 0.0
        v = self.volume
        p = self.parent
        while p is not None:
            if p.muted:
                return 0.0
            v *= p.volume
            p = p.parent
        return v


class Mixer(object):
    """Buses padrao: Master -> {Music, SFX, Voice, UI}. Fontes de audio sao
    roteadas (routing) para um bus por nome; o volume final e o produto da
    cadeia bus -> pai -> Master (audio routing)."""

    def __init__(self, log=None):
        self.log = log or (lambda s: None)
        self.master = Bus("Master")
        self.buses = {
            "Master": self.master,
            "Music": Bus("Music", self.master),
            "SFX": Bus("SFX", self.master),
            "Voice": Bus("Voice", self.master),
            "UI": Bus("UI", self.master),
        }
        self.routing = {}   # nome_da_fonte -> nome_do_bus

    def get_bus(self, name):
        b = self.buses.get(name)
        if b is None:
            b = Bus(name, self.master)
            self.buses[name] = b
        return b

    def set_volume(self, bus_name, volume_linear=None, db=None):
        b = self.get_bus(bus_name)
        b.volume = db_to_linear(db) if db is not None else max(0.0, float(volume_linear or 0.0))

    def set_mute(self, bus_name, muted):
        self.get_bus(bus_name).muted = bool(muted)

    def route(self, source_name, bus_name):
        self.routing[source_name] = bus_name

    def resolve_volume(self, source_name, source_volume=1.0):
        bus_name = self.routing.get(source_name, "SFX")
        b = self.get_bus(bus_name)
        any_solo = any(x.solo for x in self.buses.values())
        return max(0.0, min(1.0, float(source_volume))) * b.effective_volume(any_solo)


# ------------------------------------------------------------ pitch/EQ/DSP
def _sound_to_array(snd):
    np = _numpy()
    if np is None:
        return None
    try:
        import pygame.sndarray as sndarray
        return sndarray.array(snd).astype(np.float64)
    except Exception:
        return None


def _array_to_sound(arr, log):
    np = _numpy()
    try:
        import pygame.sndarray as sndarray
        clipped = np.clip(arr, -32768, 32767).astype(np.int16)
        return sndarray.make_sound(np.ascontiguousarray(clipped))
    except Exception as ex:
        log("[audio-dsp] falha ao reconstruir som: %s" % ex)
        return None


def pitch_shift(snd, semitones, log=None):
    """Reamostra o som pra mudar pitch (e velocidade junto, como um sample
    tocado mais rapido/devagar — abordagem classica e leve em CPU)."""
    log = log or (lambda s: None)
    np = _numpy()
    if np is None or semitones == 0:
        if np is None:
            log("[audio-dsp] pitch_shift precisa de numpy (nao encontrado); ignorando")
        return snd
    arr = _sound_to_array(snd)
    if arr is None:
        return snd
    ratio = 2.0 ** (float(semitones) / 12.0)
    n = arr.shape[0]
    new_n = max(1, int(n / ratio))
    idx = np.linspace(0, n - 1, new_n)
    idx_floor = np.floor(idx).astype(int)
    idx_ceil = np.minimum(idx_floor + 1, n - 1)
    frac = (idx - idx_floor)[:, None] if arr.ndim > 1 else (idx - idx_floor)
    resampled = arr[idx_floor] * (1 - frac) + arr[idx_ceil] * frac
    return _array_to_sound(resampled, log) or snd


def _biquad_peak(np, freq, gain_db, q, sr):
    a = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * freq / sr
    alpha = math.sin(w0) / (2 * q)
    cosw0 = math.cos(w0)
    b0 = 1 + alpha * a
    b1 = -2 * cosw0
    b2 = 1 - alpha * a
    a0 = 1 + alpha / a
    a1 = -2 * cosw0
    a2 = 1 - alpha / a
    return [b0 / a0, b1 / a0, b2 / a0], [1.0, a1 / a0, a2 / a0]


def _apply_biquad(np, x, b, a):
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = np.zeros(x.shape[1:]) if x.ndim > 1 else 0.0
    for n in range(x.shape[0]):
        xn = x[n]
        yn = b[0] * xn + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2
        x2, x1 = x1, xn
        y2, y1 = y1, yn
        y[n] = yn
    return y


def apply_eq(snd, low_db=0.0, mid_db=0.0, high_db=0.0, sample_rate=44100, log=None):
    """EQ de 3 bandas (graves ~150Hz, medios ~1kHz, agudos ~6kHz) via biquads
    peak em cascata. Configuravel por 'EQ config' (dB de cada banda)."""
    log = log or (lambda s: None)
    np = _numpy()
    if np is None:
        log("[audio-dsp] EQ precisa de numpy (nao encontrado); ignorando")
        return snd
    arr = _sound_to_array(snd)
    if arr is None:
        return snd
    out = arr.copy()
    for freq, gain, q in ((150, low_db, 0.9), (1000, mid_db, 0.9), (6000, high_db, 0.9)):
        if abs(gain) < 0.01:
            continue
        b, a = _biquad_peak(np, freq, gain, q, sample_rate)
        if out.ndim > 1:
            for ch in range(out.shape[1]):
                out[:, ch] = _apply_biquad(np, out[:, ch], b, a)
        else:
            out = _apply_biquad(np, out, b, a)
    return _array_to_sound(out, log) or snd


def _biquad_lowpass(np, freq, q, sr):
    """Filtro passa-baixa RBJ (2 polos, -12dB/oitava). Usado pra criar a
    camada 'abafada' (muffled) do audio HRTF 2D."""
    w0 = 2 * math.pi * max(20.0, min(freq, sr * 0.49)) / sr
    alpha = math.sin(w0) / (2 * q)
    cosw0 = math.cos(w0)
    b0 = (1 - cosw0) / 2
    b1 = 1 - cosw0
    b2 = (1 - cosw0) / 2
    a0 = 1 + alpha
    a1 = -2 * cosw0
    a2 = 1 - alpha
    return [b0 / a0, b1 / a0, b2 / a0], [1.0, a1 / a0, a2 / a0]


def _biquad_highshelf(np, freq, gain_db, q, sr):
    """Filtro high-shelf RBJ. Usado pra criar a camada 'brilhante' (bright)
    do audio HRTF 2D — o realce de agudos que o ouvido associa a um som
    vindo de cima."""
    a = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * max(20.0, min(freq, sr * 0.49)) / sr
    cosw0 = math.cos(w0)
    sinw0 = math.sin(w0)
    alpha = sinw0 / 2 * math.sqrt((a + 1 / a) * (1 / max(q, 0.01) - 1) + 2)
    two_sqrt_a_alpha = 2 * math.sqrt(a) * alpha
    b0 = a * ((a + 1) + (a - 1) * cosw0 + two_sqrt_a_alpha)
    b1 = -2 * a * ((a - 1) + (a + 1) * cosw0)
    b2 = a * ((a + 1) + (a - 1) * cosw0 - two_sqrt_a_alpha)
    a0 = (a + 1) - (a - 1) * cosw0 + two_sqrt_a_alpha
    a1 = 2 * ((a - 1) - (a + 1) * cosw0)
    a2 = (a + 1) - (a - 1) * cosw0 - two_sqrt_a_alpha
    return [b0 / a0, b1 / a0, b2 / a0], [1.0, a1 / a0, a2 / a0]


def _run_biquad_stereo(np, arr, b, a):
    if arr.ndim > 1:
        out = arr.copy()
        for ch in range(out.shape[1]):
            out[:, ch] = _apply_biquad(np, out[:, ch], b, a)
        return out
    return _apply_biquad(np, arr, b, a)


def apply_lowpass(snd, cutoff=650.0, stages=2, sample_rate=44100, log=None):
    """Cria a camada 'abafada' (muffled) de um som: passa-baixa em cascata
    (cada estagio = -12dB/oitava), pra simular som distante, atras de
    obstaculo, ou 'vindo de baixo' no HRTF 2D."""
    log = log or (lambda s: None)
    np = _numpy()
    if np is None:
        log("[audio-dsp] lowpass precisa de numpy (nao encontrado); ignorando")
        return snd
    arr = _sound_to_array(snd)
    if arr is None:
        return snd
    b, a = _biquad_lowpass(np, cutoff, 0.707, sample_rate)
    out = arr.astype(np.float64)
    for _ in range(max(1, int(stages))):
        out = _run_biquad_stereo(np, out, b, a)
    return _array_to_sound(out, log) or snd


def apply_highshelf(snd, freq=5000.0, gain_db=5.0, q=0.8, sample_rate=44100, log=None):
    """Cria a camada 'brilhante' (bright) de um som: realce de agudos, pra
    simular som 'vindo de cima' no HRTF 2D."""
    log = log or (lambda s: None)
    np = _numpy()
    if np is None or abs(gain_db) < 0.01:
        if np is None:
            log("[audio-dsp] highshelf precisa de numpy (nao encontrado); ignorando")
        return snd
    arr = _sound_to_array(snd)
    if arr is None:
        return snd
    b, a = _biquad_highshelf(np, freq, gain_db, q, sample_rate)
    out = _run_biquad_stereo(np, arr.astype(np.float64), b, a)
    return _array_to_sound(out, log) or snd


def apply_reverb(snd, mix=0.3, room_size=0.6, damping=0.4, sample_rate=44100, log=None):
    """Reverb estilo Schroeder: banco de comb filters em paralelo + allpass
    em serie. 'room_size' controla os tempos de delay, 'damping' o feedback."""
    log = log or (lambda s: None)
    np = _numpy()
    if np is None:
        log("[audio-dsp] reverb precisa de numpy (nao encontrado); ignorando")
        return snd
    arr = _sound_to_array(snd)
    if arr is None:
        return snd
    mono = arr.mean(axis=1) if arr.ndim > 1 else arr
    combs_ms = [29.7, 37.1, 41.1, 43.7]
    fb = 0.6 + 0.35 * max(0.0, min(1.0, room_size))
    damp = max(0.0, min(0.99, damping))
    wet = np.zeros_like(mono)
    for ms in combs_ms:
        d = max(1, int(sample_rate * ms / 1000.0))
        buf = np.zeros(len(mono) + d)
        state = 0.0
        for n in range(len(mono)):
            delayed = buf[n]
            state = delayed * (1 - damp) + state * damp
            buf[n + d] = mono[n] + state * fb
            wet[n] += delayed
    wet /= float(len(combs_ms))
    # allpass simples pra difundir os ecos
    ap_d = max(1, int(sample_rate * 5 / 1000.0))
    ap_buf = np.zeros(len(wet) + ap_d)
    ap_out = np.zeros_like(wet)
    g = 0.5
    for n in range(len(wet)):
        bufn = ap_buf[n]
        out_n = -g * wet[n] + bufn
        ap_buf[n + ap_d] = wet[n] + g * out_n
        ap_out[n] = out_n
    m = max(0.0, min(1.0, mix))
    result_mono = mono * (1 - m) + ap_out * m
    if arr.ndim > 1:
        result = np.repeat(result_mono[:, None], arr.shape[1], axis=1)
    else:
        result = result_mono
    return _array_to_sound(result, log) or snd


def apply_compressor(snd, threshold_db=-18.0, ratio=4.0, attack_ms=5.0, release_ms=80.0,
                      makeup_db=0.0, sample_rate=44100, log=None):
    """Compressor de dinamica classico: envelope follower + curva de razao
    acima do threshold, com attack/release e ganho de compensacao (makeup)."""
    log = log or (lambda s: None)
    np = _numpy()
    if np is None:
        log("[audio-dsp] compressor precisa de numpy (nao encontrado); ignorando")
        return snd
    arr = _sound_to_array(snd)
    if arr is None:
        return snd
    peak = 32768.0
    x = arr / peak
    mono = np.abs(x.mean(axis=1)) if x.ndim > 1 else np.abs(x)
    att = math.exp(-1.0 / (sample_rate * attack_ms / 1000.0))
    rel = math.exp(-1.0 / (sample_rate * release_ms / 1000.0))
    env = 0.0
    gain = np.ones(len(mono))
    thr = db_to_linear(threshold_db)
    for n in range(len(mono)):
        s = mono[n]
        env = (att * env + (1 - att) * s) if s > env else (rel * env + (1 - rel) * s)
        if env > thr and env > 0:
            over_db = linear_to_db(env) - threshold_db
            reduced_db = over_db - over_db / max(1.0, ratio)
            gain[n] = db_to_linear(-reduced_db)
        else:
            gain[n] = 1.0
    makeup = db_to_linear(makeup_db)
    if x.ndim > 1:
        out = x * gain[:, None] * makeup
    else:
        out = x * gain * makeup
    return _array_to_sound(out * peak, log) or snd


# --------------------------------------------------------------- espacial
def spatial_params(listener_pos, listener_forward, source_pos, min_dist=1.0, max_dist=30.0,
                    listener_vel=(0, 0, 0), source_vel=(0, 0, 0), speed_of_sound=343.0):
    """Calcula (pan, volume, pitch_semitones) pra audio 3D: pan pela posicao
    lateral relativa ao listener, atencao por distancia, e um doppler leve
    baseado na velocidade radial (opcional)."""
    dx = source_pos[0] - listener_pos[0]
    dy = source_pos[1] - listener_pos[1]
    dz = source_pos[2] - listener_pos[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < 1e-5:
        pan = 0.0
    else:
        fx, fy, fz = listener_forward
        # "right" = forward rotacionado -90 no plano XZ (aproximacao 2D)
        right = (-fz, 0.0, fx)
        rn = math.sqrt(right[0] ** 2 + right[2] ** 2) or 1.0
        right = (right[0] / rn, 0.0, right[2] / rn)
        pan = max(-1.0, min(1.0, (dx * right[0] + dz * right[2]) / max(dist, 1e-5)))
    if dist <= min_dist:
        atten = 1.0
    elif dist >= max_dist:
        atten = 0.0
    else:
        atten = 1.0 - (dist - min_dist) / (max_dist - min_dist)
        atten *= atten
    rel_vel = 0.0
    if dist > 1e-5:
        rvx, rvy, rvz = (source_vel[0] - listener_vel[0], source_vel[1] - listener_vel[1],
                        source_vel[2] - listener_vel[2])
        rel_vel = (rvx * dx + rvy * dy + rvz * dz) / dist
    doppler_ratio = speed_of_sound / max(1.0, speed_of_sound + rel_vel)
    pitch_semitones = 12.0 * math.log2(max(0.05, doppler_ratio))
    return {"pan": pan, "volume": atten, "pitch_semitones": pitch_semitones, "distance": dist}


def stereo_volumes(pan, volume):
    pan = max(-1.0, min(1.0, pan))
    left = volume * min(1.0, 1.0 - pan) if pan > 0 else volume
    right = volume * min(1.0, 1.0 + pan) if pan < 0 else volume
    return max(0.0, left), max(0.0, right)


# ---------------------------------------------------------- HRTF 2D (X/Y)
class Smoother(object):
    """Suaviza um valor escalar ao longo do tempo (tipo um Tween continuo,
    framerate-independente): a cada update() o valor anda uma fracao 'k' do
    caminho ate o alvo, baseado no dt do frame e numa constante de tempo
    'tau' (segundos). tau=0 significa 'sem suavizacao' (aplica na hora)."""
    __slots__ = ("value", "tau")

    def __init__(self, initial, tau=0.12):
        self.value = float(initial)
        self.tau = max(0.0, float(tau))

    def update(self, target, dt):
        if self.tau <= 0.0 or dt <= 0.0:
            self.value = float(target)
        else:
            k = 1.0 - math.exp(-dt / self.tau)
            self.value += (float(target) - self.value) * k
        return self.value


def hrtf2d_params(rel_x, rel_y, pan_range=480.0, elev_range=480.0,
                   min_dist=0.0, max_dist=900.0, invert_y=True):
    """Calcula os parametros de audio espacial 2D (pan lateral X + 'HRTF'
    de elevacao Y) a partir da posicao relativa (fonte - camera), ja
    escalada pelo zoom da camera.

    - pan: -1 (esquerda) .. +1 (direita), pela distancia lateral (X) em
      relacao ao alcance 'pan_range' (em unidades de mundo/tela).
    - elevation: -1 (bem abaixo) .. +1 (bem acima), pela distancia
      vertical (Y) em relacao a 'elev_range'. Por padrao (invert_y=True)
      assume o eixo Y do motor crescendo pra baixo (como a gravidade), entao
      Y menor (pra cima na tela) vira elevation positiva.
    - dry_mix / bright_mix / muffle_mix: pesos (0..1, somam no maximo 1)
      pra cross-fade em tempo real entre a camada seca, a camada 'brilhante'
      (som vindo de cima) e a camada 'abafada' (som vindo de baixo/longe).
    - volume: atenuacao por distancia (1 perto, 0 no max_dist).
    """
    dy = -rel_y if invert_y else rel_y
    dx = rel_x
    dist = math.sqrt(dx * dx + dy * dy)
    pan = max(-1.0, min(1.0, dx / max(1e-5, pan_range)))
    elevation = max(-1.0, min(1.0, dy / max(1e-5, elev_range)))
    if dist <= min_dist:
        atten = 1.0
    elif dist >= max_dist:
        atten = 0.0
    else:
        atten = 1.0 - (dist - min_dist) / max(1e-5, (max_dist - min_dist))
        atten *= atten
    bright_mix = max(0.0, elevation)
    muffle_mix = max(0.0, -elevation)
    dry_mix = 1.0 - max(bright_mix, muffle_mix)
    return {
        "pan": pan, "elevation": elevation, "volume": atten, "distance": dist,
        "dry_mix": dry_mix, "bright_mix": bright_mix, "muffle_mix": muffle_mix,
    }

# -*- coding: utf-8 -*-
"""Permissoes Android via o plugin do Pydroid 3 (`androidhelper` / `plyer` /
`android.permissions`). Tudo com fallback seguro no desktop."""

import os
import time

ANDROID = ("ANDROID_ARGUMENT" in os.environ or "ANDROID_STORAGE" in os.environ
           or os.path.exists("/system/build.prop"))

# Nomes amigaveis -> permissao Android
PERMISSION_MAP = {
    "storage": ["android.permission.READ_EXTERNAL_STORAGE",
                "android.permission.WRITE_EXTERNAL_STORAGE"],
    "read_storage": ["android.permission.READ_EXTERNAL_STORAGE"],
    "write_storage": ["android.permission.WRITE_EXTERNAL_STORAGE"],
    "media": ["android.permission.READ_MEDIA_IMAGES",
              "android.permission.READ_MEDIA_AUDIO"],
    "camera": ["android.permission.CAMERA"],
    "microphone": ["android.permission.RECORD_AUDIO"],
    "record_audio": ["android.permission.RECORD_AUDIO"],
    "location": ["android.permission.ACCESS_FINE_LOCATION",
                 "android.permission.ACCESS_COARSE_LOCATION"],
    "vibrate": ["android.permission.VIBRATE"],
    "internet": ["android.permission.INTERNET"],
    "notifications": ["android.permission.POST_NOTIFICATIONS"],
    "bluetooth": ["android.permission.BLUETOOTH_CONNECT"],
}

_last_error = None


def _expand(names):
    out = []
    for n in names:
        n = str(n).strip()
        key = n.lower()
        if key in PERMISSION_MAP:
            out.extend(PERMISSION_MAP[key])
        elif "." in n:
            out.append(n)
        else:
            out.append("android.permission." + n.upper())
    return out


# ----------------------------------------------------------- backends
def _pydroid_backend():
    """Pydroid 3 expoe o modulo `androidhelper` (plugin de permissoes)."""
    try:
        import androidhelper  # noqa
        return androidhelper
    except Exception:
        return None


def _pyjnius_backend():
    try:
        from android.permissions import request_permissions, check_permission  # noqa
        return (request_permissions, check_permission)
    except Exception:
        return None


def request(names):
    """Pede permissoes. Retorna dict {permissao: bool}."""
    global _last_error
    perms = _expand(names)
    result = dict((p, True) for p in perms)
    if not ANDROID:
        return result
    pj = _pyjnius_backend()
    if pj:
        request_permissions, check_permission = pj
        try:
            request_permissions(perms)
            return dict((p, bool(check_permission(p))) for p in perms)
        except Exception as ex:
            _last_error = str(ex)
    ah = _pydroid_backend()
    if ah:
        try:
            droid = ah.Android()
            for p in perms:
                try:
                    droid.requestPermission(p)
                except Exception:
                    pass
            return dict((p, True) for p in perms)
        except Exception as ex:
            _last_error = str(ex)
    return result


def check(name):
    perms = _expand([name])
    if not ANDROID:
        return True
    pj = _pyjnius_backend()
    if pj:
        _, check_permission = pj
        try:
            return all(bool(check_permission(p)) for p in perms)
        except Exception:
            return False
    return True


def vibrate(ms=200):
    if not ANDROID:
        return False
    try:
        from plyer import vibrator
        vibrator.vibrate(float(ms) / 1000.0)
        return True
    except Exception:
        pass
    ah = _pydroid_backend()
    if ah:
        try:
            ah.Android().vibrate(int(ms))
            return True
        except Exception:
            pass
    return False


def toast(msg):
    if not ANDROID:
        return False
    ah = _pydroid_backend()
    if ah:
        try:
            ah.Android().makeToast(str(msg))
            return True
        except Exception:
            pass
    try:
        from plyer import notification
        notification.notify(message=str(msg), title="LuaStudio")
        return True
    except Exception:
        return False


def storage_dir():
    """Diretorio de trabalho gravavel (Android ou desktop)."""
    candidates = [
        os.environ.get("EXTERNAL_STORAGE"),
        "/storage/emulated/0",
        "/sdcard",
        os.path.expanduser("~"),
    ]
    for c in candidates:
        if c and os.path.isdir(c) and os.access(c, os.W_OK):
            path = os.path.join(c, "LuaStudio")
            try:
                if not os.path.isdir(path):
                    os.makedirs(path)
                return path
            except Exception:
                continue
    return os.getcwd()


def notify(title, message):
    """Notificacao de verdade na barra de status (diferente do toast)."""
    if not ANDROID:
        return False
    request(["notifications"])
    try:
        from plyer import notification
        notification.notify(title=str(title or "LuaStudio"), message=str(message or ""),
                             app_name="LuaStudio")
        return True
    except Exception:
        pass
    ah = _pydroid_backend()
    if ah:
        try:
            ah.Android().notify(str(title or "LuaStudio"), str(message or ""))
            return True
        except Exception:
            pass
    return False


# ------------------------------------------------------------- bussola
_compass_enabled = False


def compass_enable():
    global _compass_enabled
    if not ANDROID:
        return False
    try:
        from plyer import compass
        compass.enable()
        _compass_enabled = True
        return True
    except Exception:
        _compass_enabled = False
        return False


def compass_disable():
    global _compass_enabled
    if ANDROID:
        try:
            from plyer import compass
            compass.disable()
        except Exception:
            pass
    _compass_enabled = False


def compass_heading():
    """Rumo em graus (0-360, 0 = norte) ou None se indisponivel/desligada."""
    if not ANDROID or not _compass_enabled:
        return None
    try:
        import math
        from plyer import compass
        field = compass.field
        if not field:
            return None
        heading = math.degrees(math.atan2(field[1], field[0]))
        if heading < 0:
            heading += 360.0
        return heading
    except Exception:
        return None


# ----------------------------------------------------------- microfone
_mic_recording = False
_mic_path = None


def mic_start(path=None):
    global _mic_recording, _mic_path
    if not ANDROID:
        return False
    request(["microphone"])
    try:
        from plyer import audio
        _mic_path = path or os.path.join(storage_dir(), "gravacao.3gp")
        audio.file_path = _mic_path
        audio.start()
        _mic_recording = True
        return True
    except Exception:
        _mic_recording = False
        return False


def mic_stop():
    """Para a gravacao e retorna o caminho do arquivo gravado (ou None)."""
    global _mic_recording
    if not ANDROID or not _mic_recording:
        return None
    try:
        from plyer import audio
        audio.stop()
        _mic_recording = False
        return _mic_path
    except Exception:
        _mic_recording = False
        return None


def mic_play(path=None):
    """Toca um arquivo gravado (por padrao, a ultima gravacao)."""
    if not ANDROID:
        return False
    p = path or _mic_path
    if not p or not os.path.exists(p):
        return False
    try:
        from jnius import autoclass
        MediaPlayer = autoclass("android.media.MediaPlayer")
        mp = MediaPlayer()
        mp.setDataSource(p)
        mp.prepare()
        mp.start()
        return True
    except Exception:
        pass
    try:
        from plyer import audio
        audio.file_path = p
        audio.play()
        return True
    except Exception:
        return False


# --------------------------------------------------- nivel de microfone
# (MediaRecorder + getMaxAmplitude(), pra medidor de volume em tempo real -
# separado do mic_start/mic_stop de cima, que gravam de verdade com plyer)
_level_recorder = None


def mic_level_start():
    global _level_recorder
    if not ANDROID:
        return False
    if _level_recorder is not None:
        return True
    request(["microphone"])
    try:
        from jnius import autoclass
        MediaRecorder = autoclass("android.media.MediaRecorder")
        AudioSource = autoclass("android.media.MediaRecorder$AudioSource")
        OutputFormat = autoclass("android.media.MediaRecorder$OutputFormat")
        AudioEncoder = autoclass("android.media.MediaRecorder$AudioEncoder")
        rec = MediaRecorder()
        rec.setAudioSource(AudioSource.MIC)
        rec.setOutputFormat(OutputFormat.THREE_GPP)
        rec.setAudioEncoder(AudioEncoder.AMR_NB)
        rec.setOutputFile(os.path.join(storage_dir(), "_nivel_mic.amr"))
        rec.prepare()
        rec.start()
        _level_recorder = rec
        return True
    except Exception:
        _level_recorder = None
        return False


def mic_level_stop():
    global _level_recorder
    if _level_recorder is None:
        return
    try:
        _level_recorder.stop()
        _level_recorder.release()
    except Exception:
        pass
    _level_recorder = None


def mic_level():
    """Volume atual de 0 a 100, a partir do pico de amplitude nativo
    (0-32767) medido desde a ultima leitura."""
    if _level_recorder is None:
        return 0.0
    try:
        amp = _level_recorder.getMaxAmplitude()
        return max(0.0, min(100.0, (amp / 25000.0) * 100.0))
    except Exception:
        return 0.0


# -------------------------------------------------------------- camera
def camera_take(path=None, on_complete=None):
    """Abre a camera nativa pra tirar uma foto e salva em `path`.
    `on_complete(caminho_ou_None)` e chamado quando a captura termina
    (a UI nativa da camera roda assincrona)."""
    if not ANDROID:
        if on_complete:
            on_complete(None)
        return False
    request(["camera", "storage"])
    try:
        from plyer import camera
        p = path or os.path.join(storage_dir(), "foto_%d.jpg" % int(time.time()))

        def _cb(*_a):
            ok = os.path.exists(p)
            if on_complete:
                on_complete(p if ok else None)
        camera.take_picture(filename=p, on_complete=_cb)
        return True
    except Exception:
        if on_complete:
            on_complete(None)
        return False


# --------------------------------------------------------- orientacao
_ORIENTATION_CONST = {
    "portrait": "SCREEN_ORIENTATION_PORTRAIT",
    "portrait_reverse": "SCREEN_ORIENTATION_REVERSE_PORTRAIT",
    "landscape": "SCREEN_ORIENTATION_LANDSCAPE",
    "landscape_reverse": "SCREEN_ORIENTATION_REVERSE_LANDSCAPE",
    # segue o giroscopio, mas so entre as 2 landscape OU as 2 portrait
    "sensor_portrait": "SCREEN_ORIENTATION_SENSOR_PORTRAIT",
    "sensor_landscape": "SCREEN_ORIENTATION_SENSOR_LANDSCAPE",
    # segue o giroscopio livremente entre as 4 (padrao quando nao informado)
    "sensor": "SCREEN_ORIENTATION_FULL_SENSOR",
    # libera pro sistema decidir (config do aparelho / rotacao automatica)
    "auto": "SCREEN_ORIENTATION_UNSPECIFIED",
    "unlocked": "SCREEN_ORIENTATION_UNSPECIFIED",
}


def _android_activity():
    """Acha a Activity do app Kivy exportado (python-for-android/buildozer).
    None se nao achar (desktop, Pydroid sem esse bootstrap, etc.)."""
    try:
        from jnius import autoclass
    except Exception:
        return None
    for cls_name in ("org.kivy.android.PythonActivity",
                     "org.kivy.android.PythonService"):
        try:
            cls = autoclass(cls_name)
            activity = getattr(cls, "mActivity", None)
            if activity is not None:
                return activity
        except Exception:
            continue
    return None


def set_orientation(mode="sensor"):
    """Trava (ou libera) a orientacao da tela em tempo real - chamado do
    Lua via android.setOrientation("portrait"/"landscape"/"sensor"/...).
    So tem efeito de verdade num app Android exportado (buildozer); no
    desktop e no preview do Pydroid e um no-op que devolve False."""
    global _last_error
    if not ANDROID:
        return False
    mode = str(mode or "sensor").strip().lower()
    activity = _android_activity()
    if activity is None:
        return False
    try:
        from jnius import autoclass
        ActivityInfo = autoclass("android.content.pm.ActivityInfo")
        const_name = _ORIENTATION_CONST.get(mode, "SCREEN_ORIENTATION_FULL_SENSOR")
        value = getattr(ActivityInfo, const_name)

        def _apply(*_a):
            try:
                activity.setRequestedOrientation(value)
            except Exception:
                pass
        try:
            from kivy.clock import Clock
            Clock.schedule_once(_apply, 0)
        except Exception:
            _apply()
        return True
    except Exception as ex:
        _last_error = str(ex)
        return False


def get_orientation():
    """'portrait' ou 'landscape', pelo tamanho atual da janela."""
    try:
        from kivy.core.window import Window
        return "landscape" if Window.width >= Window.height else "portrait"
    except Exception:
        return "portrait"


def hide_system_bars():
    """Modo imersivo: esconde a barra de status e a de navegacao (so
    Android). Usado pelo LuaStudio Player pra rodar o jogo em tela
    cheia de verdade, sem nenhuma UI do sistema por cima."""
    global _last_error
    if not ANDROID:
        return False
    activity = _android_activity()
    if activity is None:
        return False
    try:
        from jnius import autoclass
        View = autoclass("android.view.View")
        flags = (View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                 | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                 | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                 | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                 | View.SYSTEM_UI_FLAG_FULLSCREEN
                 | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY)

        def _apply(*_a):
            try:
                activity.getWindow().getDecorView().setSystemUiVisibility(flags)
            except Exception:
                pass
        try:
            from kivy.clock import Clock
            Clock.schedule_once(_apply, 0)
        except Exception:
            _apply()
        return True
    except Exception as ex:
        _last_error = str(ex)
        return False


def device_info():
    info = {"android": ANDROID, "storage": storage_dir()}
    try:
        import platform
        info["platform"] = platform.machine()
        info["python"] = platform.python_version()
    except Exception:
        pass
    if _last_error:
        info["last_error"] = _last_error
    return info

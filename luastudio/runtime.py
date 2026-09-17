# -*- coding: utf-8 -*-
"""Runtime: junta interpretador Lua + API `create` + cena + audio + permissoes."""

import os
import re
import math
import time
import json as _json
import random as _random

from .lua import (Interpreter, LuaTable, LuaError, LuaSyntaxError, tostring, truthy,
                  as_list, first, from_py, to_py)
from .api import Scene, CreateRoot, Instance, vec_table, to_vec, to_color, safe_float
from .vector import Vector2, Vector3, VECTOR2, VECTOR3
from .audio import Audio
from .physics import Physics2D
from .tween import TweenService
from .particles import ParticleSystem
from .profiler import Profiler
from . import audio_dsp
from . import permissions as perms

# Orcamento de "passos" de execucao Lua por frame/evento - protege contra
# `while true do end` (ou qualquer outro loop infinito) travando o app
# inteiro; e resetado a cada frame/toque/tecla (ver _reset_budget).
DEFAULT_INSTRUCTION_BUDGET = 300000

# dt maximo aceito por frame (segundos) - se o app ficar preso/em segundo
# plano e voltar com um dt gigante, evita que fisica/tween/camera dêem um
# salto absurdo (ou produzam NaN/Infinity) de uma vez so.
MAX_DT = 0.1


def safe_dt(dt):
    d = safe_float(dt, fallback=0.0, limit=MAX_DT)
    if d < 0.0:
        return 0.0
    if d > MAX_DT:
        return MAX_DT
    return d


class Runtime(object):
    def __init__(self, log=None, base_dir="."):
        self.log = log or (lambda s: None)
        self.base_dir = base_dir
        self.scene = Scene(self)
        self.audio = Audio(self.log, base_dir)
        self.physics = Physics2D(self)
        self.tween = TweenService(self)
        self.particles = ParticleSystem(self)
        self.profiler = Profiler(enabled=False)
        self.timers = []          # itens agendados por timer.after/timer.every
        self._timer_seq = 0
        self.interp = Interpreter(print_fn=self.log)
        self.interp.instruction_budget = DEFAULT_INSTRUCTION_BUDGET
        self.update_handlers = []
        self.touch_handlers = []
        self.key_handlers = []
        self.start_time = time.time()
        self.stage_size = (800.0, 600.0)
        self.background = (0.06, 0.07, 0.10, 1)
        self.ambient2d_color = (1.0, 1.0, 1.0)   # cor da luz ambiente 2D
        self.ambient2d_intensity = 1.0           # 1.0 = nao escurece nada (retrocompativel)
        self.max_lights2d = 8                    # light filtering 2D (luzes por objeto)
        self.running = False
        self.scene_registry = {}   # nome -> funcao Lua que monta a cena
        self.current_scene_name = None
        self._fade_overlay = None
        self.camera_widget = None       # kivy.uix.camera.Camera ao vivo (create.image Source="camera")
        self.mouse_pos = (0.0, 0.0)     # ultima posicao do mouse/toque, coords Lua (Y pra baixo)
        self.mouse_buttons = set()      # botoes do mouse pressionados agora ("left","right","middle")
        self.hover_obj = None           # objeto sob o cursor agora (pra OnMouseEnter/OnMouseExit)
        self.project_scripts = {}       # projeto atual: nome_arquivo.lua -> codigo (pra require)
        self._modules = {}              # cache de modulos ja carregados via require()
        self._loading_stack = set()     # pra detectar require ciclico
        self.install_api()

    # ------------------------------------------------------------- API Lua
    def install_api(self):
        g = self.interp.set_global
        scene = self.scene

        g("create", CreateRoot(scene))

        # ---- app ----
        app = LuaTable()
        app.set("find", lambda name=None: scene.find(name))
        app.set("destroy", lambda name=None: (scene.remove(scene.find(name))
                                              if scene.find(name) else None))
        app.set("clear", lambda *a: scene.clear())
        app.set("count", lambda *a: float(len(scene.objects)))

        def _all(cls=None):
            objs = scene.of_class(tostring(cls)) if cls else list(scene.objects)
            return LuaTable(objs)
        app.set("all", _all)
        app.set("width", lambda *a: float(self.stage_size[0]))
        app.set("height", lambda *a: float(self.stage_size[1]))
        app.set("size", lambda *a: vec_table(self.stage_size[0], self.stage_size[1]))
        app.set("time", lambda *a: float(time.time() - self.start_time))
        app.set("log", lambda *a: self.log(" ".join(tostring(x) for x in a)))

        def _background(c=None):
            self.background = to_color(c, self.background)
        app.set("background", _background)

        def _onupdate(fn=None):
            if fn is not None:
                self.update_handlers.append(fn)
        app.set("onUpdate", _onupdate)
        g("onUpdate", _onupdate)

        def _ontouch(fn=None):
            if fn is not None:
                self.touch_handlers.append(fn)
        app.set("onTouch", _ontouch)
        g("onTouch", _ontouch)

        def _onkey(fn=None):
            if fn is not None:
                self.key_handlers.append(fn)
        app.set("onKey", _onkey)

        app.set("vec", lambda x=0, y=0, z=0: vec_table(x, y, z))
        g("vec", app.get("vec"))
        g("vec2", lambda x=0, y=0: vec_table(x, y, 0))
        g("vec3", lambda x=0, y=0, z=0: vec_table(x, y, z))
        g("app", app)

        # ---- require(): outro script/modulo do MESMO projeto ----
        # Todos os scripts de um projeto rodam no mesmo runtime, entao um
        # modulo carregado com require() pode ver e editar os objetos que
        # outro script criou (via app.find, por exemplo).
        g("require", lambda name=None: self.require(tostring(name)))

        # ---- Vector2 / Vector3 (objetos de verdade, com metodos) ----
        g("Vector2", VECTOR2)
        g("Vector3", VECTOR3)

        # ---- input (mouse/touch): posicao, botoes, OnMouseEnter/Exit ----
        input_t = LuaTable()
        input_t.set("mousePosition", lambda *a: vec_table(self.mouse_pos[0], self.mouse_pos[1]))
        input_t.set("isMouseDown", lambda btn=1: self.mouse_button_name(btn) in self.mouse_buttons)
        g("input", input_t)
        g("Input", input_t)

        # ---- android / permissoes (plugin do Pydroid 3) ----
        android = LuaTable()
        android.set("isAndroid", lambda *a: bool(perms.ANDROID))

        def _request(*names):
            flat = []
            for n in names:
                if isinstance(n, LuaTable):
                    flat.extend([tostring(x) for x in n.ipairs_list()])
                elif n is not None:
                    flat.append(tostring(n))
            res = perms.request(flat or ["storage"])
            t = LuaTable()
            for k, v in res.items():
                t.set(k, bool(v))
            granted = all(res.values())
            self.log("[android] permissoes %s -> %s" % (flat, "OK" if granted else "negadas"))
            return [granted, t]
        android.set("requestPermission", _request)
        android.set("requestPermissions", _request)
        android.set("hasPermission", lambda name=None: bool(perms.check(tostring(name))))
        android.set("vibrate", lambda ms=200: bool(perms.vibrate(float(ms or 200))))
        android.set("toast", lambda msg="": bool(perms.toast(tostring(msg))))
        android.set("storagePath", lambda *a: perms.storage_dir())

        # -- notificacao (barra de status, com titulo, diferente do toast) --
        android.set("notify", lambda title="LuaStudio", msg="":
                     bool(perms.notify(tostring(title), tostring(msg))))

        # -- bussola --
        android.set("compassStart", lambda *a: bool(perms.compass_enable()))
        android.set("compassStop", lambda *a: perms.compass_disable())

        def _compass_heading(*a):
            h = perms.compass_heading()
            return float(h) if h is not None else None
        android.set("compassHeading", _compass_heading)

        # -- microfone --
        android.set("micStart", lambda path=None:
                     bool(perms.mic_start(tostring(path) if path else None)))
        android.set("micStop", lambda *a: (perms.mic_stop() or None))
        android.set("micPlay", lambda path=None:
                     bool(perms.mic_play(tostring(path) if path else None)))

        # -- camera (foto) --
        def _take_photo(path=None, on_done=None):
            def _cb(result_path):
                if on_done is not None:
                    self.call(on_done, result_path)
            return bool(perms.camera_take(tostring(path) if path else None, _cb))
        android.set("takePhoto", _take_photo)
        android.set("camera", _take_photo)

        # -- camera ao vivo (frames num create.image com Source="camera") --
        def _camera_start(index=0):
            if self.camera_widget is not None:
                return True
            perms.request(["camera"])
            try:
                from kivy.uix.camera import Camera
                self.camera_widget = Camera(index=int(index or 0), play=True,
                                            resolution=(640, 480))
                return True
            except Exception as ex:
                self.log("[camera] nao consegui abrir: %s" % ex)
                self.camera_widget = None
                return False
        android.set("cameraStart", _camera_start)
        android.set("cameraStop", lambda *a: self.stop_camera())
        android.set("cameraActive", lambda *a: self.camera_widget is not None)

        # -- medidor de volume do microfone (0-100, em tempo real) --
        android.set("micLevelStart", lambda *a: bool(perms.mic_level_start()))
        android.set("micLevelStop", lambda *a: perms.mic_level_stop())
        android.set("micLevel", lambda *a: float(perms.mic_level()))

        def _info(*a):
            t = LuaTable()
            for k, v in perms.device_info().items():
                t.set(k, v if not isinstance(v, int) or isinstance(v, bool) else float(v))
            return t
        android.set("info", _info)

        # -- orientacao da tela (portrait/landscape), em tempo real --
        # Ex.: android.setOrientation("landscape") trava o jogo deitado;
        # "sensor" libera pra girar sozinho; "auto" devolve pro sistema.
        android.set("setOrientation",
                     lambda mode="sensor": bool(perms.set_orientation(tostring(mode))))
        android.set("lockOrientation", android.get("setOrientation"))
        android.set("orientation", lambda *a: perms.get_orientation())
        android.set("getOrientation", lambda *a: perms.get_orientation())
        g("android", android)

        # mesma coisa disponivel em app.*, pra quem prefere nao mexer
        # com o namespace android diretamente
        app.set("setOrientation", android.get("setOrientation"))
        app.set("orientation", android.get("orientation"))

        # ---- arquivos (respeitando permissoes) ----
        fs = LuaTable()

        def _read(path=""):
            p = self.resolve(tostring(path))
            try:
                with open(p, "r") as fh:
                    return fh.read()
            except Exception as ex:
                self.log("[fs] erro lendo %s: %s" % (path, ex))
                return None
        fs.set("read", _read)

        def _write(path="", data=""):
            perms.request(["storage"])
            p = self.resolve(tostring(path))
            try:
                with open(p, "w") as fh:
                    fh.write(tostring(data))
                return True
            except Exception as ex:
                self.log("[fs] erro escrevendo %s: %s" % (path, ex))
                return False
        fs.set("write", _write)
        fs.set("exists", lambda path="": os.path.exists(self.resolve(tostring(path))))
        fs.set("dir", lambda *a: perms.storage_dir())
        g("fs", fs)

        # ---- audio direto ----
        sound = LuaTable()
        sound.set("play", lambda name=None: self._sound_op(name, "play"))
        sound.set("stop", lambda name=None: self._sound_op(name, "stop"))
        sound.set("stopAll", lambda *a: self.audio.stop_all())

        def _sound_play_fx(name=None, opts=None):
            inst = self.scene.find(tostring(name)) if name else None
            if inst is None or inst.cls != "sound":
                return
            fx = {}
            bus = "SFX"
            spatial = False
            if isinstance(opts, LuaTable):
                fx = {
                    "pitch": float(opts.get("Pitch") or 0) or None,
                    "eq_low": float(opts.get("EQLow") or 0),
                    "eq_mid": float(opts.get("EQMid") or 0),
                    "eq_high": float(opts.get("EQHigh") or 0),
                    "reverb": float(opts.get("Reverb") or 0) or None,
                    "compress": bool(opts.get("Compress")),
                }
                fx = {k: v for k, v in fx.items() if v}
                bus = tostring(opts.get("Bus") or "SFX")
                spatial = truthy(opts.get("Spatial"))
            self.audio.play(inst, bus=bus, fx=fx or None, spatial=spatial)
        sound.set("playFX", _sound_play_fx)

        def _listener(pos=None, forward=None):
            self.audio.set_listener(position=to_vec(pos) if pos is not None else None,
                                    forward=to_vec(forward) if forward is not None else None)
        sound.set("setListener", _listener)

        # ---- HRTF 2D: pan X + elevacao Y por camera2d, em tempo real ----
        def _sound_play_hrtf2d(name=None, opts=None):
            inst = self.scene.find(tostring(name)) if name else None
            if inst is None or inst.cls != "sound":
                return
            fx = {}
            bus = "SFX"
            kw = dict(pan_range=480.0, elev_range=480.0, min_dist=0.0, max_dist=900.0,
                      smooth=0.12, muffle_cutoff=650.0, bright_gain=5.0, bright_freq=5000.0)
            if isinstance(opts, LuaTable):
                fx = {
                    "pitch": float(opts.get("Pitch") or 0) or None,
                    "eq_low": float(opts.get("EQLow") or 0),
                    "eq_mid": float(opts.get("EQMid") or 0),
                    "eq_high": float(opts.get("EQHigh") or 0),
                    "reverb": float(opts.get("Reverb") or 0) or None,
                    "compress": bool(opts.get("Compress")),
                }
                fx = {k: v for k, v in fx.items() if v}
                bus = tostring(opts.get("Bus") or "SFX")
                if opts.get("PanRange") is not None:
                    kw["pan_range"] = float(opts.get("PanRange"))
                if opts.get("ElevationRange") is not None:
                    kw["elev_range"] = float(opts.get("ElevationRange"))
                if opts.get("MinDistance") is not None:
                    kw["min_dist"] = float(opts.get("MinDistance"))
                if opts.get("MaxDistance") is not None:
                    kw["max_dist"] = float(opts.get("MaxDistance"))
                if opts.get("Smooth") is not None:
                    kw["smooth"] = float(opts.get("Smooth"))
                if opts.get("MuffleCutoff") is not None:
                    kw["muffle_cutoff"] = float(opts.get("MuffleCutoff"))
                if opts.get("BrightGain") is not None:
                    kw["bright_gain"] = float(opts.get("BrightGain"))
                if opts.get("BrightFreq") is not None:
                    kw["bright_freq"] = float(opts.get("BrightFreq"))
            self.audio.play_hrtf2d(inst, bus=bus, fx=fx or None, **kw)
        sound.set("playHRTF2D", _sound_play_hrtf2d)

        def _sound_stop_hrtf2d(name=None):
            inst = self.scene.find(tostring(name)) if name else None
            if inst is not None:
                self.audio.stop_hrtf2d(inst)
        sound.set("stopHRTF2D", _sound_stop_hrtf2d)

        def _sound_set_camera2d(pos=None, zoom=None):
            self.audio.set_camera2d(position=to_vec(pos) if pos is not None else None,
                                    zoom=float(zoom) if zoom is not None else None)
        sound.set("setCamera2D", _sound_set_camera2d)
        g("sound", sound)

        # ---- mixer: buses (Master/Music/SFX/Voice/UI), volume em dB, roteamento ----
        mixer_t = LuaTable()
        mixer_t.set("setVolume", lambda bus="Master", vol=1.0: self.audio.mixer_bus.set_volume(
            tostring(bus), volume_linear=float(vol)))
        mixer_t.set("setVolumeDB", lambda bus="Master", db=0.0: self.audio.mixer_bus.set_volume(
            tostring(bus), db=float(db)))
        mixer_t.set("setMute", lambda bus="Master", muted=True: self.audio.mixer_bus.set_mute(
            tostring(bus), truthy(muted)))
        mixer_t.set("route", lambda source="", bus="SFX": self.audio.mixer_bus.route(
            tostring(source), tostring(bus)))
        mixer_t.set("dbToLinear", lambda db=0.0: audio_dsp.db_to_linear(float(db)))
        mixer_t.set("linearToDB", lambda lin=1.0: audio_dsp.linear_to_db(float(lin)))
        g("mixer", mixer_t)

        # ---- profiler ----
        profiler_t = LuaTable()
        profiler_t.set("enable", lambda on=True: setattr(self.profiler, "enabled", truthy(on)))
        profiler_t.set("report", lambda *a: self.profiler.report())
        profiler_t.set("fps", lambda *a: self.profiler.fps)
        profiler_t.set("reset", lambda *a: self.profiler.reset())
        g("profiler", profiler_t)

        # ---- post-processing (vinheta, bloom, aberracao, grading) ----
        postfx_t = LuaTable()

        def _postfx_set(opts=None):
            fx = getattr(self, "postfx", None)
            if fx is None:
                from .postfx import PostFXChain
                fx = self.postfx = PostFXChain()
            if isinstance(opts, LuaTable):
                kw = {}
                for lk, pk in (("Vignette", "vignette"), ("Bloom", "bloom"),
                              ("Aberration", "aberration"), ("Saturation", "saturation"),
                              ("Exposure", "exposure"), ("Enabled", "enabled")):
                    if opts.get(lk) is not None:
                        kw[pk] = opts.get(lk)
                fx.set(**kw)
        postfx_t.set("set", _postfx_set)
        g("postfx", postfx_t)

        # ---- camera helper: create.camera.Main{...} tambem funciona ----
        def _wait(*a):
            return None
        g("wait", _wait)

        # ---- camera 2D: create.camera2d.Main{...}; a global 'camera2d'
        # da acesso rapido a camera ativa e as conversoes de coordenada ----
        camera2d_t = LuaTable()
        camera2d_t.set("current", lambda *a: scene.camera2d)

        def _cam2d_set_active(obj=None):
            if obj is not None and getattr(obj, "cls", None) == "camera2d":
                scene.camera2d = obj
        camera2d_t.set("setActive", _cam2d_set_active)

        def _cam2d_world_to_screen(x=0, y=0):
            cam = scene.camera2d
            if cam is None:
                return vec_table(x, y)
            return cam.m_WorldToScreen(cam, x, y)
        camera2d_t.set("worldToScreen", _cam2d_world_to_screen)

        def _cam2d_screen_to_world(x=0, y=0):
            cam = scene.camera2d
            if cam is None:
                return vec_table(x, y)
            return cam.m_ScreenToWorld(cam, x, y)
        camera2d_t.set("screenToWorld", _cam2d_screen_to_world)
        g("camera2d", camera2d_t)

        # ---- luz 2D: create.light2d.Nome{...}; global 'light2d' controla
        # a luz ambiente e o limite de luzes por objeto (light filtering) ----
        light2d_t = LuaTable()

        def _ambient2d(c=None, intensity=None):
            if c is not None:
                self.ambient2d_color = to_color(c, self.ambient2d_color + (1.0,))[:3]
            if intensity is not None:
                self.ambient2d_intensity = float(intensity)
        light2d_t.set("ambient", _ambient2d)
        light2d_t.set("setMaxLights", lambda n=8: setattr(self, "max_lights2d", max(1, int(n or 8))))
        g("light2d", light2d_t)

        # ---- fisica (Stable.Physics / Area2D / CollisionBox / RayCast2D) ----
        physics = LuaTable()

        def _set_gravity(x=0, y=900, z=0):
            self.physics.set_gravity(x, y, z)
        physics.set("gravity", _set_gravity)
        physics.set("setGravity", _set_gravity)
        physics.set("getGravity", lambda *a: vec_table(*self.physics.get_gravity()))

        def _raycast(x1=0, y1=0, x2=0, y2=0):
            hit = self.physics.raycast(float(x1 or 0), float(y1 or 0), float(x2 or 0), float(y2 or 0))
            if hit is None:
                return [None]
            obj, hx, hy = hit
            return [obj, vec_table(hx, hy)]
        physics.set("raycast", _raycast)
        g("physics", physics)

        # ---- TweenService ----
        tween = LuaTable()

        def _tween_to(obj=None, props=None, duration=0.3, easing="ease_out", on_complete=None):
            self.tween.to(obj, props, float(duration or 0.3), tostring(easing or "ease_out"), on_complete)
        tween.set("to", _tween_to)
        tween.set("cancel", lambda obj=None, key=None: self.tween.cancel(obj, tostring(key) if key else None))
        g("tween", tween)

        # ---- Timer (delay / intervalo, sem precisar de loop manual) ----
        timer = LuaTable()

        def _timer_after(seconds=0.0, fn=None):
            self._timer_seq += 1
            handle = float(self._timer_seq)
            self.timers.append({"id": handle, "t": float(seconds or 0), "every": False, "fn": fn})
            return handle
        timer.set("after", _timer_after)

        def _timer_every(seconds=0.0, fn=None):
            self._timer_seq += 1
            handle = float(self._timer_seq)
            self.timers.append({"id": handle, "t": float(seconds or 0), "period": float(seconds or 0),
                                "every": True, "fn": fn})
            return handle
        timer.set("every", _timer_every)

        def _timer_cancel(handle=None):
            self.timers = [t for t in self.timers if t["id"] != handle]
        timer.set("cancel", _timer_cancel)
        g("timer", timer)
        g("Timer", timer)

        # ---- Scenes (trocar de cena/level sem carregar tudo na mao) ----
        scenes_t = LuaTable()

        def _scenes_register(name=None, fn=None):
            if name is not None and fn is not None:
                self.scene_registry[tostring(name)] = fn
        scenes_t.set("register", _scenes_register)
        scenes_t.set("current", lambda *a: self.current_scene_name)
        scenes_t.set("has", lambda name=None: tostring(name) in self.scene_registry)
        scenes_t.set("load", lambda name=None, fade=0.0: self.load_scene(name, fade))
        g("Scenes", scenes_t)
        g("scenes", scenes_t)

        # ---- Random (nomes "de jogo", alem do math.random padrao) ----
        rnd = LuaTable()
        rnd.set("seed", lambda s=None: _random.seed(s))
        rnd.set("int", lambda a=0, b=1: float(_random.randint(int(min(a, b)), int(max(a, b)))))
        rnd.set("float", lambda a=0.0, b=1.0: float(_random.uniform(a, b)))
        rnd.set("bool", lambda chance=0.5: bool(_random.random() < float(chance if chance is not None else 0.5)))

        def _rnd_pick(t=None):
            if isinstance(t, LuaTable):
                items = t.ipairs_list()
                return _random.choice(items) if items else None
            return None
        rnd.set("pick", _rnd_pick)
        g("Random", rnd)
        g("random", rnd)

        # ---- JSON ----
        json_t = LuaTable()

        def _json_encode(v=None):
            try:
                return _json.dumps(to_py(v))
            except Exception as ex:
                self.log("[json] erro ao codificar: %s" % ex)
                return None
        json_t.set("encode", _json_encode)
        json_t.set("stringify", _json_encode)

        def _json_decode(s=""):
            try:
                return from_py(_json.loads(tostring(s)))
            except Exception as ex:
                self.log("[json] erro ao decodificar: %s" % ex)
                return None
        json_t.set("decode", _json_decode)
        json_t.set("parse", _json_decode)
        g("JSON", json_t)
        g("json", json_t)

        # ---- SaveData (persistencia simples em arquivo JSON) ----
        save = LuaTable()

        def _save_path():
            try:
                d = perms.storage_dir()
            except Exception:
                d = self.base_dir
            return os.path.join(d, "savedata.json")

        def _save_load_all():
            p = _save_path()
            try:
                with open(p, "r") as fh:
                    return _json.load(fh)
            except Exception:
                return {}

        def _save_set(key=None, value=None):
            data = _save_load_all()
            data[tostring(key)] = to_py(value)
            try:
                with open(_save_path(), "w") as fh:
                    _json.dump(data, fh)
                return True
            except Exception as ex:
                self.log("[savedata] erro ao salvar: %s" % ex)
                return False
        save.set("set", _save_set)

        def _save_get(key=None, default=None):
            data = _save_load_all()
            k = tostring(key)
            if k in data:
                return from_py(data[k])
            return default
        save.set("get", _save_get)
        save.set("has", lambda key=None: tostring(key) in _save_load_all())

        def _save_remove(key=None):
            data = _save_load_all()
            data.pop(tostring(key), None)
            try:
                with open(_save_path(), "w") as fh:
                    _json.dump(data, fh)
            except Exception as ex:
                self.log("[savedata] erro ao remover: %s" % ex)
        save.set("remove", _save_remove)

        def _save_clear():
            try:
                with open(_save_path(), "w") as fh:
                    fh.write("{}")
                return True
            except Exception as ex:
                self.log("[savedata] erro ao limpar: %s" % ex)
                return False
        save.set("clear", lambda *a: _save_clear())
        g("SaveData", save)
        g("save", save)

    def _sound_op(self, name, op):
        inst = self.scene.find(name)
        if inst is None:
            self.log("[audio] som '%s' nao existe" % tostring(name))
            return
        getattr(self.audio, op)(inst)

    def mouse_button_name(self, btn):
        if isinstance(btn, str):
            return btn.lower()
        n = int(btn) if btn is not None else 1
        return {1: "left", 2: "right", 3: "middle"}.get(n, "left")

    def stop_camera(self):
        if self.camera_widget is not None:
            try:
                self.camera_widget.play = False
            except Exception:
                pass
            self.camera_widget = None

    def resolve(self, path):
        """Resolve um caminho relativo pra dentro de base_dir (pasta do
        projeto). Caminhos relativos com '..' que tentem escapar de
        base_dir sao bloqueados (zip slip / path traversal via
        fs.read/fs.write/require) - devolve um caminho que nao existe,
        entao a leitura/escrita simplesmente falha, sem crashar."""
        if os.path.isabs(path):
            return path
        base = os.path.abspath(self.base_dir)
        target = os.path.abspath(os.path.join(base, path))
        if target != base and not target.startswith(base + os.sep):
            return os.path.join(base, "__caminho_bloqueado__")
        return target

    # ------------------------------------------------------ modulos (require)
    def require(self, name):
        """Carrega outro script do projeto atual como modulo Lua: acha o
        codigo em `self.project_scripts` (ou, se nao for um projeto, tenta
        um arquivo .lua ao lado do script principal), executa ele e guarda
        o valor que ele devolver (`return ...`) num cache, do jeito que o
        `require` padrao do Lua funciona."""
        name = (name or "").strip()
        key = name[:-4] if name.lower().endswith(".lua") else name
        if key in self._modules:
            return self._modules[key]
        if key in self._loading_stack:
            raise LuaError("require: dependencia ciclica em '%s'" % name)
        source = self._find_module_source(key)
        if source is None:
            raise LuaError("require: modulo '%s' nao encontrado no projeto" % name)
        self._loading_stack.add(key)
        try:
            result = self.interp.execute(source, key + ".lua")
        finally:
            self._loading_stack.discard(key)
        value = result[0] if result else True
        self._modules[key] = value
        return value

    def _find_module_source(self, key):
        for cand in (key + ".lua", key):
            if cand in self.project_scripts:
                return self.project_scripts[cand]
        # fallback: scripts avulsos (fora do sistema de projetos) no disco
        for cand in (key + ".lua", key):
            p = self.resolve(cand)
            if os.path.isfile(p):
                try:
                    with open(p, "r") as fh:
                        return fh.read()
                except Exception:
                    pass
        return None

    # --------------------------------------------------------------- ciclo
    def reset(self):
        self.clear_scene()
        self.scene_registry = {}
        self.current_scene_name = None
        self.start_time = time.time()
        self.stop_camera()
        perms.mic_level_stop()
        self.mouse_buttons = set()
        self.hover_obj = None
        self._modules = {}
        self._loading_stack = set()
        self.interp = Interpreter(print_fn=self.log)
        self.interp.instruction_budget = DEFAULT_INSTRUCTION_BUDGET
        self.scene.runtime = self
        self.install_api()
        # Detalhe do ultimo erro que interrompeu um run_source (ou None se
        # a ultima execucao terminou bem) - a UI usa isso pra saber qual
        # linha marcar no editor. Formato: {"chunk": nome, "line": int,
        # "message": texto}.
        self.last_error = None

    def clear_scene(self):
        """Limpa objetos/fisica/tweens/timers/handlers, mas MANTEM o
        interpretador Lua vivo (variaveis/funcoes globais do script
        continuam existindo) - usado pelo Scenes.load entre uma cena e outra."""
        self.audio.stop_all()
        self.scene.clear()
        self.physics.reset()
        self.tween.reset()
        self.particles.reset()
        self.timers = []
        self.update_handlers = []
        self.touch_handlers = []
        self.key_handlers = []

    _LINE_RE = re.compile(r"\(linha (\d+)\)")

    def _record_error(self, chunkname, message):
        """Guarda o erro (com a linha, se der pra descobrir) pra UI marcar
        a linha certa no editor. Primeiro tenta achar um "(linha N)" ja
        embutido na mensagem (erros de sintaxe e alguns de execucao tem
        isso); se nao achar, usa a ultima linha que o interpretador tocou
        antes de estourar - nao e perfeito, mas acerta a esmagadora
        maioria dos casos (`nil value`, aritmetica invalida, etc.)."""
        m = self._LINE_RE.search(message)
        if m:
            line = int(m.group(1))
        else:
            line = getattr(self.interp, "current_line", 0) or 0
            if line:
                message = "%s (linha %d)" % (message, line)
        self.last_error = {"chunk": chunkname, "line": line or None, "message": message}
        return message

    def run_source(self, source, chunkname="script.lua"):
        self.reset()
        self.running = True
        try:
            self.interp.execute(source, chunkname)
            return True
        except LuaSyntaxError as ex:
            self.log("[erro de sintaxe] %s" % self._record_error(chunkname, str(ex)))
        except LuaError as ex:
            self.log("[erro] %s" % self._record_error(chunkname, tostring(ex.value)))
        except Exception as ex:  # noqa
            msg = "%s: %s" % (type(ex).__name__, ex)
            self.log("[erro interno] %s" % self._record_error(chunkname, msg))
        self.running = False
        return False

    def run_project(self, scripts, entry):
        """Executa um PROJETO inteiro: `scripts` e um dict
        {nome_arquivo.lua: codigo} e `entry` e o script de entrada. Os
        demais arquivos ficam disponiveis pro script de entrada (e uns
        pros outros) via `require(nome)`. Todos compartilham o mesmo
        ambiente Lua, entao podem criar e editar os mesmos objetos."""
        self.project_scripts = dict(scripts or {})
        src = self.project_scripts.get(entry)
        if src is None:
            self.reset()
            self.log("[erro] script de entrada '%s' nao encontrado no projeto" % entry)
            return False
        return self.run_source(src, entry)

    def stop(self):
        self.running = False
        self.audio.stop_all()
        self.stop_camera()
        perms.mic_level_stop()

    def load_scene(self, name, fade=0.0):
        name = tostring(name)
        fn = self.scene_registry.get(name)
        if fn is None:
            self.log("[Scenes] cena \"%s\" nao registrada (chame Scenes.register antes)" % name)
            return
        fade = float(fade or 0.0)
        if fade <= 0.0:
            self._swap_scene(name, fn)
            return
        half = max(fade / 2.0, 0.02)
        w, h = self.stage_size[0] + 4, self.stage_size[1] + 4
        overlay = self.scene.create("frame", "__fade_overlay")
        overlay.props.update({"Position": vec_table(-2, -2, 0), "Size": vec_table(w, h, 1),
                              "Color": (0.0, 0.0, 0.0, 0.0), "ZIndex": 99999.0})

        def _after_dark(_o):
            self._swap_scene(name, fn)
            ov2 = self.scene.create("frame", "__fade_overlay")
            ov2.props.update({"Position": vec_table(-2, -2, 0), "Size": vec_table(w, h, 1),
                              "Color": (0.0, 0.0, 0.0, 1.0), "ZIndex": 99999.0})
            self.tween.to(ov2, {"Color": (0.0, 0.0, 0.0, 0.0)}, half, "linear",
                          lambda o2: self.scene.remove(o2))
        self.tween.to(overlay, {"Color": (0.0, 0.0, 0.0, 1.0)}, half, "linear", _after_dark)

    def _swap_scene(self, name, fn):
        self.clear_scene()
        self.current_scene_name = name
        self.call(fn)

    def call(self, fn, *args):
        try:
            return first(self.interp.call_function(fn, list(args)))
        except LuaError as ex:
            self.log("[erro] %s" % tostring(ex.value))
        except Exception as ex:  # noqa
            self.log("[erro interno] %s: %s" % (type(ex).__name__, ex))
        return None

    def _update_camera2d(self, dt):
        """Segue o FollowTarget (com suavizacao opcional), aplica os
        Bounds e faz o tremor (Shake) decair a cada frame."""
        cam = self.scene.camera2d
        if cam is None or not cam.alive:
            return
        target = cam.props.get("FollowTarget")
        if target is not None and getattr(target, "alive", False):
            tx, ty, _ = target.pos()
            ox, oy, _ = to_vec(cam.props.get("FollowOffset"), (0.0, 0.0, 0.0))
            dxw, dyw = tx + ox, ty + oy
            cx, cy, cz = cam.pos()
            smooth = float(cam.props.get("FollowSmooth") or 0.0)
            if smooth > 0.0:
                k = 1.0 - math.exp(-dt / max(0.001, smooth))
                cx += (dxw - cx) * k
                cy += (dyw - cy) * k
            else:
                cx, cy = dxw, dyw
            cam.props["Position"] = vec_table(cx, cy, cz)
        bounds = cam.props.get("Bounds")
        if isinstance(bounds, LuaTable):
            x, y, z = cam.pos()
            minx, maxx = bounds.get("minX"), bounds.get("maxX")
            miny, maxy = bounds.get("minY"), bounds.get("maxY")
            if minx is not None:
                x = max(float(minx), x)
            if maxx is not None:
                x = min(float(maxx), x)
            if miny is not None:
                y = max(float(miny), y)
            if maxy is not None:
                y = min(float(maxy), y)
            cam.props["Position"] = vec_table(x, y, z)
        shake_time = getattr(cam, "_shake_time", 0.0)
        if shake_time > 0.0:
            shake_time -= dt
            if shake_time <= 0.0:
                cam._shake_time = 0.0
                cam._shake_offset = (0.0, 0.0, 0.0)
            else:
                cam._shake_time = shake_time
                k = shake_time / max(0.0001, getattr(cam, "_shake_total", shake_time))
                mag = getattr(cam, "_shake_mag", 0.0) * k
                cam._shake_offset = (_random.uniform(-mag, mag), _random.uniform(-mag, mag), 0.0)
        self.scene.dirty = True

    def _update_audio_hrtf2d(self, dt):
        """Sincroniza a 'camera' do audio HRTF 2D com o camera2d da cena (se
        houver um) e atualiza pan/elevacao de todo som HRTF 2D tocando."""
        cam = self.scene.camera2d
        if cam is not None and cam.alive:
            cx, cy, _cz = cam.pos()
            sx, sy, _sz = getattr(cam, "_shake_offset", (0.0, 0.0, 0.0))
            zoom = float(cam.props.get("Zoom") or 1.0)
            self.audio.set_camera2d(position=(cx + sx, cy + sy), zoom=zoom)
        self.audio.update_hrtf2d_all(self.scene, dt)

    def update(self, dt):
        if not self.running:
            return
        dt = safe_dt(dt)
        self._reset_budget()
        self._safe_step(self._update_camera2d, dt)
        self._safe_step(self.physics.step, dt)
        self._safe_step(self.tween.step, dt)
        self._safe_step(self.particles.step, dt)
        self._safe_step(self._step_timers, dt)
        self._safe_step(self._step_animations, dt)
        self._safe_step(self._update_audio_hrtf2d, dt)
        t = time.time() - self.start_time
        for fn in list(self.update_handlers):
            self.call(fn, float(dt), float(t))
        for obj in list(self.scene.objects):
            cb = obj.props.get("OnUpdate")
            if cb is not None:
                self.call(cb, obj, float(dt), float(t))

    def _safe_step(self, fn, *args):
        """Roda uma etapa interna do frame (fisica/tween/particulas/...)
        isolada: se uma delas quebrar, as outras (e o resto do jogo)
        continuam rodando no mesmo frame."""
        try:
            fn(*args)
        except LuaError as ex:
            self.log("[erro] %s" % tostring(ex.value))
        except Exception as ex:  # noqa
            self.log("[erro interno em %s] %s: %s" % (getattr(fn, "__name__", fn), type(ex).__name__, ex))

    def _reset_budget(self):
        """Reseta o orcamento de instrucoes Lua no inicio de cada frame,
        pra `while true do end` (ou qualquer loop infinito) travar so
        aquele frame com um erro, ao inves de travar o app inteiro."""
        self.interp._steps = 0

    def _step_timers(self, dt):
        if not self.timers:
            return
        due, keep = [], []
        for item in self.timers:
            item["t"] -= dt
            if item["t"] <= 0:
                due.append(item)
                if item.get("every"):
                    item["t"] += item.get("period", 0.0) or 0.0001
                    keep.append(item)
            else:
                keep.append(item)
        self.timers = keep
        for item in due:
            if item["fn"] is not None:
                self.call(item["fn"])

    def _step_animations(self, dt):
        for obj in self.scene.objects:
            if obj.cls != "image" or not obj.alive:
                continue
            speed = float(obj.props.get("FrameSpeed") or 0)
            if speed == 0 or not truthy(obj.props.get("Playing", True)):
                continue
            cols = max(1, int(obj.props.get("Columns") or 1))
            rows = max(1, int(obj.props.get("Rows") or 1))
            total = cols * rows
            if total <= 1:
                continue
            frame = float(obj.props.get("Frame") or 0) + speed * dt
            if frame >= total:
                if truthy(obj.props.get("Loop", True)):
                    frame = frame % total
                else:
                    frame = float(total - 1)
                    obj.props["Playing"] = False
                    cb = obj.props.get("OnAnimEnd")
                    if cb is not None:
                        self.call(cb, obj)
            obj.props["Frame"] = frame
            self.scene.dirty = True

    def dispatch_touch(self, x, y, phase="down", uid=0):
        self._reset_budget()
        for fn in list(self.touch_handlers):
            self.call(fn, float(x), float(y), phase, float(uid))

    def dispatch_click(self, inst):
        self._reset_budget()
        cb = inst.props.get("OnClick")
        if cb is not None:
            self.call(cb, inst)

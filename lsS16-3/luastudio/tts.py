# -*- coding: utf-8 -*-
import atexit
import hashlib
import os
import shutil
import tempfile
import threading
import time
from collections import OrderedDict

DEFAULT_LANG = "pt"
CACHE_LIMIT = 24
BUS_SOURCE = "__tts__"
BUS_NAME = "Voice"

_REGIONS = {
    "pt-br": ("pt", "com.br"),
    "pt-pt": ("pt", "pt"),
    "en-us": ("en", "com"),
    "en-gb": ("en", "co.uk"),
    "en-au": ("en", "com.au"),
    "en-in": ("en", "co.in"),
    "es-es": ("es", "es"),
    "es-mx": ("es", "com.mx"),
    "es-us": ("es", "com"),
    "fr-fr": ("fr", "fr"),
    "fr-ca": ("fr", "ca"),
}

COMMON_LANGS = {
    "pt": "Portugues", "en": "Ingles", "es": "Espanhol", "fr": "Frances",
    "de": "Alemao", "it": "Italiano", "ja": "Japones", "ko": "Coreano",
    "zh-CN": "Chines (simplificado)", "zh-TW": "Chines (tradicional)",
    "ru": "Russo", "ar": "Arabe", "hi": "Hindi", "nl": "Holandes",
    "pl": "Polones", "tr": "Turco", "sv": "Sueco", "uk": "Ucraniano",
    "el": "Grego", "id": "Indonesio", "vi": "Vietnamita", "th": "Tailandes",
}


def parse_lang(lang):
    code = str(lang or "").strip().replace("_", "-")
    if not code:
        return DEFAULT_LANG, "com"
    key = code.lower()
    if key in _REGIONS:
        return _REGIONS[key]
    if key in ("zh-cn", "zh-tw"):
        return code[:3].lower() + code[3:].upper(), "com"
    base = key.split("-")[0]
    return (base if "-" in key and base in COMMON_LANGS else key), "com"


class TTS(object):
    def __init__(self, log, get_mixer, get_volume):
        self.log = log or (lambda s: None)
        self._get_mixer = get_mixer
        self._get_volume = get_volume
        self.default_lang = DEFAULT_LANG
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._queue = []
        self._events = []
        self._worker = None
        self._speaking = False
        self._generation = 0
        self._tmp_dir = None
        self._cache = OrderedDict()
        self._playing_path = None

    def set_language(self, lang):
        self.default_lang = str(lang or "").strip() or DEFAULT_LANG

    def _dir(self):
        if self._tmp_dir is None or not os.path.isdir(self._tmp_dir):
            self._tmp_dir = tempfile.mkdtemp(prefix="luastudio_tts_")
            atexit.register(shutil.rmtree, self._tmp_dir, True)
        return self._tmp_dir

    def speak(self, text, lang=None, slow=False, volume=1.0, interrupt=False, on_finish=None):
        text = str(text if text is not None else "").strip()
        if not text:
            return False
        mixer = self._get_mixer()
        if mixer is None:
            self.log("[tts] sem audio (mixer desativado)")
            return False
        job = {
            "text": text,
            "lang": str(lang).strip() if lang else self.default_lang,
            "slow": bool(slow),
            "volume": max(0.0, min(1.0, float(volume))),
            "cb": on_finish,
        }
        with self._cond:
            if interrupt:
                self._cancel_locked()
            self._queue.append(job)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, daemon=True)
                self._worker.start()
            self._cond.notify()
        return True

    def stop(self):
        with self._cond:
            self._cancel_locked()
        self._halt_music()

    def _cancel_locked(self):
        self._generation += 1
        for job in self._queue:
            self._finish(job, False, "cancelado")
        self._queue = []
        self._cond.notify_all()

    def is_speaking(self):
        with self._lock:
            return self._speaking or bool(self._queue)

    def pending(self):
        with self._lock:
            return len(self._queue) + (1 if self._speaking else 0)

    def drain_events(self):
        with self._lock:
            items, self._events = self._events, []
        return items

    def _finish(self, job, ok, err=None):
        if job.get("cb") is not None:
            self._events.append((job["cb"], bool(ok), err))

    def _run(self):
        while True:
            with self._cond:
                if not self._queue:
                    self._cond.wait(timeout=5.0)
                    if not self._queue:
                        self._worker = None
                        return
                job = self._queue.pop(0)
                gen = self._generation
                self._speaking = True
            ok, err = False, None
            try:
                ok, err = self._say(job, gen)
            except Exception as ex:
                err = "%s: %s" % (type(ex).__name__, ex)
            if err and err != "cancelado":
                self.log("[tts] %s" % err)
            with self._lock:
                self._speaking = False
                self._finish(job, ok, err)

    def _cancelled(self, gen):
        with self._lock:
            return gen != self._generation

    def _say(self, job, gen):
        path = self._synthesize(job)
        if isinstance(path, tuple):
            return False, path[1]
        if self._cancelled(gen):
            return False, "cancelado"
        mixer = self._get_mixer()
        if mixer is None:
            return False, "mixer desativado"
        music = mixer.music
        self._playing_path = path
        try:
            music.load(path)
            music.set_volume(self._get_volume(job["volume"]))
            music.play()
            while music.get_busy():
                if self._cancelled(gen):
                    return False, "cancelado"
                time.sleep(0.05)
            if self._cancelled(gen):
                return False, "cancelado"
            return True, None
        finally:
            self._halt_music()
            self._playing_path = None

    def _halt_music(self):
        mixer = self._get_mixer()
        if mixer is None:
            return
        try:
            mixer.music.stop()
            if hasattr(mixer.music, "unload"):
                mixer.music.unload()
        except Exception:
            pass

    def _synthesize(self, job):
        lang, tld = parse_lang(job["lang"])
        key = hashlib.sha1(("%s|%s|%s|%s" % (lang, tld, job["slow"], job["text"])).encode("utf-8")).hexdigest()
        with self._lock:
            path = self._cache.get(key)
            if path and os.path.exists(path):
                self._cache.move_to_end(key)
                return path
        try:
            from gtts import gTTS
        except Exception:
            return ("err", "gTTS nao instalado (pip install gTTS)")
        path = os.path.join(self._dir(), key + ".mp3")
        try:
            gTTS(text=job["text"], lang=lang, tld=tld, slow=job["slow"]).save(path)
        except Exception as ex:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            name = type(ex).__name__
            if name == "gTTSError" or "lang" in str(ex).lower():
                return ("err", "falha no gTTS (idioma '%s' invalido ou sem internet): %s" % (lang, ex))
            return ("err", "falha ao gerar voz (%s): %s" % (name, ex))
        with self._lock:
            self._cache[key] = path
            while len(self._cache) > CACHE_LIMIT:
                old_key, old_path = next(iter(self._cache.items()))
                if old_path == self._playing_path:
                    self._cache.move_to_end(old_key)
                    break
                del self._cache[old_key]
                try:
                    os.remove(old_path)
                except Exception:
                    pass
        return path

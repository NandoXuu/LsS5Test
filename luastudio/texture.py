# -*- coding: utf-8 -*-
"""Sistema de texturas: filtragem (nearest/bilinear/trilinear+mipmap),
cache e batching de uploads para a GPU via Kivy.

Nao reinventa o carregamento de imagem (isso ja e feito com kivy.core.image /
PIL em stage.py); este modulo cuida de COMO a textura e amostrada e de
evitar uploads repetidos (batching) quando varios objetos reusam a mesma
imagem com o mesmo modo de filtragem.
"""

FILTER_NEAREST = "nearest"
FILTER_BILINEAR = "linear"
FILTER_TRILINEAR = "linear_mipmap_linear"
FILTER_NEAREST_MIPMAP = "nearest_mipmap_nearest"

_VALID = {FILTER_NEAREST, FILTER_BILINEAR, FILTER_TRILINEAR, FILTER_NEAREST_MIPMAP}


def normalize_filter(mode):
    m = str(mode or "linear").strip().lower()
    aliases = {
        "nearest": FILTER_NEAREST, "point": FILTER_NEAREST, "pixel": FILTER_NEAREST,
        "bilinear": FILTER_BILINEAR, "linear": FILTER_BILINEAR, "smooth": FILTER_BILINEAR,
        "trilinear": FILTER_TRILINEAR, "mipmap": FILTER_TRILINEAR,
        "nearest_mipmap": FILTER_NEAREST_MIPMAP,
    }
    return aliases.get(m, FILTER_BILINEAR)


class TextureManager(object):
    """Cache central de texturas Kivy com filtragem configuravel e batching:
    a mesma (source, filtro) so e enviada a GPU uma vez, mesmo se dezenas de
    instancias/objetos usarem a mesma imagem."""

    def __init__(self, resolver, log=None):
        self.resolver = resolver          # funcao source -> caminho absoluto
        self.log = log or (lambda s: None)
        self._cache = {}                  # (path, filter, wrap) -> Texture
        self._batch_pending = {}          # path -> set(filtros pedidos no frame)
        self.stats = {"uploads": 0, "hits": 0, "batched": 0}

    def get(self, source, filter_mode="linear", wrap=False, mipmap=None):
        if not source:
            return None
        path = self.resolver(source) if self.resolver else source
        if not path:
            return None
        fmode = normalize_filter(filter_mode)
        if mipmap is None:
            mipmap = fmode in (FILTER_TRILINEAR, FILTER_NEAREST_MIPMAP)
        key = (path, fmode, bool(wrap))
        cached = self._cache.get(key)
        if cached is not None:
            self.stats["hits"] += 1
            return cached
        # batching: se ja existe a mesma imagem com OUTRO filtro carregada,
        # reaproveita os pixels ja lidos do disco (evita re-decodificar o PNG/JPG)
        base_tex = self._find_any(path)
        try:
            from kivy.core.image import Image as CoreImage
            if base_tex is not None:
                tex = base_tex
                self.stats["batched"] += 1
            else:
                tex = CoreImage(path, mipmap=mipmap).texture
                self.stats["uploads"] += 1
            tex.mag_filter = FILTER_NEAREST if fmode == FILTER_NEAREST else FILTER_BILINEAR
            tex.min_filter = fmode
            tex.wrap = "repeat" if wrap else "clamp_to_edge"
        except Exception as ex:
            self.log("[textura] falha ao carregar %s: %s" % (source, ex))
            return None
        self._cache[key] = tex
        return tex

    def _find_any(self, path):
        for (p, _f, _w), tex in self._cache.items():
            if p == path:
                return tex
        return None

    def clear(self):
        self._cache.clear()
        self.stats = {"uploads": 0, "hits": 0, "batched": 0}

# -*- coding: utf-8 -*-
"""Sistema de fontes customizadas do LuaStudio.

Deixa o `create.text/label/button/frame` (prop `Font`) e o metodo
`obj:SetFont(...)` usarem qualquer fonte que o jogo trouxer em
`assets/fonts/`, em cinco formatos:

    .ttf / .otf  -> usados direto (e o que o Kivy/SDL2 ja sabe ler)
    .woff        -> descompactado pra .ttf/.otf de verdade (via fontTools)
    .woff2       -> idem, so que precisa tambem do pacote "brotli"
    .svg         -> fonte SVG "legada" (o <font> do SVG 1.1, glifo por
                    glifo com atributo `d`) e recompilada num .ttf real
                    (via fontTools: cada <glyph unicode="X" d="..."> vira
                    um glifo TrueType de verdade, curvas cubicas do SVG
                    convertidas pra quadraticas)

O jogo so precisa saber o NOME do arquivo - a busca e sempre relativa a
pasta do projeto:

    assets/fonts/minhafonte.ttf
    create.text.pl = { Text = "Ola", Font = "minhafonte.ttf" }
    -- ou depois:
    pl:SetFont("outrafonte.woff2")

Toda conversao e cacheada em disco (pasta `.lsfontcache/` dentro do
projeto, ao lado de `assets/`) usando um hash do arquivo de origem, entao
so acontece uma vez por fonte (ou de novo se o arquivo original mudar).
Nada aqui derruba o jogo: se a fonte nao for achada, o formato nao for
suportado, ou faltar uma biblioteca opcional (fonttools/brotli), o motor
avisa uma vez no console e volta pra fonte padrao.
"""

import os
import hashlib
import xml.etree.ElementTree as ET

NATIVE_EXTS = (".ttf", ".otf", ".ttc")
CONVERTIBLE_EXTS = (".woff", ".woff2", ".svg")
SUPPORTED_EXTS = NATIVE_EXTS + CONVERTIBLE_EXTS

# subpastas onde procuramos, em ordem, quando so um NOME de arquivo e
# passado em `Font` (sem caminho) - "assets/fonts" e a convencao pedida,
# as outras sao so pra nao quebrar por causa de maiusculas/minusculas
_FONT_SUBDIRS = ("assets/fonts", "Assets/fonts", "assets/Fonts", "Assets/Fonts", "assets")


def _strip_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


class FontManager(object):
    """Resolve o valor da prop `Font` pra um caminho .ttf/.otf que o Kivy
    (`kivy.core.text.Label(font_name=...)`) consegue usar direto,
    convertendo formatos web/legados quando precisa."""

    def __init__(self, resolve_fn, base_dir_fn, log=None):
        self._resolve_fn = resolve_fn      # runtime.resolve (mesma seguranca de caminho de imagem/audio)
        self._base_dir_fn = base_dir_fn    # runtime.base_dir (funcao ou valor fixo)
        self.log = log or (lambda s: None)
        self._cache = {}                   # valor bruto da prop Font -> caminho resolvido (ou None)
        self._warned = set()               # evita repetir o mesmo aviso toda hora no console

    # ------------------------------------------------------------ util
    def _project_dir(self):
        b = self._base_dir_fn() if callable(self._base_dir_fn) else self._base_dir_fn
        return os.path.abspath(b or ".")

    def _cache_dir(self):
        d = os.path.join(self._project_dir(), ".lsfontcache")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def _warn_once(self, key, msg):
        if key in self._warned:
            return
        self._warned.add(key)
        self.log("[fonte] %s" % msg)

    def clear_cache(self):
        """Chamado quando um projeto novo e carregado - a fonte com o
        mesmo nome de outro projeto pode ser outro arquivo."""
        self._cache.clear()
        self._warned.clear()

    # ------------------------------------------------------- localizar
    def _find_source(self, value):
        value = (value or "").strip().replace("\\", "/")
        if not value:
            return None
        base = os.path.basename(value)
        proj = self._project_dir()
        candidates = []
        direct = self._resolve_fn(value) if self._resolve_fn else None
        if direct:
            candidates.append(direct)
        for sub in _FONT_SUBDIRS:
            candidates.append(os.path.join(proj, sub.replace("/", os.sep), base))
        assets_root = os.path.join(proj, "assets")
        if os.path.isdir(assets_root):
            for root, _dirs, files in os.walk(assets_root):
                if base in files:
                    candidates.append(os.path.join(root, base))
        seen = set()
        for cand in candidates:
            if not cand:
                continue
            cand = os.path.abspath(cand)
            if cand in seen:
                continue
            seen.add(cand)
            if os.path.isfile(cand):
                return cand
        return None

    def _cache_path(self, src):
        try:
            st = os.stat(src)
            sig = "%s|%s|%s" % (src, st.st_mtime, st.st_size)
        except Exception:
            sig = src
        h = hashlib.sha1(sig.encode("utf-8", "replace")).hexdigest()[:16]
        name = os.path.splitext(os.path.basename(src))[0]
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
        return os.path.join(self._cache_dir(), "%s_%s.ttf" % (safe, h))

    # -------------------------------------------------------- publico
    def get(self, font_value):
        """`Font` (nome/caminho) -> caminho .ttf/.otf pronto pro Kivy, ou
        None (fica na fonte padrao do sistema) se nao der certo."""
        value = (font_value or "").strip()
        if not value:
            return None
        if value in self._cache:
            return self._cache[value]
        result = None
        src = self._find_source(value)
        if src is None:
            self._warn_once("nf:" + value,
                             "\"%s\" nao encontrada (procurei em assets/fonts/%s)"
                             % (value, os.path.basename(value)))
        else:
            ext = os.path.splitext(src)[1].lower()
            if ext in NATIVE_EXTS:
                result = src
            elif ext in (".woff", ".woff2"):
                result = self._convert_woff(src)
            elif ext == ".svg":
                result = self._convert_svg(src)
            else:
                self._warn_once("fmt:" + ext,
                                 "formato \"%s\" nao suportado (use .ttf/.otf/.woff/.woff2/.svg)" % ext)
        self._cache[value] = result
        return result

    # ------------------------------------------------------- WOFF/WOFF2
    def _convert_woff(self, src):
        out = self._cache_path(src)
        if os.path.isfile(out):
            return out
        try:
            from fontTools.ttLib import TTFont
        except Exception:
            self._warn_once("nofonttools",
                             "fontes .woff/.woff2 precisam do pacote \"fonttools\" "
                             "(pip install fonttools) - usando a fonte padrao por enquanto")
            return None
        try:
            font = TTFont(src)
            font.flavor = None
            tmp = out + ".part"
            font.save(tmp)
            os.replace(tmp, out)
            return out
        except Exception as ex:
            if "brotli" in str(ex).lower():
                self._warn_once("nobrotli",
                                 "fontes .woff2 tambem precisam do pacote \"brotli\" "
                                 "(pip install brotli) - usando a fonte padrao por enquanto")
            else:
                self._warn_once("woff:" + src,
                                 "nao consegui converter \"%s\": %s" % (os.path.basename(src), ex))
            return None

    # --------------------------------------------------- SVG (legada)
    def _convert_svg(self, src):
        out = self._cache_path(src)
        if os.path.isfile(out):
            return out
        try:
            from fontTools.svgLib.path import parse_path
            from fontTools.pens.ttGlyphPen import TTGlyphPen
            from fontTools.pens.cu2quPen import Cu2QuPen
            from fontTools.fontBuilder import FontBuilder
        except Exception:
            self._warn_once("nofonttools",
                             "fontes .svg precisam do pacote \"fonttools\" "
                             "(pip install fonttools) - usando a fonte padrao por enquanto")
            return None
        try:
            tmp = out + ".part"
            _svg_font_to_ttf(src, tmp, parse_path, TTGlyphPen, Cu2QuPen, FontBuilder)
            os.replace(tmp, out)
            return out
        except _NoGlyphsError:
            self._warn_once("svg:" + src,
                             "\"%s\" nao parece uma fonte SVG (formato <font> do SVG 1.1) - "
                             "confirma se e mesmo esse tipo de arquivo" % os.path.basename(src))
            return None
        except Exception as ex:
            self._warn_once("svg:" + src,
                             "nao consegui converter a fonte SVG \"%s\": %s"
                             % (os.path.basename(src), ex))
            return None


class _NoGlyphsError(Exception):
    pass


def _svg_font_to_ttf(src_path, out_path, parse_path, TTGlyphPen, Cu2QuPen, FontBuilder):
    """Le um arquivo de fonte SVG 1.1 legada (elemento <font>, um <glyph
    unicode="X" d="..."> por caractere) e recompila num .ttf de verdade.
    So mapeia glifos de UM codepoint (o formato tambem permite ligaduras
    com varios caracteres no atributo unicode; como isso e raro e o motor
    desenha texto caractere-a-caractere, ligaduras sao ignoradas aqui)."""
    tree = ET.parse(src_path)
    root = tree.getroot()
    for el in root.iter():
        el.tag = _strip_ns(el.tag)

    font_el = root.find(".//font")
    if font_el is None and _strip_ns(root.tag) == "font":
        font_el = root
    if font_el is None:
        raise _NoGlyphsError("sem elemento <font>")

    face_el = font_el.find("font-face")
    upm = int(float((face_el.get("units-per-em") if face_el is not None else None) or 1000))
    ascent = int(float((face_el.get("ascent") if face_el is not None else None) or upm * 0.8))
    descent_raw = float((face_el.get("descent") if face_el is not None else None) or -(upm * 0.2))
    descent = -abs(int(descent_raw))  # sTypoDescender e sempre negativo
    family = (face_el.get("font-family") if face_el is not None else None) or "CustomSVGFont"
    default_adv = int(float(font_el.get("horiz-adv-x") or upm * 0.6))

    def _outline(d):
        pen = TTGlyphPen(None)
        if d:
            cq = Cu2QuPen(pen, max_err=1.0, reverse_direction=True)
            parse_path(d, cq)
        return pen.glyph()

    glyph_order = [".notdef"]
    glyphs = {}
    advances = {}
    char_map = {}

    missing = font_el.find("missing-glyph")
    glyphs[".notdef"] = _outline(missing.get("d") if missing is not None else None)
    advances[".notdef"] = int(float(missing.get("horiz-adv-x"))) if (
        missing is not None and missing.get("horiz-adv-x")) else default_adv

    for g_el in font_el.findall("glyph"):
        uni = g_el.get("unicode")
        if not uni or len(uni) != 1:
            continue  # ignora glifos sem unicode e ligaduras multi-char
        cp = ord(uni)
        if cp in char_map:
            continue
        gname = "uni%04X" % cp
        glyphs[gname] = _outline(g_el.get("d"))
        adv = g_el.get("horiz-adv-x")
        advances[gname] = int(float(adv)) if adv is not None else default_adv
        char_map[cp] = gname
        glyph_order.append(gname)

    if not char_map:
        raise _NoGlyphsError("nenhum <glyph unicode=\"...\"> valido")

    fb = FontBuilder(upm, isTTF=True)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(char_map)
    fb.setupGlyf(glyphs)
    metrics = {gn: (advances.get(gn, default_adv), 0) for gn in glyph_order}
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ascent, descent=descent)
    style = "Regular"
    ps_name = (family.replace(" ", "") or "CustomSVGFont") + "-" + style
    fb.setupNameTable({
        "familyName": family, "styleName": style,
        "uniqueFontIdentifier": ps_name, "fullName": family + " " + style,
        "psName": ps_name, "version": "1.0",
    })
    fb.setupOS2(sTypoAscender=ascent, sTypoDescender=descent,
                usWinAscent=max(ascent, 0), usWinDescent=abs(descent))
    fb.setupPost()
    fb.save(out_path)

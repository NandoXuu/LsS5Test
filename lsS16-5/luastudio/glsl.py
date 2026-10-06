# -*- coding: utf-8 -*-
"""Shaders GLSL reais (GPU) do LuaStudio, via kivy.graphics.RenderContext.

Tres usos, todos com o mesmo registro `create.shader.<Nome>`:
  - elemento 2D:  `Shader = "Nome"` em qualquer objeto 2D
  - camada:       `Layer.SetShader(n, "Nome")`
  - tela inteira: `postfx.Add("Nome")` (encadeavel, varios passes)
  - material 3D:  `create.material.X = { Shader = "Nome", ... }`

Shaders 2D, Layer e PostFX recebem a imagem ja renderizada em `texture0`
(alias `uTexture`) e as coordenadas em `tex_coord0` (alias `vTexCoord`).
`vLocalUV` vai de 0 a 1 sobre o proprio elemento e `sampleContent(uv)` le a
imagem nessa coordenada local. O codigo pode ou nao incluir `$HEADER$`;
declaracoes que o motor ja fornece sao removidas para nao duplicar.
"""

import os
import re
import math

MAX_LIGHTS = 8

_VERSION_RE = re.compile(r'^\s*#version[^\n]*\n?', re.MULTILINE)
_IN_DECL_RE = re.compile(r'^(\s*)in(\s+)(\w+)(\s+)(\w+)(\s*;)', re.MULTILINE)
_OUT_DECL_RE = re.compile(r'^\s*out\s+vec4\s+(\w+)\s*;\s*\n?', re.MULTILINE)
_BAD_HASH_RE = re.compile(
    r'^([ \t]*)#(?!\s*(?:version|define|undef|if|ifdef|ifndef|else|elif|endif|error|pragma|extension|line)\b)', re.MULTILINE)
_TEXTURE_CALL_RE = re.compile(r'\btexture\s*\(')
_DECL_RE = re.compile(
    r'^[ \t]*(uniform|varying|attribute)\s+(?:(?:lowp|mediump|highp)\s+)?(\w+)\s+(\w+)\s*(\[[^\]]*\])?\s*;[ \t]*\n?',
    re.MULTILINE)
_MAIN_RE = re.compile(r'\bvoid\s+main\s*\(\s*(?:void)?\s*\)')
_HEADER_TOKEN = "$HEADER$"

AUTO_TIME = ("uTime", "u_time", "time", "iTime")
AUTO_RES = ("uResolution", "u_resolution", "resolution", "iResolution")
AUTO_COLOR = ("uColor",)
RESERVED_2D = ("texture0", "uTexture", "tex_coord0", "vTexCoord", "frag_color",
               "uRectUV", "vLocalUV", "uMask", "uTime", "uResolution", "uColor",
               "uScreenTexture", "uScreenOn", "uScreenSize", "uObjectSize", "uObjectPosition", "vScreenUV")


def adapt_fragment_source(src):
    """Aceita GLSL desktop (#version, in/out, texture()) ou GLSL ES e devolve
    o dialeto que o Kivy compila (OpenGL ES 2.0)."""
    if not src:
        return src
    out = _VERSION_RE.sub('', src)
    out = _IN_DECL_RE.sub(lambda m: "%svarying%s%s%s%s%s" % m.groups(), out)
    m = _OUT_DECL_RE.search(out)
    if m:
        outvar = m.group(1)
        out = _OUT_DECL_RE.sub('', out)
        out = re.sub(r'\b%s\b' % re.escape(outvar), 'gl_FragColor', out)
    elif 'gl_FragColor' not in out and re.search(r'\bfragColor\b', out):
        out = re.sub(r'\bfragColor\b', 'gl_FragColor', out)
    out = _TEXTURE_CALL_RE.sub('texture2D(', out)
    out = _BAD_HASH_RE.sub(lambda m: m.group(1) + '//', out)
    return out


def strip_header_token(src):
    return src.replace(_HEADER_TOKEN, "")


def strip_declarations(src, names):
    names = set(names)

    def repl(m):
        return "" if m.group(3) in names else m.group(0)
    return _DECL_RE.sub(repl, src)


def declared_uniforms(src):
    """nome -> (tipo, e_array) de tudo que o codigo declara como uniform."""
    found = {}
    for m in _DECL_RE.finditer(src):
        if m.group(1) == "uniform":
            found[m.group(3)] = (m.group(2), m.group(4) is not None)
    return found


def _declared_names(src):
    return set(m.group(3) for m in _DECL_RE.finditer(src))


# ------------------------------------------------------------- valores
def _table_to_list(value):
    from .lua import LuaTable
    if not isinstance(value, LuaTable):
        return value
    items = value.ipairs_list()
    if items:
        flat = []
        for it in items:
            flat.extend(_table_to_list(it) if isinstance(it, LuaTable) else [it])
        return flat
    for keys in (("x", "y", "z", "w"), ("r", "g", "b", "a")):
        vals = [value.get(k) for k in keys]
        vals = [v for v in vals if v is not None]
        if vals:
            return vals
    return []


def _as_floats(value):
    from .lua import LuaTable
    if isinstance(value, str):
        from .api import to_color
        return list(to_color(value))
    if isinstance(value, LuaTable):
        value = _table_to_list(value)
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.extend(_as_floats(v))
        return out
    if isinstance(value, bool):
        return [1.0 if value else 0.0]
    try:
        f = float(value)
    except (TypeError, ValueError):
        return [0.0]
    if f != f or f in (float("inf"), float("-inf")):
        f = 0.0
    return [f]


_VEC_SIZE = {"vec2": 2, "vec3": 3, "vec4": 4, "ivec2": 2, "ivec3": 3, "ivec4": 4,
             "bvec2": 2, "bvec3": 3, "bvec4": 4}


def coerce_uniform(value, gl_type, is_array=False):
    """Converte um valor vindo do Lua pro tipo Python que o Kivy espera para
    o tipo GLSL declarado (float->float, int/bool/sampler->int, vecN->lista)."""
    vals = _as_floats(value)
    if not vals:
        vals = [0.0]
    if is_array:
        return [float(v) for v in vals]
    if gl_type == "float":
        return float(vals[0])
    if gl_type in ("int", "bool", "sampler2D", "samplerCube"):
        return int(round(vals[0]))
    n = _VEC_SIZE.get(gl_type)
    if n:
        while len(vals) < n:
            vals.append(vals[-1] if len(vals) > 1 else vals[0])
        vals = vals[:n]
        if gl_type.startswith(("ivec", "bvec")):
            return [int(round(v)) for v in vals]
        return [float(v) for v in vals]
    return None


class Program(object):
    """Par vertex/fragment pronto pro RenderContext + tipos dos uniforms."""

    def __init__(self, entry, vs, fs):
        self.name = entry.name
        self.vs = vs
        self.fs = fs
        self.types = declared_uniforms(vs + "\n" + fs)
        self.signature = (entry.name, entry.signature(), hash(vs), hash(fs))

    @property
    def entry(self):
        return SHADERS.get(self.name)

    def values(self, time_value, resolution, color, rect_uv=(0.0, 0.0, 1.0, 1.0), overrides=None,
               extra=None):
        raw = {}
        for n in AUTO_TIME:
            raw[n] = time_value
        for n in AUTO_RES:
            raw[n] = list(resolution)
        for n in AUTO_COLOR:
            raw[n] = list(color)
        raw["uRectUV"] = list(rect_uv)
        if extra:
            raw.update(extra)
        raw.update(self.entry.uniforms)
        raw.update(self.entry.runtime)
        if overrides:
            raw.update(overrides)
        out = {}
        for name, value in raw.items():
            spec = self.types.get(name)
            if spec is None:
                continue
            if name in AUTO_RES and spec[0] == "vec3" and len(raw[name]) == 2:
                value = list(raw[name]) + [1.0]
            coerced = coerce_uniform(value, spec[0], spec[1])
            if coerced is not None:
                out[name] = coerced
        return out

    def apply(self, rc, values):
        for name, value in values.items():
            rc[name] = value


# ------------------------------------------------------ cabecalho 2D/UI
DEFAULT_2D_VERTEX = """$HEADER$
void main(void)
{
    frag_color = color * vec4(1.0, 1.0, 1.0, opacity);
    tex_coord0 = vTexCoords0;
    gl_Position = projection_mat * modelview_mat * vec4(vPosition.xy, 0.0, 1.0);
}
"""

_UI_HELPERS = """
uniform vec4 uRectUV;
#define uTexture texture0
#define vTexCoord tex_coord0
#define vLocalUV ((tex_coord0 - uRectUV.xy) / max(uRectUV.zw, vec2(0.0001)))
vec2 contentUV(vec2 local) { return uRectUV.xy + local * uRectUV.zw; }
uniform sampler2D uScreenTexture;
uniform float uScreenOn;
uniform vec2 uScreenSize;
uniform vec2 uObjectSize;
uniform vec2 uObjectPosition;
#define vScreenUV (gl_FragCoord.xy / uScreenSize)
vec4 sampleScreen(vec2 uv) { return texture2D(uScreenTexture, clamp(uv, 0.0, 1.0)); }
vec4 sampleBehind() { return sampleScreen(vScreenUV); }
vec4 sampleObject(vec2 local)
{
    if (local.x < 0.0 || local.x > 1.0 || local.y < 0.0 || local.y > 1.0)
        return vec4(0.0);
    return texture2D(texture0, contentUV(local));
}
vec4 sampleContent(vec2 local)
{
#ifdef LS_CONTENT_IS_SCREEN
    if (uScreenOn > 0.5)
        return sampleScreen(local);
#endif
    return sampleObject(local);
}
"""

MASK_ONLY_FRAGMENT = """$HEADER$
uniform sampler2D uMask;
void main(void)
{
    vec4 c = texture2D(texture0, tex_coord0);
    float m = texture2D(uMask, tex_coord0).a;
    gl_FragColor = vec4(c.rgb, c.a * m);
}
"""


_SCREEN_API = ("sampleScreen", "sampleBehind", "sampleObject", "uScreenTexture", "vScreenUV",
               "uScreenSize", "uObjectSize", "uObjectPosition")


def uses_screen_api(user_src):
    """True se o GLSL usa qualquer nome da API de tela (sampleScreen,
    sampleBehind, uScreenTexture, vScreenUV...). Nesse caso `sampleContent`
    e SEMPRE o conteudo do proprio objeto e a tela e lida pela API nova.
    Sem nenhum desses nomes, um shader de modo screen mantem o contrato
    antigo: `sampleContent(uv)` le o que esta atras, em UV de tela."""
    return any(re.search(r"\b%s\b" % n, user_src) for n in _SCREEN_API)


def _ui_header(user_src):
    declared = _declared_names(user_src)
    lines = []
    if not uses_screen_api(user_src):
        lines.append("#define LS_CONTENT_IS_SCREEN")
    if not any(n in declared for n in AUTO_TIME):
        lines.append("uniform float uTime;")
    if not any(n in declared for n in AUTO_RES):
        lines.append("uniform vec2 uResolution;")
    if "uColor" not in declared:
        lines.append("uniform vec4 uColor;")
    if "uMask" not in declared:
        lines.append("uniform sampler2D uMask;")
    return "\n".join(lines) + "\n" + _UI_HELPERS


def build_2d_fragment(raw_fragment, has_mask=False):
    frag = adapt_fragment_source(strip_header_token(raw_fragment))
    frag = strip_declarations(frag, RESERVED_2D)
    header = _ui_header(raw_fragment)
    if has_mask:
        renamed, n = _MAIN_RE.subn('void userMain()', frag, count=1)
        if n == 1:
            frag = renamed + """
void main(void)
{
    userMain();
    float m = texture2D(uMask, tex_coord0).a;
    gl_FragColor.a *= m;
}
"""
    return _HEADER_TOKEN + "\n" + header + "\n" + frag


def build_layer_sources(name, has_mask=False):
    prog = SHADERS.program_2d(name, has_mask)
    return prog.fs if prog is not None else None


# ---------------------------------------------------------- stdlib PBR 3D
def _pbr_stdlib():
    decl = []
    calls = []
    for i in range(MAX_LIGHTS):
        decl.append("uniform vec3 uLightPos%d;" % i)
        decl.append("uniform vec3 uLightColor%d;" % i)
        decl.append("uniform float uLightIsDirectional%d;" % i)
        calls.append(
            "    if (uLightCount > %d.5) Lo += pbrAccum(N, V, worldPos, albedo, roughness, metallic, F0, "
            "uLightPos%d, uLightColor%d, uLightIsDirectional%d);" % (i, i, i, i))
    return """
uniform sampler2D uAlbedoMap;
uniform float uHasAlbedoMap;
uniform sampler2D uNormalMap;
uniform float uHasNormalMap;
uniform vec4 uBaseColor;
uniform float uRoughness;
uniform float uMetallic;
uniform float uTime;
uniform vec3 uViewPos;
uniform float uAmbient;
uniform float uLightCount;
%s

varying vec2 vTexCoord;
varying vec3 vWorldPos;
varying vec3 vTangent;
varying vec3 vNormal;

const float PI = 3.14159265359;

vec3 unpackNormal(sampler2D nmap, vec2 uv, vec3 N, vec3 T) {
    vec3 tnormal = texture2D(nmap, uv).rgb * 2.0 - 1.0;
    T = normalize(T - N * dot(N, T));
    vec3 B = cross(N, T);
    mat3 TBN = mat3(T, B, N);
    return normalize(TBN * tnormal);
}

float distributionGGX(vec3 N, vec3 H, float roughness) {
    float a = roughness * roughness;
    float a2 = a * a;
    float NdotH = max(dot(N, H), 0.0);
    float NdotH2 = NdotH * NdotH;
    float denom = (NdotH2 * (a2 - 1.0) + 1.0);
    return a2 / (PI * denom * denom + 0.0001);
}

float geometrySchlickGGX(float NdotV, float roughness) {
    float r = roughness + 1.0;
    float k = (r * r) / 8.0;
    return NdotV / (NdotV * (1.0 - k) + k);
}

float geometrySmith(vec3 N, vec3 V, vec3 L, float roughness) {
    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);
    return geometrySchlickGGX(NdotV, roughness) * geometrySchlickGGX(NdotL, roughness);
}

vec3 fresnelSchlick(float cosTheta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

vec3 pbrAccum(vec3 N, vec3 V, vec3 worldPos, vec3 albedo, float roughness, float metallic,
              vec3 F0, vec3 lpos, vec3 lcolor, float isdir) {
    vec3 L;
    float atten;
    if (isdir > 0.5) {
        L = normalize(-lpos);
        atten = 1.0;
    } else {
        vec3 toL = lpos - worldPos;
        float dist = length(toL);
        L = toL / max(dist, 0.0001);
        atten = 1.0 / max(dist * dist, 0.01);
    }
    vec3 H = normalize(V + L);
    vec3 radiance = lcolor * atten;
    float NDF = distributionGGX(N, H, roughness);
    float G = geometrySmith(N, V, L, roughness);
    vec3 F = fresnelSchlick(max(dot(H, V), 0.0), F0);
    vec3 kD = (vec3(1.0) - F) * (1.0 - metallic);
    float denom = 4.0 * max(dot(N, V), 0.0) * max(dot(N, L), 0.0) + 0.0001;
    vec3 specular = (NDF * G * F) / denom;
    float NdotL = max(dot(N, L), 0.0);
    return (kD * albedo / PI + specular) * radiance * NdotL;
}

vec3 pbrLight(vec3 N, vec3 worldPos, vec3 albedo, float roughness, float metallic) {
    vec3 V = normalize(uViewPos - worldPos);
    vec3 F0 = mix(vec3(0.04), albedo, metallic);
    vec3 Lo = vec3(0.0);
%s
    return uAmbient * albedo + Lo;
}

vec3 sRGBToLinear(vec3 c) { return pow(c, vec3(2.2)); }
vec3 linearToSRGB(vec3 c) { return pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)); }
""" % ("\n".join(decl), "\n".join(calls))


PBR_STDLIB = _pbr_stdlib()
_PBR_NAMES = _declared_names(PBR_STDLIB)

DEFAULT_VERTEX = """$HEADER$
attribute vec3 aWorldPos;
attribute vec3 aNormal;
attribute vec3 aTangent;
varying vec2 vTexCoord;
varying vec3 vWorldPos;
varying vec3 vNormal;
varying vec3 vTangent;

void main(void) {
    frag_color = color * vec4(1.0, 1.0, 1.0, opacity);
    tex_coord0 = vTexCoords0;
    vTexCoord = vTexCoords0;
    vWorldPos = aWorldPos;
    vNormal = aNormal;
    vTangent = aTangent;
    gl_Position = projection_mat * modelview_mat * vec4(vPosition.xy, 0.0, 1.0);
}
"""

VERTEX_FORMAT = [
    (b'vPosition', 2, 'float'),
    (b'vTexCoords0', 2, 'float'),
    (b'aWorldPos', 3, 'float'),
    (b'aNormal', 3, 'float'),
    (b'aTangent', 3, 'float'),
]
FLOATS_PER_VERTEX = 2 + 2 + 3 + 3 + 3


def default_fragment_wrapper(user_source):
    user = strip_declarations(strip_header_token(user_source), _PBR_NAMES | {"texture0", "tex_coord0", "frag_color"})
    return _HEADER_TOKEN + "\n" + PBR_STDLIB + "\n" + user


# ------------------------------------------------------------- registries
class ShaderEntry(object):
    def __init__(self, name, fragment_src, vertex_src=None, uniforms=None, textures=None, wrap=False,
                 screen=False):
        self.name = name
        self.screen = bool(screen)
        self.raw_fragment = fragment_src
        self.raw_vertex = vertex_src
        self.uniforms = dict(uniforms or {})
        self.textures = dict(textures or {})
        self.wrap = bool(wrap)
        self.runtime = {}

    def signature(self):
        return (hash(str(self.raw_fragment)), hash(str(self.raw_vertex)))


def _table_to_dict(tbl):
    from .lua import LuaTable
    if isinstance(tbl, LuaTable):
        return dict((k, v) for k, v in tbl.items() if isinstance(k, str))
    if isinstance(tbl, dict):
        return dict(tbl)
    return {}


class MaterialEntry(object):
    def __init__(self, name, props):
        self.name = name
        self.shader = str(props.get("Shader") or "")
        self.albedo = props.get("Albedo") or props.get("Source") or None
        normal_map = props.get("NormalMap")
        if isinstance(normal_map, dict) or hasattr(normal_map, "get"):
            self.normal_map = normal_map.get("Source") or normal_map.get("source")
            self.roughness = normal_map.get("Roughness")
            self.metallic = normal_map.get("Metallic")
        else:
            self.normal_map = normal_map
            self.roughness = None
            self.metallic = None
        if self.roughness is None:
            self.roughness = props.get("Roughness")
        if self.metallic is None:
            self.metallic = props.get("Metallic")
        self.roughness = float(self.roughness) if self.roughness is not None else 0.5
        self.metallic = float(self.metallic) if self.metallic is not None else 0.0
        self.lit = bool(props.get("Lit", True))


class _Resolver(object):
    def __init__(self):
        self.path_resolver = None

    def set_path_resolver(self, fn):
        self.path_resolver = fn

    def resolve(self, src):
        if not src:
            return ""
        s = str(src)
        looks_like_path = s.strip().lower().endswith((".glsl", ".frag", ".vert", ".fs", ".vs")) and "\n" not in s
        if looks_like_path:
            path = self.path_resolver(s.strip()) if self.path_resolver else s.strip()
            if path and os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read()
        return s


class ShaderRegistry(object):
    def __init__(self):
        self._items = {}
        self._programs = {}
        self.resolver = _Resolver()

    def register(self, name, fragment_src, vertex_src=None, uniforms=None, textures=None, wrap=False,
                 screen=False):
        name = str(name)
        old = self._items.get(name)
        entry = ShaderEntry(name, fragment_src, vertex_src, uniforms, textures, wrap, screen)
        if old is not None:
            entry.runtime = old.runtime
        self._items[name] = entry

    def get(self, name):
        return self._items.get(str(name))

    def names(self):
        return list(self._items.keys())

    def set_uniform(self, name, key, value):
        entry = self.get(name)
        if entry is None:
            return False
        entry.runtime[str(key)] = value
        return True

    def get_uniform(self, name, key):
        entry = self.get(name)
        if entry is None:
            return None
        key = str(key)
        if key in entry.runtime:
            return entry.runtime[key]
        return entry.uniforms.get(key)

    def _vertex_for_2d(self, entry):
        if entry.raw_vertex:
            return _HEADER_TOKEN + "\n" + strip_header_token(self.resolver.resolve(entry.raw_vertex))
        return DEFAULT_2D_VERTEX

    def program_2d(self, name, has_mask=False):
        entry = self.get(name)
        if entry is None:
            return None
        key = (entry.name, entry.signature(), bool(has_mask))
        prog = self._programs.get(key)
        if prog is None:
            frag = build_2d_fragment(self.resolver.resolve(entry.raw_fragment), has_mask)
            prog = Program(entry, self._vertex_for_2d(entry), frag)
            self._programs[key] = prog
        return prog

    def build_sources(self, name):
        entry = self.get(name)
        if entry is None:
            return None
        frag_raw = self.resolver.resolve(entry.raw_fragment)
        fragment = default_fragment_wrapper(adapt_fragment_source(frag_raw))
        if entry.raw_vertex:
            vertex = _HEADER_TOKEN + "\n" + strip_header_token(self.resolver.resolve(entry.raw_vertex))
        else:
            vertex = DEFAULT_VERTEX
        return vertex, fragment

    def program_3d(self, name):
        entry = self.get(name)
        if entry is None:
            return None
        key = (entry.name, entry.signature(), "3d")
        prog = self._programs.get(key)
        if prog is None:
            vertex, fragment = self.build_sources(name)
            prog = Program(entry, vertex, fragment)
            self._programs[key] = prog
        return prog


class MaterialRegistry(object):
    def __init__(self):
        self._items = {}

    def register(self, name, props):
        self._items[str(name)] = MaterialEntry(str(name), props)

    def get(self, name):
        return self._items.get(str(name))

    def is_glsl_material(self, name):
        mat = self.get(name)
        if mat is None or not mat.shader:
            return False
        return SHADERS.get(mat.shader) is not None


SHADERS = ShaderRegistry()
MATERIALS = MaterialRegistry()


def sync_instance(inst):
    if inst.cls == "shader":
        frag = inst.props.get("Fragment") or inst.props.get("Frag") or inst.props.get("Source")
        vert = inst.props.get("Vertex")
        if frag:
            mode = str(inst.props.get("ShaderMode") or "").strip().lower()
            screen = bool(inst.props.get("Screen")) or mode == "screen"
            SHADERS.register(inst.name, frag, vert,
                             _table_to_dict(inst.props.get("Uniforms")),
                             _table_to_dict(inst.props.get("Textures")),
                             bool(inst.props.get("Wrap")), screen)
    elif inst.cls == "material":
        MATERIALS.register(inst.name, inst.props)


# --------------------------------------------------------- geometria (UV/TBN)
def face_uv(n, mirrored=False):
    """UV sintetico 0..1 pra uma face de n vertices (a malha nao tem UV
    proprio). Suficiente pra texturizar/normal-map cada face individualmente
    (nao e um mapeamento continuo entre faces vizinhas da mesma malha)."""
    if n == 3:
        uvs = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
    elif n == 4:
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    else:
        uvs = [(0.5 + 0.5 * math.cos(2 * math.pi * i / n),
                0.5 + 0.5 * math.sin(2 * math.pi * i / n)) for i in range(n)]
    if mirrored:
        uvs = uvs[::-1]
    return uvs


def face_tangent(world_pts, uvs):
    """Tangente constante por face (algoritmo padrao a partir dos deltas de
    UV). Suficiente pra normal mapping olhar 'pro lado certo' na textura."""
    if len(world_pts) < 3 or len(uvs) < 3:
        return (1.0, 0.0, 0.0)
    p0, p1, p2 = world_pts[0], world_pts[1], world_pts[2]
    uv0, uv1, uv2 = uvs[0], uvs[1], uvs[2]
    e1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    e2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
    du1, dv1 = uv1[0] - uv0[0], uv1[1] - uv0[1]
    du2, dv2 = uv2[0] - uv0[0], uv2[1] - uv0[1]
    denom = (du1 * dv2 - du2 * dv1)
    if abs(denom) < 1e-8:
        return (1.0, 0.0, 0.0)
    r = 1.0 / denom
    tx = (e1[0] * dv2 - e2[0] * dv1) * r
    ty = (e1[1] * dv2 - e2[1] * dv1) * r
    tz = (e1[2] * dv2 - e2[2] * dv1) * r
    n = math.sqrt(tx * tx + ty * ty + tz * tz) or 1.0
    return (tx / n, ty / n, tz / n)


def build_light_uniforms(lights, max_lights=MAX_LIGHTS):
    """Converte lighting.Light em listas por indice (uLightPos0.., uLightColor0..)."""
    pos, col, is_dir = [], [], []
    for lt in lights[:max_lights]:
        if not getattr(lt, "enabled", True):
            continue
        if lt.type == "directional":
            pos.append(list(lt.direction))
            is_dir.append(1.0)
        else:
            pos.append(list(lt.position))
            is_dir.append(0.0)
        col.append([lt.color[0] * lt.intensity, lt.color[1] * lt.intensity, lt.color[2] * lt.intensity])
    count = len(pos)
    while len(pos) < max_lights:
        pos.append([0.0, 0.0, 0.0])
        col.append([0.0, 0.0, 0.0])
        is_dir.append(0.0)
    return pos, col, is_dir, count

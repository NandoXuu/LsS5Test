# -*- coding: utf-8 -*-
"""Pos-processamento de tela inteira: a cena (3D + 2D) e renderizada num Fbo
e passa por uma cadeia de shaders GLSL. A cadeia mistura o efeito embutido
(vinheta, bloom, aberracao, saturacao, exposicao) com qualquer
`create.shader.<Nome>` registrado pelo jogo."""

from . import glsl as glsl_mod

BUILTIN_NAME = "__postfx_builtin__"

FRAGMENT_SHADER = """
uniform float vignette;
uniform float bloom;
uniform float aberration;
uniform float saturation;
uniform float exposure;

void main(void) {
    vec2 uv = tex_coord0;
    vec4 col;
    if (aberration > 0.0001) {
        float a = aberration * 0.006;
        col.r = texture2D(texture0, uv + vec2(a, 0.0)).r;
        col.g = texture2D(texture0, uv).g;
        col.b = texture2D(texture0, uv - vec2(a, 0.0)).b;
        col.a = texture2D(texture0, uv).a;
    } else {
        col = texture2D(texture0, uv);
    }

    if (bloom > 0.0001) {
        vec4 blur = vec4(0.0);
        float o = 0.0035;
        blur += texture2D(texture0, uv + vec2(o, 0.0));
        blur += texture2D(texture0, uv - vec2(o, 0.0));
        blur += texture2D(texture0, uv + vec2(0.0, o));
        blur += texture2D(texture0, uv - vec2(0.0, o));
        blur *= 0.25;
        col += max(blur - 0.65, 0.0) * bloom;
    }

    col.rgb *= exposure;
    float gray = dot(col.rgb, vec3(0.299, 0.587, 0.114));
    col.rgb = mix(vec3(gray), col.rgb, saturation);

    if (vignette > 0.0001) {
        vec2 d = uv - vec2(0.5);
        float v = smoothstep(0.85, 0.25, length(d) * 1.35);
        col.rgb *= mix(1.0 - vignette, 1.0, v);
    }

    gl_FragColor = col;
}
"""

glsl_mod.SHADERS.register(BUILTIN_NAME, FRAGMENT_SHADER)

_BUILTIN_KEYS = ("vignette", "bloom", "aberration", "saturation", "exposure")


class PostFXChain(object):
    def __init__(self):
        self.enabled = False
        self.vignette = 0.0
        self.bloom = 0.0
        self.aberration = 0.0
        self.saturation = 1.0
        self.exposure = 1.0
        self.passes = []

    def set(self, **kw):
        for k, v in kw.items():
            if hasattr(self, k) and k != "passes":
                setattr(self, k, bool(v) if k == "enabled" else float(v))
        if "enabled" not in kw:
            self.enabled = True

    def builtin_active(self):
        return self.enabled and (self.vignette > 0.0001 or self.bloom > 0.0001
                                 or self.aberration > 0.0001
                                 or abs(self.saturation - 1.0) > 0.0001
                                 or abs(self.exposure - 1.0) > 0.0001)

    def add(self, name, uniforms=None):
        name = str(name)
        for p in self.passes:
            if p["name"] == name:
                if uniforms:
                    p["uniforms"].update(uniforms)
                return
        self.passes.append({"name": name, "uniforms": dict(uniforms or {})})

    def remove(self, name):
        name = str(name)
        self.passes = [p for p in self.passes if p["name"] != name]

    def clear(self):
        self.passes = []

    def set_uniform(self, name, key, value):
        for p in self.passes:
            if p["name"] == str(name):
                p["uniforms"][str(key)] = value
                return True
        return False

    def names(self):
        return [p["name"] for p in self.passes]

    def uniforms(self):
        return dict((k, float(getattr(self, k))) for k in _BUILTIN_KEYS)

    def plan(self):
        out = []
        if self.builtin_active():
            out.append((BUILTIN_NAME, self.uniforms()))
        for p in self.passes:
            if glsl_mod.SHADERS.get(p["name"]) is not None:
                out.append((p["name"], p["uniforms"]))
        return out

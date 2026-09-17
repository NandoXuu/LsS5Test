# -*- coding: utf-8 -*-
"""Post-processing: renderiza a cena num Fbo (framebuffer offscreen) e
compoe o resultado na tela com um shader GLSL (vinheta, bloom simples,
aberracao cromatica e color grading). Usa o pipeline nativo do Kivy
(Fbo + RenderContext), entao nao adiciona nenhuma dependencia nova.

Desligado por padrao: so entra em uso quando o jogo chama postfx.enable(...)
via API Lua, pra nao mudar o caminho de renderizacao de projetos existentes.
"""

FRAGMENT_SHADER = """
$HEADER$

uniform vec2 resolution;
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
        vec4 bright = max(col - 0.65, 0.0) * bloom;
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


class PostFXChain(object):
    """Configuracao de post-processing aplicada por SceneWidget/Stage.
    Os campos sao lidos pelo widget que faz o Fbo -> shader -> tela."""

    def __init__(self):
        self.enabled = False
        self.vignette = 0.0
        self.bloom = 0.0
        self.aberration = 0.0
        self.saturation = 1.0
        self.exposure = 1.0

    def set(self, **kw):
        for k, v in kw.items():
            if hasattr(self, k):
                setattr(self, k, float(v) if k != "enabled" else bool(v))

    def uniforms(self):
        return {
            "vignette": float(self.vignette),
            "bloom": float(self.bloom),
            "aberration": float(self.aberration),
            "saturation": float(self.saturation),
            "exposure": float(self.exposure),
        }


def make_fx_widget(target_widget):
    """Cria um RenderContext com o shader de post-processing acoplado a
    'target_widget' (o Stage). Retorna None se o Kivy nao expuser GLSL
    customizado no ambiente atual (ex.: alguns backends restritos)."""
    try:
        from kivy.uix.effectwidget import EffectWidget, EffectBase
    except Exception:
        return None

    class _PostFXEffect(EffectBase):
        def __init__(self, chain, **kw):
            self.chain = chain
            EffectBase.__init__(self, **kw)
            self.glsl = FRAGMENT_SHADER

        def update_glsl(self, *_a):
            self.do_glsl()

    ew = EffectWidget()
    return ew, _PostFXEffect

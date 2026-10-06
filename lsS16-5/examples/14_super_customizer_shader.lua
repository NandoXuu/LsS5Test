-- 14: SUPER CUSTOMIZER - Shader por elemento (GLSL)
-- Um `create.shader.X` (que ja existia so pra materiais 3D) agora tambem
-- pode ser ligado a QUALQUER elemento 2D via `Shader = "Nome"`. O shader
-- recebe a propria renderizacao do elemento em `uTexture` (texture0) mais
-- uTime/uResolution/uColor prontos - e se o elemento tambem tiver Mask,
-- o motor multiplica o alpha final pela mascara sozinho.
app.background("#0e1220")

create.shader.Pulso = {
  Fragment = [[
#ifdef GL_ES
precision mediump float;
#endif
void main() {
    vec4 c = texture2D(uTexture, vTexCoord);
    float pulse = 0.6 + 0.4 * sin(uTime * 4.0);
    gl_FragColor = vec4(c.rgb * uColor.rgb * pulse, c.a);
}
]]
}

create.shader.Glitch = {
  Fragment = [[
#ifdef GL_ES
precision mediump float;
#endif
float rand(vec2 co) { return fract(sin(dot(co, vec2(12.9898,78.233))) * 43758.5453); }
void main() {
    vec2 uv = vTexCoord;
    float linha = floor(uv.y * 40.0);
    float desloc = (rand(vec2(linha, floor(uTime * 12.0))) - 0.5) * 0.06;
    uv.x += desloc;
    vec4 c = texture2D(uTexture, uv);
    gl_FragColor = c;
}
]]
}

create.label.Titulo = { Text = "Shader por elemento", Position = {20,16}, Size = {320,36},
  FontSize = 22, TextColor = "cyan" }

create.button.Botao = {
  Text = "PULSO", Position = {30,70}, Size = {260,70}, Color = "#2b6cf6", Radius = 16,
  Shader = "Pulso",
}

create.label.TextoGlitch = {
  Text = "SINAL INSTAVEL", Position = {30,170}, Size = {260,60}, FontSize = 26,
  TextColor = "#20ff90", Color = "#10141c", Radius = 8,
  Shader = "Glitch",
}

-- Shader + Mask juntos: o texto de fogo do exemplo 13, agora pulsando.
create.mask.TextoFogo2 = {
  Position = {30,260}, Size = {260,90}, Shape = "text", Text = "FIRE", FontSize = 56,
}
create.image.FogoPulsando = {
  Position = {30,260}, Size = {260,90}, Source = "assets/fire.png",
  Mask = "TextoFogo2", Shader = "Pulso",
}

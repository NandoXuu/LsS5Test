app.background("#0e1220")

create.label.Titulo = { Text = "Ondas e esteira infinita", Position = {20,16}, Size = {320,36},
  FontSize = 20, TextColor = "cyan" }

create.shader.Ondas = {
  Fragment = [[
uniform float u_frequency;
uniform float u_amplitude;
uniform float u_speed;
void main(void)
{
    vec2 uv = vLocalUV;
    float wave_x = sin(uv.y * u_frequency + uTime * u_speed) * u_amplitude;
    float wave_y = cos(uv.x * u_frequency + uTime * u_speed) * u_amplitude;
    gl_FragColor = sampleContent(uv + vec2(wave_x, wave_y)) * frag_color;
}
]],
  Uniforms = { u_frequency = 20, u_amplitude = 0.04, u_speed = 4 },
}

create.shader.Esteira = {
  Fragment = [[
uniform float u_frequency;
uniform float u_amplitude;
uniform float u_wave_speed;
uniform float u_scroll_speed;
uniform float u_scale;
void main(void)
{
    vec2 uv = vLocalUV * u_scale;
    uv -= uTime * u_scroll_speed;
    float wave_x = sin(uv.y * u_frequency + uTime * u_wave_speed) * u_amplitude;
    float wave_y = cos(uv.x * u_frequency + uTime * u_wave_speed) * u_amplitude;
    gl_FragColor = sampleContent(fract(uv + vec2(wave_x, wave_y))) * frag_color;
}
]],
  Uniforms = { u_frequency = 8, u_amplitude = 0.04, u_wave_speed = 3,
               u_scroll_speed = 0.25, u_scale = 2 },
}

create.frame.PainelOndas = {
  Position = {20,70}, Size = {300,140}, Radius = 14,
  Gradient1 = "#2b6cf6", Gradient2 = "#20ff90", Shader = "Ondas",
}

create.frame.PainelEsteira = {
  Position = {20,240}, Size = {300,140}, Radius = 14,
  Gradient1 = "#e0552b", Gradient2 = "#f6c12b", Shader = "Esteira",
}

onUpdate(function(dt, t)
  Shader.SetUniform("Ondas", "u_amplitude", 0.03 + 0.03 * math.sin(t))
  app.find("PainelEsteira"):SetUniform("u_scale", 2 + math.sin(t * 0.5))
end)

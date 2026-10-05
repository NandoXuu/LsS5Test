app.background("#0e1220")

create.shader.VidroPixel = {
  Screen = true,
  Fragment = [[
uniform float u_pixel;
uniform float u_opacity;
void main(void)
{
    vec4 obj = sampleObject(vLocalUV);
    vec2 cell = vec2(max(u_pixel, 1.0)) / uScreenSize;
    vec2 uv = (floor(vScreenUV / cell) + 0.5) * cell;
    vec3 behind = sampleContent(uv).rgb;
    gl_FragColor = vec4(mix(behind, obj.rgb, obj.a * u_opacity), obj.a);
}
]],
  Uniforms = { u_pixel = 10, u_opacity = 0.3 },
}

create.shader.Lente = {
  Fragment = [[
uniform float u_zoom;
void main(void)
{
    vec2 c = vLocalUV - 0.5;
    vec2 uv = vScreenUV - (c * (1.0 - 1.0 / u_zoom)) * (uObjectSize / uScreenSize);
    vec4 obj = sampleObject(vLocalUV);
    gl_FragColor = vec4(mix(sampleScreen(uv).rgb, obj.rgb, obj.a * 0.15), obj.a);
}
]],
  Uniforms = { u_zoom = 1.8 },
}

create.frame.Faixa1 = { Position = {0,90}, Size = {420,40}, Color = "#ff3d3d" }
create.frame.Faixa2 = { Position = {0,150}, Size = {420,40}, Color = "#ffd23d" }
create.frame.Faixa3 = { Position = {0,210}, Size = {420,40}, Color = "#3dff9a" }
create.label.Texto = { Text = "ATRAS DO VIDRO", Position = {20,260}, Size = {380,50},
  FontSize = 30, TextColor = "#ffffff" }

create.frame.Bola = { Position = {0,100}, Size = {70,70}, Radius = 35, Color = "#2b6cf6" }

create.button.Vidro = {
  Text = "VIDRO PIXEL", Position = {110,70}, Size = {200,140}, Color = "#ffffff", Radius = 18,
  Shader = "VidroPixel",
}

create.button.LenteBtn = {
  Text = "LENTE", Position = {110,230}, Size = {200,90}, Color = "#ffffff", Radius = 45,
  Shader = "Lente", ShaderMode = "screen",
}

create.label.Frente = { Text = "ESTE TEXTO NAO PIXELIZA", Position = {20,340}, Size = {380,40},
  FontSize = 18, TextColor = "cyan", ZIndex = 50 }

onUpdate(function(dt, t)
  Bola.Position = {200 + math.sin(t * 1.5) * 180, 100 + math.cos(t) * 70}
end)

create.shader.Escurecer = {
  Screen = true,
  Fragment = [[
void main(void)
{
    gl_FragColor = vec4(sampleContent(vScreenUV).rgb * 0.5, 1.0);
}
]],
}
create.frame.TelaToda = { FullScreen = true, Color = "#00000000", Shader = "Escurecer",
  ZIndex = 40, Visible = false }
create.label.Dica = { Text = "toque em LENTE: escurece a tela toda", Position = {20,390}, Size = {380,24},
  FontSize = 14, TextColor = "#9aa4b2", ZIndex = 60 }
LenteBtn.OnClick = function() TelaToda.Visible = not TelaToda.Visible end

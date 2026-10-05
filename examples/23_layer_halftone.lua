app.background("#f2ead3")

create.shader.Halftone = {
  Fragment = [[
uniform float u_dot_size;
uniform float u_color_levels;
uniform float u_dot_softness;
uniform float u_invert_dots;

void main(void)
{
    vec4 albedo = sampleContent(vLocalUV);
    vec3 poster = floor(albedo.rgb * u_color_levels) / u_color_levels;
    vec2 cell = fract(gl_FragCoord.xy / u_dot_size) - 0.5;
    float dist = length(cell);
    float lum = dot(poster, vec3(0.299, 0.587, 0.114));
    float radius = (u_invert_dots > 0.5 ? lum : 1.0 - lum) * 0.6;
    float mask = 1.0 - smoothstep(radius - u_dot_softness, radius, dist);
    vec3 cor = u_invert_dots > 0.5 ? mix(vec3(0.0), poster, mask) : mix(poster, vec3(0.0), mask);
    gl_FragColor = vec4(cor, albedo.a) * frag_color;
}
]],
  Uniforms = { u_dot_size = 12, u_color_levels = 4, u_dot_softness = 0.05, u_invert_dots = 0 },
}

create.frame.Sol = { Position = {40,60}, Size = {260,260}, Radius = 130,
  Gradient1 = "#ff3d3d", Gradient2 = "#ffd23d", RenderLayer = 1 }
create.label.Texto = { Text = "POP ART", Position = {40,340}, Size = {260,60},
  FontSize = 40, TextColor = "#2b6cf6", RenderLayer = 1 }

Layer.SetShader(1, "Halftone")

create.slider.Tamanho = { Position = {40,420}, Size = {260,30}, Min = 4, Max = 32, Value = 12,
  OnChange = function(self, v) Layer.SetUniform(1, "u_dot_size", v) end }

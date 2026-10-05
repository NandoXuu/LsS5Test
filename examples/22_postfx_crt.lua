app.background("#102030")

create.shader.CRT = {
  Fragment = [[
uniform vec2 u_resolution;
uniform float u_curvature;
uniform float u_corner_radius;
uniform float u_scanlines;
uniform float u_scanline_size;
uniform float u_vignette;
uniform float u_brightness;
uniform float u_interference;
uniform float u_roll_speed;

float hash(vec2 p) {
    vec2 p2 = fract(p * vec2(0.1031, 0.1030));
    p2 += dot(p2, p2.yx + 33.33);
    return fract((p2.x + p2.y) * p2.x);
}

void main(void)
{
    vec2 local = vLocalUV;
    vec2 px = local * u_resolution;
    float aspect = u_resolution.x / u_resolution.y;

    float wave = sin(local.y * 30.0 + uTime * 5.0) * 0.002 * u_interference;
    float jitter = hash(vec2(uTime, floor(px.y))) * 0.001 * u_interference;
    vec2 distorted = local + vec2(wave + jitter, 0.0);

    vec2 cc = distorted * 2.0 - 1.0;
    vec2 bent = cc + cc * cc.yx * cc.yx * u_curvature;
    bent *= 1.0 + u_curvature * 0.25;
    vec2 uv = bent * 0.5 + 0.5;

    vec2 half_size = vec2(aspect, 1.0);
    vec2 p = bent * half_size;
    vec2 q = abs(p) - (half_size - u_corner_radius);
    float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - u_corner_radius;
    float inside = clamp(0.5 - d / 0.005, 0.0, 1.0);

    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
        gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    vec3 col = sampleContent(uv).rgb;

    float line = px.y / u_scanline_size;
    float s = 0.5 + 0.5 * cos(line * 6.2832);
    float lum = dot(col, vec3(0.3, 0.59, 0.11));
    col *= mix(1.0, mix(1.0 - u_scanlines, 1.0, s), 1.0 - lum * 0.4);

    float scan_roll = mod(local.y + uTime * u_roll_speed, 1.0);
    float roll_line = smoothstep(0.45, 0.5, scan_roll) * (1.0 - smoothstep(0.5, 0.55, scan_roll));
    col *= mix(1.0, 0.85, roll_line * u_interference);

    float k = mod(floor(px.x), 3.0);
    vec3 stripe = (k < 1.0) ? vec3(1.0, 0.7, 0.7) : ((k < 2.0) ? vec3(0.7, 1.0, 0.7) : vec3(0.7, 0.7, 1.0));
    col *= mix(vec3(1.0), stripe * 1.15, 0.35);

    vec2 v = uv * (1.0 - uv);
    col *= mix(1.0, pow(clamp(v.x * v.y * 16.0, 0.0, 1.0), 0.3), u_vignette);

    col *= u_brightness;
    col += (hash(px + uTime) - 0.5) / 100.0 * u_interference;

    gl_FragColor = vec4(mix(vec3(0.0), col, inside), 1.0);
}
]],
  Uniforms = {
    u_curvature = 0.12, u_corner_radius = 0.05, u_scanlines = 0.4, u_scanline_size = 3,
    u_vignette = 0.45, u_brightness = 1.25, u_interference = 1, u_roll_speed = 0.3,
  },
}

create.label.Titulo = { Text = "PostFX: CRT", Position = {30,40}, Size = {300,40},
  FontSize = 28, TextColor = "#20ff90" }
create.button.Botao = { Text = "JOGAR", Position = {30,110}, Size = {260,70},
  Color = "#2b6cf6", Radius = 12,
  OnClick = function(self) postfx.Remove("CRT") end }
create.button.Ligar = { Text = "LIGAR CRT", Position = {30,200}, Size = {260,70},
  Color = "#e0552b", Radius = 12,
  OnClick = function(self) postfx.Add("CRT") end }

postfx.Add("CRT")

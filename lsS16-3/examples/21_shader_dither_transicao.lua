app.background("#0e1220")

create.shader.Dither = {
  Fragment = [[
uniform vec2 u_center;
uniform float u_radius;
uniform float u_pixel_size;
uniform vec2 u_resolution;
uniform vec2 u_dither_offset;
uniform int u_bayer_size;
uniform float u_falloff;
uniform vec4 u_transition_color;

float get_bayer2(vec2 coord) {
    int x = int(mod(coord.x, 2.0));
    int y = int(mod(coord.y, 2.0));
    int index = y * 2 + x;
    float val = 0.0;
    if (index == 1) val = 2.0;
    if (index == 2) val = 3.0;
    if (index == 3) val = 1.0;
    return (val + 0.5) / 4.0;
}

float get_bayer4(vec2 coord) {
    int x = int(mod(coord.x, 4.0));
    int y = int(mod(coord.y, 4.0));
    int index = y * 4 + x;
    float m[16];
    m[0] = 0.0;  m[1] = 8.0;  m[2] = 2.0;  m[3] = 10.0;
    m[4] = 12.0; m[5] = 4.0;  m[6] = 14.0; m[7] = 6.0;
    m[8] = 3.0;  m[9] = 11.0; m[10] = 1.0; m[11] = 9.0;
    m[12] = 15.0; m[13] = 7.0; m[14] = 13.0; m[15] = 5.0;
    for (int i = 0; i < 16; i++) {
        if (i == index) return (m[i] + 0.5) / 16.0;
    }
    return 0.0;
}

float get_dither(vec2 uv, vec2 step_size) {
    vec2 bayer_coord = floor(uv / step_size + 1.0e-5);
    vec2 grid_uv = bayer_coord * step_size + step_size * 0.5;
    float dist = distance(grid_uv, u_center);
    float t = pow(clamp(dist / max(u_radius, 0.0001), 0.0, 1.0), u_falloff);
    float threshold = u_bayer_size == 0 ? get_bayer2(bayer_coord) : get_bayer4(bayer_coord);
    return (threshold <= (1.0 - t)) ? 1.0 : 0.0;
}

float get_mask(vec2 uv, vec2 step_size, vec2 offset) {
    return max(get_dither(uv, step_size), get_dither(uv - offset, step_size));
}

void main(void)
{
    vec2 uv = vLocalUV;
    vec4 albedo = sampleContent(uv);
    vec2 uv_step = u_pixel_size / u_resolution;
    vec2 raw_offset_uv = floor(u_dither_offset + 0.5) * uv_step;
    vec2 sub_step = uv_step * 0.5;
    vec2 quantized_uv = floor(uv / uv_step) * uv_step;
    vec2 q1 = uv_step * 0.25;
    vec2 q3 = uv_step * 0.75;
    vec2 off = raw_offset_uv * 0.5;

    float v1 = get_mask(quantized_uv + q1, sub_step, off);
    float v2 = get_mask(quantized_uv + vec2(q3.x, q1.y), sub_step, off);
    float v3 = get_mask(quantized_uv + vec2(q1.x, q3.y), sub_step, off);
    float v4 = get_mask(quantized_uv + q3, sub_step, off);
    float dither = (v1 + v2 + v3 + v4) * 0.25;

    vec3 cor = mix(albedo.rgb, u_transition_color.rgb, dither * u_transition_color.a);
    gl_FragColor = vec4(cor, albedo.a) * frag_color;
}
]],
  Uniforms = {
    u_center = {0.5, 0.5}, u_radius = 0.45, u_pixel_size = 8,
    u_dither_offset = {2, 0}, u_bayer_size = 1, u_falloff = 2.5,
    u_transition_color = {0, 0, 0, 1},
  },
}

create.frame.Imagem = {
  Position = {20,60}, Size = {300,300}, Radius = 10,
  Gradient1 = "#ff8a3d", Gradient2 = "#3d7bff", Shader = "Dither",
}

create.slider.Pixel = { Position = {20,380}, Size = {300,30}, Min = 1, Max = 32, Value = 8,
  OnChange = function(self, v) Shader.SetUniform("Dither", "u_pixel_size", v) end }

onUpdate(function(dt, t)
  Shader.SetUniform("Dither", "u_radius", 0.4 + math.sin(t * 0.8) * 0.4)
end)

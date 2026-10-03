import math

MAX_NM_LIGHTS = 8

TYPE_POINT = 0.0
TYPE_DIRECTIONAL = 1.0
TYPE_SPOT = 2.0

DEFAULT_AMBIENT = 0.05

VERTEX_SHADER = """$HEADER$

uniform vec2 u_rect_pos;
varying vec2 v_pix;

void main(void)
{
    frag_color = color * vec4(1.0, 1.0, 1.0, opacity);
    tex_coord0 = vTexCoords0;
    v_pix = vPosition.xy - u_rect_pos;
    gl_Position = projection_mat * modelview_mat * vec4(vPosition.xy, 0.0, 1.0);
}
"""


def _light_uniforms():
    out = []
    for i in range(MAX_NM_LIGHTS):
        out.append("uniform vec2 u_l%d_pos;" % i)
        out.append("uniform vec3 u_l%d_color;" % i)
        out.append("uniform vec4 u_l%d_params;" % i)
        out.append("uniform vec4 u_l%d_dir;" % i)
    return "\n".join(out)


def _light_calls():
    out = []
    for i in range(MAX_NM_LIGHTS):
        out.append(
            "    if (u_light_count > %d.5)\n"
            "        add_light(pix, n, view_dir, u_l%d_pos, u_l%d_color, u_l%d_params, u_l%d_dir,\n"
            "                  diffuse_color, specular_color, spec_power, diffuse_light, specular_light);"
            % (i, i, i, i, i))
    return "\n".join(out)


FRAGMENT_TEMPLATE = """$HEADER$

varying vec2 v_pix;

uniform sampler2D normal_map;

uniform float u_light_count;
uniform float u_shadow;

uniform float normal_strength;
uniform float flip_y;
uniform float debug_normal;

uniform float albedo_strength;
uniform float roughness;
uniform float specular_strength;
uniform float metallic;
uniform float emission_strength;
uniform float ao;
uniform float ambient;
uniform vec3 ambient_color;

@LIGHT_UNIFORMS@

void add_light(vec2 pix, vec3 n, vec3 view_dir, vec2 lpos, vec3 lcolor, vec4 p, vec4 d,
               vec3 diffuse_color, vec3 specular_color, float spec_power,
               inout vec3 diffuse_light, inout vec3 specular_light)
{
    float radius = max(p.x, 1.0);
    float height = max(p.y, 1.0);
    float intensity = p.z;
    vec3 ldir;
    float atten;

    if (p.w > 0.5 && p.w < 1.5)
    {
        ldir = normalize(vec3(d.xy, height / 100.0));
        atten = 1.0;
    }
    else
    {
        vec2 diff = lpos - pix;
        float dist = length(diff);
        ldir = normalize(vec3(diff, height));
        atten = 1.0 - smoothstep(0.0, radius, dist);
        if (p.w > 1.5)
        {
            vec2 to_point = -diff / max(dist, 0.0001);
            float c = clamp(dot(to_point, d.xy), -1.0, 1.0);
            float edge = max(0.0, 1.0 - acos(c) / max(d.z, 0.0001));
            atten *= edge;
        }
    }

    atten *= u_shadow;

    float diffuse = max(dot(n, ldir), 0.0) * atten;

    vec3 half_dir = normalize(ldir + view_dir);
    float spec = pow(max(dot(n, half_dir), 0.0001), spec_power);
    spec *= atten;
    spec *= specular_strength;

    diffuse_light += diffuse_color * lcolor * diffuse * intensity;
    specular_light += specular_color * lcolor * spec * intensity;
}

void main(void)
{
    vec2 uv = tex_coord0;
    vec2 pix = v_pix;

    vec4 albedo_sample = texture2D(texture0, uv);
    vec4 normal_sample = texture2D(normal_map, uv);

    if (albedo_sample.a <= 0.001)
        discard;

    if (debug_normal > 0.5)
    {
        gl_FragColor = vec4(normal_sample.rgb, albedo_sample.a * frag_color.a);
        return;
    }

    vec3 albedo = albedo_sample.rgb * albedo_strength;

    vec3 n = normal_sample.rgb * 2.0 - 1.0;
    n.xy *= normal_strength;
    n.y *= flip_y;
    n = normalize(n);

    vec3 view_dir = vec3(0.0, 0.0, 1.0);
    float spec_power = mix(128.0, 2.0, roughness);

    vec3 specular_color = mix(vec3(0.04), albedo, metallic);
    vec3 diffuse_color = albedo * (1.0 - metallic);

    vec3 ambient_light = albedo * ambient_color * ambient * ao;
    vec3 diffuse_light = vec3(0.0);
    vec3 specular_light = vec3(0.0);

@LIGHT_CALLS@

    vec3 emission = albedo * emission_strength;

    vec3 result = ambient_light + diffuse_light + specular_light + emission;
    result = clamp(result, 0.0, 1.0);

    gl_FragColor = vec4(result, albedo_sample.a * frag_color.a);
}
"""


def fragment_source():
    return (FRAGMENT_TEMPLATE
            .replace("@LIGHT_UNIFORMS@", _light_uniforms())
            .replace("@LIGHT_CALLS@", _light_calls()))


def _num(value, default):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _flag(value):
    if value is None:
        return 0.0
    if isinstance(value, str):
        return 1.0 if value.strip().lower() in ("1", "true", "yes", "on") else 0.0
    return 1.0 if value else 0.0


def material_uniforms(props):
    return {
        "normal_strength": _num(props.get("NormalStrength"), 2.0),
        "flip_y": -1.0 if _flag(props.get("FlipY")) else 1.0,
        "debug_normal": _flag(props.get("ViewNormal")),
        "albedo_strength": _num(props.get("Albedo"), 1.0),
        "roughness": min(1.0, max(0.0, _num(props.get("Roughness"), 0.5))),
        "specular_strength": _num(props.get("Specular"), 0.5),
        "metallic": min(1.0, max(0.0, _num(props.get("Metallic"), 0.0))),
        "emission_strength": _num(props.get("Emission"), 0.0),
        "ao": _num(props.get("AO"), 1.0),
    }


def resolve_ambient(props, runtime_explicit, runtime_value, has_lights):
    own = props.get("Ambient")
    if own is not None and own != "":
        return _num(own, DEFAULT_AMBIENT)
    if runtime_explicit:
        return float(runtime_value)
    return DEFAULT_AMBIENT if has_lights else 1.0


def to_local(dx, dy, rot_deg, flip_x, flip_y):
    if flip_x:
        dx = -dx
    if flip_y:
        dy = -dy
    if rot_deg:
        r = math.radians(rot_deg)
        c, s = math.cos(r), math.sin(r)
        dx, dy = dx * c - dy * s, dx * s + dy * c
    return dx, dy


def light_to_uniforms(light, rect, center, to_stage, rot_deg, flip_x, flip_y):
    rx, ry = rect[0], rect[1]
    cx, cy = center
    sx, sy = to_stage(light.position[0], light.position[1])
    lx, ly = to_local(sx - cx, sy - cy, rot_deg, flip_x, flip_y)
    lx += cx - rx
    ly += cy - ry

    kind = TYPE_POINT
    dirx, diry, spot = 0.0, 0.0, 0.0
    ang = math.radians(light.direction)
    if light.type == "directional":
        kind = TYPE_DIRECTIONAL
        vx, vy = to_local(-math.cos(ang), math.sin(ang), rot_deg, flip_x, flip_y)
        n = math.hypot(vx, vy) or 1.0
        dirx, diry = vx / n, vy / n
    elif light.type == "spot":
        kind = TYPE_SPOT
        vx, vy = to_local(math.cos(ang), -math.sin(ang), rot_deg, flip_x, flip_y)
        n = math.hypot(vx, vy) or 1.0
        dirx, diry = vx / n, vy / n
        spot = math.radians(max(0.1, light.spot_angle))

    height = _num(getattr(light, "height", None), 100.0)
    return {
        "pos": [float(lx), float(ly)],
        "color": [float(light.color[0]), float(light.color[1]), float(light.color[2])],
        "params": [float(light.range), float(height), float(light.intensity), float(kind)],
        "dir": [float(dirx), float(diry), float(spot), 0.0],
    }

# -*- coding: utf-8 -*-
"""API propria do LuaStudio: objetos, propriedades e a global `create`."""

import math

from .lua import LuaTable, LuaError, tostring, truthy, as_list, first
from .vector import Vector2, Vector3, coerce_xyz

# --------------------------------------------------------------- utilidades
DEFAULT_COLORS = {
    "white": (1, 1, 1, 1), "black": (0, 0, 0, 1), "red": (0.90, 0.25, 0.25, 1),
    "green": (0.25, 0.80, 0.45, 1), "blue": (0.25, 0.55, 0.95, 1),
    "yellow": (0.98, 0.83, 0.25, 1), "orange": (0.98, 0.60, 0.20, 1),
    "purple": (0.65, 0.40, 0.95, 1), "cyan": (0.25, 0.85, 0.90, 1),
    "pink": (0.98, 0.45, 0.70, 1), "gray": (0.55, 0.55, 0.60, 1),
    "grey": (0.55, 0.55, 0.60, 1), "dark": (0.10, 0.11, 0.15, 1),
    "transparent": (0, 0, 0, 0),
}


def safe_float(v, fallback=0.0, limit=1.0e7):
    """Converte pra float protegendo contra NaN/Infinity (podem vir de
    divisao por zero, math malformado etc.) antes de qualquer valor
    chegar no renderer Kivy - NaN vira `fallback`, +-Infinity vira
    +-`limit` (um numero bem grande, mas finito e seguro de desenhar)."""
    try:
        f = float(v)
    except Exception:
        return fallback
    if f != f:  # NaN nunca e igual a si mesmo
        return fallback
    if f == float("inf"):
        return limit
    if f == float("-inf"):
        return -limit
    return f


def _clamp01(vals):
    return tuple(0.0 if x < 0.0 else (1.0 if x > 1.0 else x) for x in vals)


def to_color(v, default=(1, 1, 1, 1)):
    if v is None:
        return default
    if isinstance(v, (tuple, list)) and not isinstance(v, LuaTable):
        try:
            vals = [safe_float(x) for x in v[:4]]
            if len(vals) == 3:
                vals.append(1.0)
            if len(vals) >= 4:
                return _clamp01(vals[:4])
        except (TypeError, ValueError):
            return default
        return default
    if isinstance(v, str):
        s = v.strip().lower()
        if s in DEFAULT_COLORS:
            return DEFAULT_COLORS[s]
        if s.startswith("#"):
            s = s[1:]
            if len(s) == 3:
                s = "".join(c * 2 for c in s)
            if len(s) == 6:
                s += "ff"
            try:
                return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4, 6))
            except ValueError:
                return default
        return default
    if isinstance(v, LuaTable):
        nums = v.ipairs_list()
        if len(nums) >= 3:
            vals = [safe_float(x) for x in nums[:4]]
            if max(vals[:3]) > 1.0:
                vals = [x / 255.0 for x in vals]
            if len(vals) == 3:
                vals.append(1.0)
            return _clamp01(vals)
        r = v.get("r"); g = v.get("g"); b = v.get("b"); a = v.get("a")
        if r is not None:
            vals = [safe_float(r), safe_float(g), safe_float(b)]
            if max(vals) > 1.0:
                vals = [x / 255.0 for x in vals]
            vals.append(safe_float(a, 1.0) if a is not None else 1.0)
            return _clamp01(vals)
    return default


def to_vec(v, default=(0.0, 0.0, 0.0)):
    """Aceita {x=..,y=..,z=..}, {1,2,3}, numero, ou Vector2/Vector3."""
    if v is None:
        return tuple(default)
    if isinstance(v, (Vector2, Vector3)):
        x, y, z = coerce_xyz(v)
        return (safe_float(x), safe_float(y),
                safe_float(z) if isinstance(v, Vector3) else default[2] if len(default) > 2 else 0.0)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        f = safe_float(v)
        return (f, f, f)
    if isinstance(v, LuaTable):
        arr = v.ipairs_list()
        if arr:
            vals = [safe_float(x) for x in arr[:3]]
            while len(vals) < 3:
                vals.append(safe_float(default[len(vals)]))
            return tuple(vals)
        x = v.get("x"); y = v.get("y"); z = v.get("z")
        return (safe_float(x) if x is not None else safe_float(default[0]),
                safe_float(y) if y is not None else safe_float(default[1]),
                safe_float(z) if z is not None else safe_float(default[2]))
    return tuple(safe_float(x) for x in default)


def vec_table(x, y, z=0.0):
    t = LuaTable()
    x = safe_float(x); y = safe_float(y); z = safe_float(z)
    t.set("x", x); t.set("y", y); t.set("z", z)
    t.set(1.0, x); t.set(2.0, y); t.set(3.0, z)
    return t


# ---------------------------------------------------------------- Instance
CLASSES_2D = ("button", "label", "text", "frame", "image", "slider", "toggle", "particles")
CLASSES_2D_CAMERA = ("camera2d",)
CLASSES_2D_LIGHT = ("light2d",)
CLASSES_3D = ("part", "camera", "light")
CLASSES_OTHER = ("sound",)


# apelidos "estilo decorator" (Stroke.Color, Sprite.Image...) mapeados pras
# propriedades reais, sem precisar de uma arvore de nodes de verdade
PROP_ALIASES = {
    "StrokeColor": "BorderColor",
    "StrokeSize": "BorderSize",
    "Stroke": "BorderColor",
    "Gradient1": "GradientColor1",
    "Gradient2": "GradientColor2",
    "SpriteImage": "SpriteSource",
    "HoverScale": "PressScale",
    "ClickScale": "PressScale",
}


class Instance(object):
    """Objeto criado por `create.<classe>.<Nome>`."""

    def __init__(self, scene, cls, name):
        self.scene = scene
        self.cls = cls
        self.name = name
        self.alive = True
        self.props = {
            "Name": name,
            "Visible": True,
            "Position": vec_table(20, 20, 0),
            "Size": vec_table(200, 60, 1),
            "Scale": vec_table(1, 1, 1),
            "FlipX": False,
            "FlipY": False,
            "FlipZ": False,
            "KeepAspect": False,
            "Rotation": 0.0,
            "Rotation3": vec_table(0, 0, 0),
            "Color": "#2b6cf6" if cls == "button" else "#00000000",
            "TextColor": "white",
            "Text": name if cls in ("button", "label", "text") else "",
            "FontSize": 20.0,
            "ZIndex": 0.0,
            "Anchor": "topleft",
            "Radius": 12.0,
            "Shape": "cube",
            "Source": "",
            "Volume": 1.0,
            "Loop": False,
            "FOV": 70.0,
            "Target": vec_table(0, 0, 0),
            "Value": 0.0,
            "Min": 0.0,
            "Max": 100.0,
            "Checked": False,
            "OnClick": None,
            "OnChange": None,
            "OnUpdate": None,
            "OnMouseEnter": None,
            "OnMouseExit": None,
            # ---- fisica (Stable.Physics / Area2D / CollisionBox) ----
            "Physics": False,
            "Static": False,
            "IsArea": False,
            "Collidable": True,
            "Velocity": vec_table(0, 0, 0),
            "Gravity": None,
            "UseGravity": True,
            "Mass": 1.0,
            "Bounce": 0.2,
            "Friction": 0.0,
            "OnCollide": None,
            "OnAreaEnter": None,
            "OnAreaExit": None,
            # ---- spritesheet / animacao (Sprite.Animate) ----
            "Columns": 1.0,
            "Rows": 1.0,
            "Frame": 0.0,
            "FrameSpeed": 0.0,     # quadros por segundo; 0 = parado
            "Playing": True,
            "OnAnimEnd": None,
            # ---- decoradores de UI (Stroke/Gradient/Shadow/Padding/Sprite interno) ----
            "BorderSize": 1.4,
            "GradientColor1": None,
            "GradientColor2": None,
            "GradientDirection": 0.0,
            "ShadowColor": None,
            "ShadowBlur": 10.0,
            "ShadowOffset": vec_table(2, 3, 0),
            "Padding": 8.0,
            "SpriteSource": "",
            "SpriteScale": 1.0,
            "SpriteAnchor": "center",
            "SpriteKeepAspect": True,
            # ---- Transition (anima escala ao tocar, sem escrever script) ----
            "TransitionEnabled": False,
            "PressScale": 0.95,
            "TransitionSpeed": 0.12,
            # ---- camera 2D / luz 2D (compatibilidade com o sistema 3D) ----
            "IgnoreCamera": False,   # true = desenha fixo na tela (HUD), ignora Camera2D
            "Lit": False,            # true = recebe iluminacao dos create.light2d da cena
            "CastShadow": False,     # true = ocluidor pras sombras 2D e 3D
        }
        # ajustes por classe
        if cls == "label" or cls == "text":
            self.props["Color"] = "#00000000"
        if cls == "part":
            self.props["Position"] = vec_table(0, 0, 0)
            self.props["Size"] = vec_table(1, 1, 1)
            self.props["Color"] = "#4aa3ff"
        if cls == "camera":
            self.props["Position"] = vec_table(0, 2, -8)
        if cls == "light":
            self.props.update({
                "Position": vec_table(0, 6, 0), "Type": "directional",
                "Direction": vec_table(-0.4, -0.9, -0.5), "Color": "white",
                "Intensity": 1.0, "Range": 20.0, "SpotAngle": 45.0,
                "CastShadow": False, "Enabled": True, "Layer": 0,
                "Shininess": 32.0, "Specular": 0.35, "Rim": 0.0,
            })
        if cls == "image":
            self.props["Loop"] = True
        if cls == "particles":
            self.props.update({
                "Rate": 20.0, "Emitting": True, "MaxParticles": 200,
                "Direction": -90.0, "SpreadAngle": 30.0,
                "Speed": vec_table(60, 60, 0), "Life": vec_table(1.0, 1.0, 0),
                "SizeStart": 10.0, "SizeEnd": 2.0,
                "Color1": "orange", "Color2": None,
                "EmitBox": vec_table(0, 0, 0), "Gravity": None,
            })
            self._particles = []
            self._emit_acc = 0.0
        if cls == "camera2d":
            self.props.update({
                "Position": vec_table(0, 0, 0),
                "Zoom": 1.0,
                "Rotation": 0.0,
                "Active": True,
                "FollowTarget": None,
                "FollowSmooth": 0.0,     # 0 = gruda no alvo; >0 = suaviza (segundos)
                "FollowOffset": vec_table(0, 0, 0),
                "Bounds": None,          # {minX=,minY=,maxX=,maxY=} opcional
            })
            self._shake_offset = (0.0, 0.0, 0.0)
            self._shake_time = 0.0
            self._shake_total = 0.0
            self._shake_mag = 0.0
        if cls == "light2d":
            self.props.update({
                "Position": vec_table(0, 0, 0),
                "Type": "point",         # "point" | "directional" | "spot"
                "Direction": 0.0,        # graus, usado por directional/spot
                "Color": "white",
                "Intensity": 1.0,
                "Range": 220.0,
                "SpotAngle": 45.0,
                "CastShadow": False,
                "Enabled": True,
                "Layer": 0,
            })

    # -------- integracao com o interpretador --------
    def lua_index(self, key):
        key = PROP_ALIASES.get(str(key), str(key))
        method = getattr(self, "m_" + key, None)
        if method is not None:
            return method
        if key in self.props:
            return self.props[key]
        return None

    def lua_newindex(self, key, value):
        self.set_prop(str(key), value)

    def lua_call(self, args):
        """Permite `create.button.X{...}` e `obj{...}` para atualizar props."""
        if args:
            self.apply(args[0])
        return [self]

    # -------- propriedades --------
    def set_prop(self, key, value):
        key = PROP_ALIASES.get(str(key), str(key))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = safe_float(value)
        self.props[key] = value
        if key == "Name":
            self.scene.rename(self, tostring(value))
        self.scene.dirty = True

    def apply(self, spec):
        from .lua import LuaFunction
        if isinstance(spec, LuaTable):
            for k, v in spec.items():
                if isinstance(k, str):
                    self.set_prop(k, v)
        elif callable(spec) or isinstance(spec, LuaFunction):
            self.scene.runtime.call(spec, self)
        return self

    # -------- valores tipados (usados pelo renderer) --------
    def pos(self):
        return to_vec(self.props.get("Position"), (0, 0, 0))

    def size(self):
        return to_vec(self.props.get("Size"), (100, 40, 1))

    def rot(self):
        r = self.props.get("Rotation")
        return safe_float(r, 0.0)

    def rot3(self):
        return to_vec(self.props.get("Rotation3"), (0, 0, 0))

    # -------- escala independente por eixo (esticar/comprimir) --------
    def scale(self):
        return to_vec(self.props.get("Scale"), (1.0, 1.0, 1.0))

    def axis_scale(self):
        """Escala assinada por eixo: negativo = espelhado (FlipX/FlipY/FlipZ)."""
        sx, sy, sz = self.scale()
        if truthy(self.props.get("FlipX")):
            sx = -sx
        if truthy(self.props.get("FlipY")):
            sy = -sy
        if truthy(self.props.get("FlipZ")):
            sz = -sz
        return sx, sy, sz

    def eff_size(self):
        """Tamanho final (Size * Scale), sempre positivo por eixo."""
        w, h, d = self.size()
        asx, asy, asz = self.axis_scale()
        return (w * abs(asx), h * abs(asy), d * abs(asz))

    def color(self):
        return to_color(self.props.get("Color"), (0.2, 0.4, 0.9, 1))

    def text_color(self):
        return to_color(self.props.get("TextColor"), (1, 1, 1, 1))

    def visible(self):
        return truthy(self.props.get("Visible"))

    def zindex(self):
        try:
            return safe_float(self.props.get("ZIndex") or 0)
        except Exception:
            return 0.0

    # -------- metodos expostos ao Lua --------
    def m_Set(self, _self=None, spec=None):
        return self.apply(spec)

    def m_Destroy(self, *_a):
        self.alive = False
        self.scene.remove(self)

    def m_Move(self, _self=None, dx=0, dy=0, dz=0):
        x, y, z = self.pos()
        self.set_prop("Position", vec_table(x + float(dx or 0), y + float(dy or 0), z + float(dz or 0)))

    def m_MoveTo(self, _self=None, x=0, y=0, z=0):
        self.set_prop("Position", vec_table(float(x or 0), float(y or 0), float(z or 0)))

    def m_Rotate(self, _self=None, d=0, dy=None, dz=None):
        if self.cls in CLASSES_3D or dy is not None:
            rx, ry, rz = self.rot3()
            self.set_prop("Rotation3", vec_table(rx + float(d or 0), ry + float(dy or 0), rz + float(dz or 0)))
        else:
            self.set_prop("Rotation", self.rot() + float(d or 0))

    def m_SetText(self, _self=None, txt=""):
        self.set_prop("Text", tostring(txt))

    def m_SetColor(self, _self=None, c=None):
        self.set_prop("Color", c)

    def m_Show(self, *_a):
        self.set_prop("Visible", True)

    def m_Hide(self, *_a):
        self.set_prop("Visible", False)

    def m_GetPosition(self, *_a):
        x, y, z = self.pos()
        return vec_table(x, y, z)

    # -------- escala / espelhamento por eixo --------
    def m_SetScale(self, _self=None, x=1.0, y=None, z=None):
        """obj:SetScale(2) -> uniforme | obj:SetScale(2, 0.5) -> so estica X"""
        if y is None:
            y = x
        if z is None:
            z = 1.0
        self.set_prop("Scale", vec_table(float(x or 1.0), float(y or 1.0), float(z or 1.0)))

    def m_GetScale(self, *_a):
        x, y, z = self.scale()
        return vec_table(x, y, z)

    def m_Stretch(self, _self=None, sx=1.0, sy=1.0):
        """Atalho pra esticar/comprimir 2D nos dois eixos de uma vez."""
        _, _, z = self.scale()
        self.set_prop("Scale", vec_table(float(sx or 1.0), float(sy or 1.0), z))

    def m_Flip(self, _self=None, fx=None, fy=None, fz=None):
        if fx is not None:
            self.set_prop("FlipX", truthy(fx))
        if fy is not None:
            self.set_prop("FlipY", truthy(fy))
        if fz is not None:
            self.set_prop("FlipZ", truthy(fz))

    # -------- fisica --------
    def m_EnablePhysics(self, _self=None, opts=None):
        self.set_prop("Physics", True)
        if isinstance(opts, LuaTable):
            self.apply(opts)
        return self

    def m_DisablePhysics(self, *_a):
        self.set_prop("Physics", False)

    def m_MakeArea(self, _self=None, on=True):
        self.set_prop("Physics", True)
        self.set_prop("IsArea", True if on is None else truthy(on))
        return self

    def m_SetVelocity(self, _self=None, x=0, y=0, z=0):
        self.set_prop("Velocity", vec_table(float(x or 0), float(y or 0), float(z or 0)))

    def m_GetVelocity(self, *_a):
        x, y, z = to_vec(self.props.get("Velocity"), (0, 0, 0))
        return vec_table(x, y, z)

    def m_ApplyImpulse(self, _self=None, x=0, y=0, z=0):
        vx, vy, vz = to_vec(self.props.get("Velocity"), (0, 0, 0))
        self.set_prop("Velocity", vec_table(vx + float(x or 0), vy + float(y or 0), vz + float(z or 0)))

    # -------- camera 2D (mesma API/compatibilidade da camera 3D + extras) --------
    def m_Follow(self, _self=None, target=None, smooth=None, offset=None):
        """cam:Follow(objeto, suavizacao_seg, {x=,y=}) - camera acompanha um
        objeto todo frame; smooth=0 (padrao) gruda direto no alvo."""
        self.set_prop("FollowTarget", target)
        if smooth is not None:
            self.set_prop("FollowSmooth", float(smooth))
        if offset is not None:
            self.set_prop("FollowOffset", offset)
        return self

    def m_Unfollow(self, *_a):
        self.set_prop("FollowTarget", None)

    def m_Shake(self, _self=None, strength=10.0, duration=0.3):
        """cam:Shake(forca_px, duracao_seg) - tremor de camera com decaimento
        linear (screen shake), tipo impacto/explosao."""
        self._shake_mag = abs(float(strength or 0.0))
        self._shake_total = max(0.0001, float(duration or 0.0))
        self._shake_time = self._shake_total
        return self

    def m_StopShake(self, *_a):
        self._shake_time = 0.0
        self._shake_offset = (0.0, 0.0, 0.0)

    def m_SetZoom(self, _self=None, z=1.0):
        self.set_prop("Zoom", max(0.01, float(z or 1.0)))
        return self

    def m_GetZoom(self, *_a):
        return float(self.props.get("Zoom") or 1.0)

    def m_ZoomBy(self, _self=None, factor=1.0):
        z = float(self.props.get("Zoom") or 1.0) * float(factor or 1.0)
        self.set_prop("Zoom", max(0.01, z))
        return self

    def m_SetBounds(self, _self=None, minx=None, miny=None, maxx=None, maxy=None):
        """cam:SetBounds(minX, minY, maxX, maxY) - trava a camera dentro dos
        limites do mundo/mapa (qualquer lado pode ficar nil = sem limite)."""
        t = LuaTable()
        if minx is not None:
            t.set("minX", float(minx))
        if miny is not None:
            t.set("minY", float(miny))
        if maxx is not None:
            t.set("maxX", float(maxx))
        if maxy is not None:
            t.set("maxY", float(maxy))
        self.set_prop("Bounds", t)
        return self

    def m_ClearBounds(self, *_a):
        self.set_prop("Bounds", None)

    def m_WorldToScreen(self, _self=None, x=0.0, y=0.0):
        """Converte um ponto do mundo 2D pra coordenada de tela (considerando
        Position/Zoom/Rotation/tremor desta camera). Devolve {x=,y=,z=}."""
        w, h = self.scene.runtime.stage_size
        camx, camy, _ = self.pos()
        shx, shy, _ = self._shake_offset if hasattr(self, "_shake_offset") else (0.0, 0.0, 0.0)
        camx += shx; camy += shy
        zoom = max(0.01, float(self.props.get("Zoom") or 1.0))
        rot = math.radians(float(self.props.get("Rotation") or 0.0))
        cx, cy = w / 2.0, h / 2.0
        dx = float(x or 0.0) - camx
        dy = camy - float(y or 0.0)
        cr, sr = math.cos(rot), math.sin(rot)
        sxp = cx + zoom * (dx * cr + dy * sr)
        syp = cy + zoom * (-dx * sr + dy * cr)
        return vec_table(sxp, h - syp, 0)

    def m_ScreenToWorld(self, _self=None, x=0.0, y=0.0):
        """Inverso de WorldToScreen: coordenada de tela -> ponto do mundo."""
        w, h = self.scene.runtime.stage_size
        camx, camy, _ = self.pos()
        shx, shy, _ = self._shake_offset if hasattr(self, "_shake_offset") else (0.0, 0.0, 0.0)
        camx += shx; camy += shy
        zoom = max(0.01, float(self.props.get("Zoom") or 1.0))
        rot = math.radians(float(self.props.get("Rotation") or 0.0))
        cx, cy = w / 2.0, h / 2.0
        syp = h - float(y or 0.0)
        u = (float(x or 0.0) - cx) / zoom
        wv = (syp - cy) / zoom
        cr, sr = math.cos(rot), math.sin(rot)
        dx = u * cr - wv * sr
        dy = u * sr + wv * cr
        return vec_table(dx + camx, camy - dy, 0)

    # -------- spritesheet / animacao --------
    def m_GotoFrame(self, _self=None, idx=0):
        self.set_prop("Frame", float(int(idx or 0)))

    def m_Pause(self, *_a):
        self.set_prop("Playing", False)

    def m_Resume(self, *_a):
        self.set_prop("Playing", True)

    # -------- particulas --------
    def m_Burst(self, _self=None, count=10):
        self.scene.runtime.particles.burst(self, count)

    def m_StartEmit(self, *_a):
        self.set_prop("Emitting", True)

    def m_StopEmit(self, *_a):
        self.set_prop("Emitting", False)

    # -------- decoradores de UI (sem escrever script) --------
    def m_EnableTransition(self, _self=None, opts=None):
        self.set_prop("TransitionEnabled", True)
        if isinstance(opts, LuaTable):
            self.apply(opts)
        return self

    def m_DisableTransition(self, *_a):
        self.set_prop("TransitionEnabled", False)

    def padding(self):
        """(esquerda, direita, cima, baixo) a partir de Padding (numero ou tabela)."""
        p = self.props.get("Padding")
        if isinstance(p, LuaTable):
            l = p.get("left") or p.get("Left") or p.get(1.0) or 0
            r = p.get("right") or p.get("Right") or p.get(2.0) or l
            t = p.get("top") or p.get("Top") or p.get(3.0) or 0
            b = p.get("bottom") or p.get("Bottom") or p.get(4.0) or t
            return (float(l or 0), float(r or 0), float(t or 0), float(b or 0))
        v = float(p or 0)
        return (v, v, v, v)

    def m_Play(self, _self=None, *a):
        if self.cls == "sound":
            self.scene.runtime.audio.play(self)
        else:
            self.set_prop("Playing", True)

    def m_Stop(self, _self=None, *a):
        if self.cls == "sound":
            self.scene.runtime.audio.stop(self)
        else:
            self.set_prop("Playing", False)

    def __repr__(self):
        return "<%s %s>" % (self.cls, self.name)


# ------------------------------------------------------------------- Scene
class Scene(object):
    def __init__(self, runtime):
        self.runtime = runtime
        self.objects = []           # ordem de criacao
        self.by_name = {}
        self.dirty = True
        self.camera = None
        self.camera2d = None

    def create(self, cls, name, spec=None):
        if name in self.by_name:
            self.remove(self.by_name[name])
        inst = Instance(self, cls, name)
        self.objects.append(inst)
        self.by_name[name] = inst
        if cls == "camera" and self.camera is None:
            self.camera = inst
        if cls == "camera2d" and self.camera2d is None:
            self.camera2d = inst
        if spec is not None:
            inst.apply(spec)
        self.dirty = True
        return inst

    def rename(self, inst, newname):
        for k, v in list(self.by_name.items()):
            if v is inst and k != newname:
                del self.by_name[k]
        self.by_name[newname] = inst

    def remove(self, inst):
        if inst in self.objects:
            self.objects.remove(inst)
        for k, v in list(self.by_name.items()):
            if v is inst:
                del self.by_name[k]
        if self.camera is inst:
            self.camera = None
            for o in self.objects:
                if o.cls == "camera":
                    self.camera = o
                    break
        if self.camera2d is inst:
            self.camera2d = None
            for o in self.objects:
                if o.cls == "camera2d":
                    self.camera2d = o
                    break
        self.dirty = True

    def clear(self):
        self.objects = []
        self.by_name = {}
        self.camera = None
        self.camera2d = None
        self.dirty = True

    def find(self, name):
        return self.by_name.get(tostring(name))

    def of_class(self, cls):
        return [o for o in self.objects if o.cls == cls and o.alive]


# ------------------------------------------------------------ create proxy
class NameProxy(object):
    """`create.button.Hello` -> este objeto (ou a Instance ja criada)."""

    def __init__(self, scene, cls, name):
        self.scene = scene
        self.cls = cls
        self.name = name

    def lua_call(self, args):
        spec = args[0] if args else None
        inst = self.scene.create(self.cls, self.name, spec)
        return [inst]

    def lua_index(self, key):
        inst = self.scene.by_name.get(self.name)
        if inst is not None:
            return inst.lua_index(key)
        return None

    def lua_newindex(self, key, value):
        inst = self.scene.by_name.get(self.name)
        if inst is None:
            inst = self.scene.create(self.cls, self.name)
        inst.set_prop(str(key), value)


class ClassProxy(object):
    """`create.button` -> este objeto."""

    def __init__(self, scene, cls):
        self.scene = scene
        self.cls = cls

    def lua_index(self, key):
        name = tostring(key)
        inst = self.scene.by_name.get(name)
        if inst is not None and inst.cls == self.cls:
            return inst
        return NameProxy(self.scene, self.cls, name)

    def lua_newindex(self, key, value):
        """`create.button.Hello = { ... }`"""
        self.scene.create(self.cls, tostring(key), value)

    def lua_call(self, args):
        """`create.button{ Name = "X", ... }` (nome automatico)"""
        spec = args[0] if args else None
        name = None
        if isinstance(spec, LuaTable) and spec.get("Name"):
            name = tostring(spec.get("Name"))
        if not name:
            name = "%s_%d" % (self.cls, len(self.scene.objects) + 1)
        return [self.scene.create(self.cls, name, spec)]


class CreateRoot(object):
    """Global `create`."""

    ALL = CLASSES_2D + CLASSES_2D_CAMERA + CLASSES_2D_LIGHT + CLASSES_3D + CLASSES_OTHER

    def __init__(self, scene):
        self.scene = scene

    def lua_index(self, key):
        cls = tostring(key).lower()
        if cls in self.ALL:
            return ClassProxy(self.scene, cls)
        raise LuaError("classe desconhecida em create.%s (validas: %s)"
                       % (key, ", ".join(self.ALL)))

    def lua_newindex(self, key, value):
        raise LuaError("use create.<classe>.<Nome> = { ... }")

    def lua_call(self, args):
        cls = tostring(args[0]).lower() if args else ""
        spec = args[1] if len(args) > 1 else None
        return ClassProxy(self.scene, cls).lua_call([spec])

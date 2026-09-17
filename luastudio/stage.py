# -*- coding: utf-8 -*-
"""Palco Kivy: desenha UI 2D (com rotacao, gradiente, sombra, spritesheet)
e a cena 3D (matematica pura)."""

import math

from kivy.uix.widget import Widget
from kivy.graphics import (Color, Rectangle, Line, PushMatrix, PopMatrix,
                           Rotate, Translate, Scale, Mesh, RoundedRectangle)
from kivy.graphics.texture import Texture
from kivy.core.text import Label as CoreLabel
from kivy.core.image import Image as CoreImage

try:
    from kivy.core.window import Window
except Exception:
    Window = None

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except Exception:
    HAS_PIL = False

from . import render3d
from . import lighting as light_mod
from . import lighting2d as light2d_mod
from . import pipeline as pipeline_mod
from . import texture as texture_mod
from .api import to_color, to_vec, vec_table
from .lua import tostring, truthy


class Stage(Widget):
    def __init__(self, runtime, **kw):
        Widget.__init__(self, **kw)
        self.runtime = runtime
        self._textures = {}
        self._gradients = {}
        self._tex_manager = texture_mod.TextureManager(runtime.resolve, runtime.log)
        self._render_pipeline = pipeline_mod.RenderPipeline()
        self._pressed = {}   # touch.uid -> obj (pra desfazer o Transition no touch_up)
        self.bind(size=lambda *a: self.redraw(), pos=lambda *a: self.redraw())
        if Window is not None:
            try:
                Window.bind(mouse_pos=self._on_mouse_move)
            except Exception:
                pass

    # ------------------------------------------------------ coordenadas
    def to_stage(self, x, y):
        """Lua usa Y para baixo, Kivy para cima."""
        return self.x + x, self.y + self.height - y

    def hit_test(self, tx, ty):
        """Recebe coords Lua (y para baixo) e devolve o objeto 2D no topo.
        Compativel com Camera2D: objetos que nao sao IgnoreCamera sao
        testados no espaco do mundo (invertendo a transformacao da
        camera), os demais (HUD) sao testados direto em coords de tela."""
        best = None
        cam = self._active_camera2d()
        for obj in self.runtime.scene.objects:
            if obj.cls not in ("button", "label", "text", "frame", "image", "toggle"):
                continue
            if not obj.visible():
                continue
            qx, qy = self._local_point(tx, ty, obj, cam)
            px, py, _ = obj.pos()
            w, h, _ = obj.eff_size()
            if px <= qx <= px + w and py <= qy <= py + h:
                if best is None or obj.zindex() >= best.zindex():
                    best = obj
        return best

    # ------------------------------------------------------- camera 2D
    def _active_camera2d(self):
        cam = self.runtime.scene.camera2d
        if cam is None or not cam.alive:
            return None
        if not truthy(cam.props.get("Active", True)):
            return None
        return cam

    def _local_point(self, tx, ty, obj, cam=None):
        """Converte um ponto em coords de tela (Lua, relativas ao palco)
        pro espaco em que 'obj' esta desenhado: mundo (com Camera2D
        aplicada) ou tela direto, se obj.IgnoreCamera ou nao ha camera."""
        if cam is None or truthy(obj.props.get("IgnoreCamera")):
            return tx, ty
        return self._cam2d_screen_to_world(*self.to_stage(tx, ty), cam=cam)

    def _cam2d_screen_to_world(self, px, py, cam):
        """Inverso de _apply_camera2d_matrix: ponto em coords Kivy (mesmo
        referencial de self.x/self.y) -> ponto do mundo (coords Lua)."""
        camx, camy, _ = cam.pos()
        shx, shy, _ = getattr(cam, "_shake_offset", (0.0, 0.0, 0.0))
        camx += shx; camy += shy
        zoom = max(0.01, float(cam.props.get("Zoom") or 1.0))
        rot = math.radians(float(cam.props.get("Rotation") or 0.0))
        cx = self.x + self.width / 2.0
        cy = self.y + self.height / 2.0
        u = (px - cx) / zoom
        w = (py - cy) / zoom
        cr, sr = math.cos(rot), math.sin(rot)
        dx = u * cr - w * sr
        dy = u * sr + w * cr
        return dx + camx, camy - dy

    def _apply_camera2d_matrix(self, cam):
        """Empilha a transformacao (Translate/Scale/Rotate) da Camera2D no
        canvas: tudo desenhado depois disso fica em 'espaco do mundo',
        seguindo Position/Zoom/Rotation/tremor da camera ativa."""
        camx, camy, _ = cam.pos()
        shx, shy, _ = getattr(cam, "_shake_offset", (0.0, 0.0, 0.0))
        camx += shx; camy += shy
        zoom = max(0.01, float(cam.props.get("Zoom") or 1.0))
        rot = float(cam.props.get("Rotation") or 0.0)
        cx = self.x + self.width / 2.0
        cy = self.y + self.height / 2.0
        camkx, camky = self.to_stage(camx, camy)
        Translate(cx, cy, 0)
        Scale(zoom, zoom, 1)
        Rotate(angle=-rot, axis=(0, 0, 1))
        Translate(-camkx, -camky, 0)

    # ---------------------------------------------------------- desenho
    def redraw(self, *_a):
        rt = self.runtime
        rt.stage_size = (float(self.width), float(self.height))
        prof = getattr(rt, "profiler", None)
        if prof:
            prof.frame_start()
        self.canvas.clear()
        with self.canvas:
            Color(*rt.background)
            Rectangle(pos=self.pos, size=self.size)
            # 3D e 2D ficam isolados: um travar nao impede o outro de
            # aparecer (e o fundo acima sempre fica visivel, no minimo).
            try:
                if prof:
                    with prof.measure("render3d"):
                        self._draw_3d()
                else:
                    self._draw_3d()
            except Exception as ex:  # noqa
                rt.log("[erro no render 3D] %s: %s" % (type(ex).__name__, ex))
            try:
                if prof:
                    with prof.measure("render2d"):
                        self._draw_2d()
                else:
                    self._draw_2d()
            except Exception as ex:  # noqa
                rt.log("[erro no render 2D] %s: %s" % (type(ex).__name__, ex))
        if prof:
            prof.frame_end()

    # ---- luzes: converte instancias da classe "light" pra lighting.Light ----
    def _collect_lights(self):
        rt = self.runtime
        lights = []
        for obj in rt.scene.of_class("light"):
            if not obj.alive:
                continue
            lights.append(light_mod.Light(
                type=str(obj.props.get("Type") or "directional"),
                position=obj.pos(),
                direction=to_vec(obj.props.get("Direction"), (-0.4, -0.9, -0.5)),
                color=to_color(obj.props.get("Color"), (1, 1, 1, 1))[:3],
                intensity=float(obj.props.get("Intensity") or 1.0),
                range=float(obj.props.get("Range") or 20.0),
                spot_angle=float(obj.props.get("SpotAngle") or 45.0),
                casts_shadow=truthy(obj.props.get("CastShadow")),
                layer=obj.props.get("Layer") or 0,
                enabled=truthy(obj.props.get("Enabled", True)),
            ))
        if not lights:
            # sem luzes na cena: mantem o visual antigo (luz direcional fixa)
            lights = [light_mod.Light(type="directional", direction=(-0.4, -0.9, -0.5),
                                      color=(1, 1, 1), intensity=1.0)]
        return lights

    def _collect_occluders(self, parts):
        """Objetos 'part' marcados CastShadow=true viram ocluidores pra
        sombra planar dos outros objetos."""
        out = []
        for p in parts:
            if truthy(p.props.get("CastShadow")):
                bx, by, bz = p.size()
                out.append({"pos": p.pos(), "radius": (max(0.2, bx / 2.0), max(0.2, bz / 2.0))})
        return out

    # ---- 3D ----
    def _draw_3d(self):
        rt = self.runtime
        parts = rt.scene.of_class("part")
        if not parts:
            return
        cam_obj = rt.scene.camera
        if cam_obj is not None:
            cam = render3d.Camera(cam_obj.pos(),
                                  to_vec(cam_obj.props.get("Target"), (0, 0, 0)),
                                  float(cam_obj.props.get("FOV") or 70.0),
                                  cam_obj.rot3())
        else:
            cam = render3d.Camera()
        lights = self._collect_lights()
        occluders = self._collect_occluders(parts)
        faces = render3d.project_scene(parts, cam, self.width, self.height,
                                       lights=lights, pipeline=self._render_pipeline,
                                       occluders=occluders, ground_y=0.0)
        for face in faces:
            pts = [(self.x + p[0], self.y + p[1]) for p in face["points"]]
            flat = []
            for p in pts:
                flat.extend([p[0], p[1], 0, 0])
            n = len(pts)
            indices = []
            for i in range(1, n - 1):
                indices.extend([0, i, i + 1])
            Color(*face["color"])
            Mesh(vertices=flat, indices=indices, mode="triangles")
            Color(0, 0, 0, 0.25)
            Line(points=[c for p in pts for c in p], close=True, width=1.0)

    # ---- luzes 2D: converte instancias "light2d" pra lighting2d.Light2D ----
    def _collect_lights2d(self):
        rt = self.runtime
        lights = []
        for obj in rt.scene.of_class("light2d"):
            if not obj.alive:
                continue
            x, y, _ = obj.pos()
            lights.append(light2d_mod.Light2D(
                type=str(obj.props.get("Type") or "point"),
                position=(x, y),
                direction=float(obj.props.get("Direction") or 0.0),
                color=to_color(obj.props.get("Color"), (1, 1, 1, 1))[:3],
                intensity=float(obj.props.get("Intensity") or 1.0),
                range=float(obj.props.get("Range") or 220.0),
                spot_angle=float(obj.props.get("SpotAngle") or 45.0),
                casts_shadow=truthy(obj.props.get("CastShadow")),
                layer=obj.props.get("Layer") or 0,
                enabled=truthy(obj.props.get("Enabled", True)),
            ))
        return lights

    def _collect_occluders2d(self, objs, skip=None):
        out = []
        for o in objs:
            if o is skip:
                continue
            if truthy(o.props.get("CastShadow")):
                x, y, _ = o.pos()
                w, h, _ = o.eff_size()
                out.append((x, y, x + w, y + h))
        return out

    # ---- 2D ----
    def _draw_2d(self):
        objs = [o for o in self.runtime.scene.objects
                if o.cls in ("button", "label", "text", "frame", "image", "slider", "toggle", "particles")
                and o.visible()]
        objs.sort(key=lambda o: o.zindex())
        self._cur_2d_objs = objs
        self._cur_lights2d = self._collect_lights2d()
        cam = self._active_camera2d()
        if cam is not None:
            # objetos "de mundo" seguem a Camera2D; IgnoreCamera=true fica
            # fixo na tela (HUD), desenhado por cima, sem a transformacao
            world_objs = [o for o in objs if not truthy(o.props.get("IgnoreCamera"))]
            fixed_objs = [o for o in objs if truthy(o.props.get("IgnoreCamera"))]
            PushMatrix()
            try:
                self._apply_camera2d_matrix(cam)
                for obj in world_objs:
                    self._draw_one(obj)
            finally:
                # PopMatrix TEM que rodar mesmo se algo acima quebrar,
                # senao o resto do frame (HUD) herda a transformacao da
                # camera por engano.
                PopMatrix()
            for obj in fixed_objs:
                self._draw_one(obj)
        else:
            for obj in objs:
                self._draw_one(obj)

    def _draw_one(self, obj):
        """Desenha um objeto isolado: se ele tiver uma propriedade invalida
        (cor malformada, textura quebrada etc.) e o desenho falhar, so
        ESSE objeto some do frame - o resto da cena continua normal."""
        try:
            if obj.cls == "particles":
                self._draw_particles(obj)
            else:
                self._draw_widget(obj)
        except Exception as ex:  # noqa
            self.runtime.log("[erro ao desenhar '%s'] %s: %s"
                             % (obj.name, type(ex).__name__, ex))

    def _draw_particles(self, obj):
        parts = getattr(obj, "_particles", None)
        if not parts:
            return
        for p in parts:
            t = min(1.0, p["age"] / p["life"])
            size = p["size0"] + (p["size1"] - p["size0"]) * t
            if size <= 0:
                continue
            c1, c2 = p["c1"], p["c2"]
            r = c1[0] + (c2[0] - c1[0]) * t
            gg = c1[1] + (c2[1] - c1[1]) * t
            b = c1[2] + (c2[2] - c1[2]) * t
            a = c1[3] + (c2[3] - c1[3]) * t
            if a <= 0.003:
                continue
            sx, sy = self.to_stage(p["x"] - size / 2.0, p["y"] - size / 2.0)
            sy -= size
            Color(r, gg, b, a)
            Rectangle(pos=(sx, sy), size=(size, size))

    def _draw_widget(self, obj):
        x, y, _ = obj.pos()
        w, h, _ = obj.eff_size()
        w = max(w, 1.0)
        h = max(h, 1.0)
        asx, asy, _ = obj.axis_scale()
        flip_x = asx < 0
        flip_y = asy < 0
        sx, sy = self.to_stage(x, y)
        sy -= h
        rot = obj.rot()
        radius = float(obj.props.get("Radius") or 0)
        cx, cy = sx + w / 2.0, sy + h / 2.0

        PushMatrix()
        if flip_x or flip_y:
            Translate(cx, cy, 0)
            Scale(-1.0 if flip_x else 1.0, -1.0 if flip_y else 1.0, 1.0)
            Translate(-cx, -cy, 0)
        if rot:
            Translate(cx, cy, 0)
            Rotate(angle=-rot, axis=(0, 0, 1))
            Translate(-cx, -cy, 0)

        # ---- sombra (Shadow) - desenhada primeiro, atras de tudo ----
        shadow_c = obj.props.get("ShadowColor")
        if shadow_c is not None:
            sc = to_color(shadow_c, (0, 0, 0, 0.5))
            blur = max(0.0, float(obj.props.get("ShadowBlur") or 0))
            offx, offy, _ = to_vec(obj.props.get("ShadowOffset"), (2, 3, 0))
            layers = max(1, int(blur / 3) + 1)
            for i in range(layers, 0, -1):
                grow = blur * i / layers
                alpha = sc[3] * (1.0 - (i - 1) / float(layers)) * 0.5
                if alpha <= 0.003:
                    continue
                Color(sc[0], sc[1], sc[2], alpha)
                rad_i = max(radius + grow * 0.4, 0.01)
                RoundedRectangle(pos=(sx - grow / 2.0 + offx, sy - grow / 2.0 - offy),
                                 size=(w + grow, h + grow), radius=[rad_i])

        # ---- luz 2D (Lit=true): tinge a cor de preenchimento e as
        # texturas (imagem/sprite) com a soma das create.light2d + ambient
        lit_tint = (1.0, 1.0, 1.0)
        if truthy(obj.props.get("Lit")) and self._cur_lights2d:
            cxp, cyp = x + w / 2.0, y + h / 2.0
            filtered = light2d_mod.filter_lights2d(
                self._cur_lights2d, (cxp, cyp),
                max_lights=int(getattr(self.runtime, "max_lights2d", 8) or 8))
            occluders = self._collect_occluders2d(getattr(self, "_cur_2d_objs", []), skip=obj)
            shadow = (light2d_mod.shadow_factor2d((cxp, cyp), filtered, occluders)
                     if occluders else 1.0)
            ambient = float(getattr(self.runtime, "ambient2d_intensity", 1.0))
            acolor = getattr(self.runtime, "ambient2d_color", (1.0, 1.0, 1.0))
            lit_tint = light2d_mod.shade_point2d((cxp, cyp), (1.0, 1.0, 1.0, 1.0), filtered,
                                                 ambient=ambient, ambient_color=acolor,
                                                 shadow_factor=shadow)[:3]

        # ---- preenchimento: gradiente (se configurado) ou cor solida ----
        col = obj.color()
        if truthy(obj.props.get("Lit")) and self._cur_lights2d:
            col = (col[0] * lit_tint[0], col[1] * lit_tint[1], col[2] * lit_tint[2],
                  col[3] if len(col) > 3 else 1.0)
        g1 = obj.props.get("GradientColor1")
        g2 = obj.props.get("GradientColor2")
        grad_tex = None
        if g1 is not None and g2 is not None:
            grad_tex = self._gradient_texture(to_color(g1), to_color(g2),
                                              float(obj.props.get("GradientDirection") or 0))
        if grad_tex is not None:
            Color(1, 1, 1, col[3] if col[3] > 0 else 1.0)
            if radius > 0:
                RoundedRectangle(pos=(sx, sy), size=(w, h), radius=[radius], texture=grad_tex)
            else:
                Rectangle(pos=(sx, sy), size=(w, h), texture=grad_tex)
        elif col[3] > 0:
            Color(*col)
            if radius > 0:
                RoundedRectangle(pos=(sx, sy), size=(w, h), radius=[radius])
            else:
                Rectangle(pos=(sx, sy), size=(w, h))

        # ---- borda (Stroke) ----
        border = obj.props.get("BorderColor")
        if border is not None:
            bsize = float(obj.props.get("BorderSize") or 1.4)
            Color(*to_color(border))
            Line(rounded_rectangle=(sx, sy, w, h, max(radius, 0.01)), width=bsize)

        # ---- imagem principal (Source) - com suporte a spritesheet ----
        if obj.cls == "image":
            src = str(obj.props.get("Source") or "")
            if src.strip().lower() == "camera":
                tex = self._camera_texture()
            else:
                tex = self._texture(src)
            if tex is not None:
                cols = max(1, int(obj.props.get("Columns") or 1))
                rows = max(1, int(obj.props.get("Rows") or 1))
                Color(lit_tint[0], lit_tint[1], lit_tint[2], 1)
                if cols > 1 or rows > 1:
                    total = cols * rows
                    frame = int(float(obj.props.get("Frame") or 0)) % total
                    fx, fy = frame % cols, frame // cols
                    u0, u1 = fx / float(cols), (fx + 1) / float(cols)
                    v1, v0 = 1.0 - fy / float(rows), 1.0 - (fy + 1) / float(rows)
                    Rectangle(pos=(sx, sy), size=(w, h), texture=tex,
                             tex_coords=(u0, v0, u1, v0, u1, v1, u0, v1))
                elif truthy(obj.props.get("KeepAspect")) and tex.width and tex.height:
                    fit = min(w / float(tex.width), h / float(tex.height))
                    iw, ih = tex.width * fit, tex.height * fit
                    ix = sx + (w - iw) / 2.0
                    iy = sy + (h - ih) / 2.0
                    Rectangle(pos=(ix, iy), size=(iw, ih), texture=tex)
                else:
                    Rectangle(pos=(sx, sy), size=(w, h), texture=tex)

        if obj.cls == "slider":
            val = float(obj.props.get("Value") or 0)
            vmin = float(obj.props.get("Min") or 0)
            vmax = float(obj.props.get("Max") or 100)
            frac = 0.0 if vmax == vmin else max(0.0, min(1.0, (val - vmin) / (vmax - vmin)))
            Color(1, 1, 1, 0.85)
            Rectangle(pos=(sx, sy + h / 2 - 3), size=(w * frac, 6))

        if obj.cls == "toggle":
            on = bool(obj.props.get("Checked"))
            Color(0.2, 0.85, 0.45, 1) if on else Color(0.4, 0.4, 0.45, 1)
            RoundedRectangle(pos=(sx, sy), size=(w, h), radius=[h / 2])
            Color(1, 1, 1, 1)
            RoundedRectangle(pos=(sx + (w - h if on else 0), sy), size=(h, h), radius=[h / 2])

        # ---- Sprite interno (icone dentro de Button/Frame/etc, com Padding) ----
        pl, pr, pt, pb = obj.padding()
        sprite_src = str(obj.props.get("SpriteSource") or "")
        if sprite_src and obj.cls != "image":
            stex = self._texture(sprite_src, filter_mode=obj.props.get("Filter"))
            if stex is not None:
                inner_w = max(w - pl - pr, 1.0)
                inner_h = max(h - pt - pb, 1.0)
                sscale = float(obj.props.get("SpriteScale") or 1.0)
                keep = truthy(obj.props.get("SpriteKeepAspect", True))
                if keep and stex.width and stex.height:
                    fit = min(inner_w / float(stex.width), inner_h / float(stex.height)) * sscale
                    iw, ih = stex.width * fit, stex.height * fit
                else:
                    iw, ih = inner_w * sscale, inner_h * sscale
                anchor = str(obj.props.get("SpriteAnchor") or "center").lower()
                ix0, iy0 = sx + pl, sy + pb
                if anchor == "left":
                    ix = ix0
                elif anchor == "right":
                    ix = ix0 + inner_w - iw
                else:
                    ix = ix0 + (inner_w - iw) / 2.0
                if anchor == "top":
                    iy = iy0 + inner_h - ih
                elif anchor == "bottom":
                    iy = iy0
                else:
                    iy = iy0 + (inner_h - ih) / 2.0
                Color(lit_tint[0], lit_tint[1], lit_tint[2], 1)
                Rectangle(pos=(ix, iy), size=(iw, ih), texture=stex)

        text = tostring(obj.props.get("Text") or "")
        if text and obj.cls in ("button", "label", "text", "frame", "toggle"):
            fs = float(obj.props.get("FontSize") or 20)
            lbl = CoreLabel(text=text, font_size=fs, color=obj.text_color())
            lbl.refresh()
            tex = lbl.texture
            align = str(obj.props.get("Align") or "center").lower()
            if align == "left":
                tx = sx + pl
            elif align == "right":
                tx = sx + w - tex.width - pr
            else:
                tx = sx + (w - tex.width) / 2.0
            ty = sy + (h - tex.height) / 2.0
            Color(1, 1, 1, 1)
            Rectangle(pos=(tx, ty), size=tex.size, texture=tex)
        PopMatrix()

    def _gradient_texture(self, c1, c2, angle):
        """Gera (e cacheia) uma textura de gradiente linear na direcao pedida."""
        if not HAS_PIL:
            return None
        key = (tuple(round(v, 3) for v in c1), tuple(round(v, 3) for v in c2),
              round(float(angle) % 360.0, 1))
        if key in self._gradients:
            return self._gradients[key]
        size = 48
        img = PILImage.new("RGBA", (size, size))
        px = img.load()
        rad = math.radians(angle)
        dx, dy = math.cos(rad), math.sin(rad)
        vals = []
        for yy in range(size):
            for xx in range(size):
                nx = xx / float(size - 1) - 0.5
                ny = yy / float(size - 1) - 0.5
                vals.append(nx * dx + ny * dy)
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        i = 0
        for yy in range(size):
            for xx in range(size):
                t = (vals[i] - lo) / span
                i += 1
                r = c1[0] + (c2[0] - c1[0]) * t
                gg = c1[1] + (c2[1] - c1[1]) * t
                b = c1[2] + (c2[2] - c1[2]) * t
                a = c1[3] + (c2[3] - c1[3]) * t
                px[xx, yy] = (int(max(0.0, min(1.0, r)) * 255), int(max(0.0, min(1.0, gg)) * 255),
                             int(max(0.0, min(1.0, b)) * 255), int(max(0.0, min(1.0, a)) * 255))
        tex = Texture.create(size=(size, size), colorfmt="rgba")
        tex.blit_buffer(img.tobytes(), colorfmt="rgba", bufferfmt="ubyte")
        tex.flip_vertical()
        self._gradients[key] = tex
        return tex

    def _texture(self, source, filter_mode=None):
        if not source:
            return None
        if filter_mode:
            # passa pelo TextureManager: filtragem (nearest/bilinear/mipmap) + batching de cache
            return self._tex_manager.get(source, filter_mode=filter_mode)
        if source in self._textures:
            return self._textures[source]
        path = self.runtime.resolve(source)
        tex = None
        try:
            tex = CoreImage(path).texture
        except Exception as ex:
            self.runtime.log("[imagem] nao carregou %s: %s" % (source, ex))
        self._textures[source] = tex
        return tex

    def _camera_texture(self):
        """Textura ao vivo da camera (android.cameraStart() liga o feed);
        nunca fica em cache, ja que muda a cada frame."""
        cam = self.runtime.camera_widget
        if cam is None:
            return None
        try:
            return cam.texture
        except Exception:
            return None

    # ---------------------------------------------------------- entrada
    def _on_mouse_move(self, _window, pos):
        """Posicao continua do mouse (sem precisar segurar botao) - usada
        pra input.mousePosition() e pros eventos OnMouseEnter/OnMouseExit."""
        rt = self.runtime
        if not self.collide_point(*pos):
            self._set_hover(None)
            return
        tx = pos[0] - self.x
        ty = self.y + self.height - pos[1]
        rt.mouse_pos = (tx, ty)
        self._set_hover(self.hit_test(tx, ty))

    def _set_hover(self, obj):
        rt = self.runtime
        prev = rt.hover_obj
        if obj is prev:
            return
        rt.hover_obj = obj
        if prev is not None and prev.alive:
            cb = prev.props.get("OnMouseExit")
            if cb is not None:
                rt.call(cb, prev)
        if obj is not None:
            cb = obj.props.get("OnMouseEnter")
            if cb is not None:
                rt.call(cb, obj)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        btn = getattr(touch, "button", None) or "left"
        self.runtime.mouse_buttons.add(btn)
        tx = touch.x - self.x
        ty = self.y + self.height - touch.y
        self.runtime.dispatch_touch(tx, ty, "down", touch.uid)
        obj = self.hit_test(tx, ty)
        if obj is not None:
            if obj.cls == "toggle":
                obj.set_prop("Checked", not bool(obj.props.get("Checked")))
                cb = obj.props.get("OnChange")
                if cb is not None:
                    self.runtime.call(cb, obj, obj.props.get("Checked"))
            if obj.cls == "slider":
                lx, _ly = self._local_point(tx, ty, obj, self._active_camera2d())
                w = max(obj.size()[0], 1.0)
                vmin = float(obj.props.get("Min") or 0)
                vmax = float(obj.props.get("Max") or 100)
                frac = max(0.0, min(1.0, (lx - obj.pos()[0]) / w))
                obj.set_prop("Value", vmin + frac * (vmax - vmin))
                cb = obj.props.get("OnChange")
                if cb is not None:
                    self.runtime.call(cb, obj, obj.props.get("Value"))
            if truthy(obj.props.get("TransitionEnabled")):
                ps = float(obj.props.get("PressScale") or 0.95)
                spd = float(obj.props.get("TransitionSpeed") or 0.12)
                self.runtime.tween.to(obj, {"Scale": vec_table(ps, ps, 1.0)}, spd, "ease_out")
                self._pressed[touch.uid] = obj
            self.runtime.dispatch_click(obj)
        self.redraw()
        return True

    def on_touch_move(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        self.runtime.dispatch_touch(touch.x - self.x,
                                    self.y + self.height - touch.y, "move", touch.uid)
        return True

    def on_touch_up(self, touch):
        btn = getattr(touch, "button", None) or "left"
        self.runtime.mouse_buttons.discard(btn)
        pressed = self._pressed.pop(touch.uid, None)
        if pressed is not None and pressed.alive:
            spd = float(pressed.props.get("TransitionSpeed") or 0.12)
            self.runtime.tween.to(pressed, {"Scale": vec_table(1.0, 1.0, 1.0)}, spd, "ease_out")
        if not self.collide_point(*touch.pos):
            return False
        self.runtime.dispatch_touch(touch.x - self.x,
                                    self.y + self.height - touch.y, "up", touch.uid)
        return True

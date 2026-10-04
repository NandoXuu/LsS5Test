# -*- coding: utf-8 -*-
"""Palco Kivy: desenha UI 2D (com rotacao, gradiente, sombra, spritesheet)
e a cena 3D (matematica pura)."""

import math
import re
import time

from kivy.uix.widget import Widget
from kivy.uix.textinput import TextInput
from kivy.graphics import (Color, Rectangle, Line, PushMatrix, PopMatrix,
                           Rotate, Translate, Scale, Mesh, RoundedRectangle,
                           RenderContext, Fbo, Ellipse, BindTexture)
from .canvasdraw import CanvasDrawContext
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
from . import normalmap2d as nm2d
from . import spritesheet as sheet_mod
from . import pipeline as pipeline_mod
from . import texture as texture_mod
from . import tilemap as tilemap_mod
from . import glsl as glsl_mod
from . import richtext as richtext_mod
from . import inputs as inputs_mod
from .api import to_color, to_vec, vec_table, safe_float
from .lua import tostring, truthy, LuaTable


class Stage(Widget):
    def __init__(self, runtime, **kw):
        Widget.__init__(self, **kw)
        self.runtime = runtime
        self._textures = {}
        self._gradients = {}
        self._tex_manager = texture_mod.TextureManager(runtime.resolve, runtime.log)
        self._render_pipeline = pipeline_mod.RenderPipeline()
        # ---- materiais GLSL (shaders reais, via kivy.graphics.RenderContext) ----
        glsl_mod.SHADERS.resolver.set_path_resolver(runtime.resolve)
        self._glsl_ctx = {}       # nome do material -> RenderContext ja compilado
        self._glsl_broken = set()  # materiais que falharam ao compilar (nao tenta de novo)
        self._normalmap_ctx = {}
        self._normalmap_broken = set()
        self._normalmap_aspect_warned = set()
        self._pressed = {}   # touch.uid -> obj (pra desfazer o Transition no touch_up)
        self._layer_fbos = {}
        self._out = self.canvas
        self._rc_cache = {}
        self._rc_broken = set()
        self._fx_fbos = {}
        # ---- SUPER CUSTOMIZER: Mask / Shader por elemento ----
        self._obj_fbos = {}        # nome do objeto -> Fbo com seu conteudo normal
        self._mask_fbos = {}       # nome da mascara -> Fbo com a mascara renderizada
        self._mask_frame_cache = {}  # nome da mascara -> textura, valido so neste frame
        self._mask_only_rc = None  # RenderContext compartilhado p/ "so mascara, sem Shader"
        self._text_inputs = {}
        self._text_input_updating = set()
        self.bind(size=lambda *a: self.redraw(), pos=lambda *a: self.redraw())
        if Window is not None:
            try:
                Window.bind(mouse_pos=self._on_mouse_move)
            except Exception:
                pass
        # teclado + gamepad (on_key_*/on_joy_*) -> runtime.input
        self._input_bridge = inputs_mod.KivyBridge(Window, runtime, self._text_focused)
        self._input_bridge.attach()

    def _text_focused(self):
        return any(getattr(ti, "focus", False) for ti in self._text_inputs.values())

    def release_input(self):
        """Desliga o teclado/gamepad deste Stage (usado quando o Stage morre
        e outro nasce, ex.: Player)."""
        if self._input_bridge is not None:
            self._input_bridge.detach()

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
            if obj.cls not in ("button", "label", "text", "frame", "image", "toggle", "textbox", "textedit", "codeedit", "canvas"):
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
    # ------------------------------------------------------ campos de texto
    def _textbox_font_path(self, obj):
        font_prop = obj.props.get("Font")
        if not font_prop:
            return None
        try:
            return self.runtime.fonts.get(tostring(font_prop))
        except Exception:
            return None

    def _draw_textbox(self, obj):
        """Renderiza TextBox/TextEdit/CodeEdit pelo renderer do LuaStudio.
        O TextInput filho fica invisível e serve somente como ponte para
        teclado, IME, cursor lógico e seleção nativa."""
        x, y, _ = obj.pos()
        w, h, _ = obj.eff_size()
        w, h = max(float(w), 1.0), max(float(h), 1.0)
        sx, sy = self.to_stage(x, y)
        sy -= h
        radius = max(0.0, float(obj.props.get("Radius") or 0))
        pl, pr, pt, pb = obj.padding()
        alpha = max(0.0, min(1.0, float(obj.color()[3])))

        Color(1, 1, 1, alpha)
        fill = to_color(obj.props.get("Color"), (0.12, 0.14, 0.18, 1))
        Color(fill[0], fill[1], fill[2], fill[3] * alpha)
        RoundedRectangle(pos=(sx, sy), size=(w, h), radius=[radius])

        border = obj.props.get("BorderColor")
        if border is not None:
            bc = to_color(border, (1, 1, 1, 1))
            bw = max(0.0, float(obj.props.get("BorderSize") or 0))
            if bw > 0:
                Color(bc[0], bc[1], bc[2], bc[3] * alpha)
                Line(rounded_rectangle=(sx, sy, w, h, max(radius, 0.01)), width=bw)

        text = tostring(obj.props.get("Text") or "")
        focused = bool(obj.props.get("Focused"))
        if not text:
            placeholder = tostring(obj.props.get("Placeholder") or "")
            if placeholder and not focused:
                self._draw_input_text(obj, placeholder, x + pl, y + pt, w - pl - pr, h - pt - pb,
                                      placeholder=True)
        else:
            self._draw_input_text(obj, text, x + pl, y + pt, w - pl - pr, h - pt - pb)

        # Cursor visual do LuaStudio. O índice continua sendo mantido pelo
        # TextInput nativo; aqui desenhamos somente a representação.
        ti = self._text_inputs.get(obj)
        if focused and ti is not None and not bool(obj.props.get("ReadOnly")):
            try:
                cursor = int(getattr(ti, "cursor_index", len(text))[0]) if False else int(ti.cursor_index())
            except Exception:
                cursor = len(text)
            prefix = text[:max(0, min(cursor, len(text)))]
            fs = float(obj.props.get("FontSize") or 20)
            font_path = self._textbox_font_path(obj)
            kw = dict(text=prefix, font_size=fs, color=(0, 0, 0, 0))
            if font_path:
                kw["font_name"] = font_path
            lbl = CoreLabel(**kw)
            lbl.refresh()
            cx = sx + pl + lbl.texture.width
            cc = to_color(obj.props.get("CursorColor"), obj.text_color())
            Color(*cc)
            Line(points=[cx, sy + pb + 6, cx, sy + h - pt - 6], width=1.2)

    def _draw_input_text(self, obj, text, x, y, w, h, placeholder=False):
        fs = float(obj.props.get("FontSize") or 20)
        color = to_color(obj.props.get("PlaceholderColor"), (0.55, 0.58, 0.65, 1)) if placeholder else obj.text_color()
        font_path = self._textbox_font_path(obj)
        # Password continua sendo secreto visualmente, sem alterar Text.
        if bool(obj.props.get("Password")) and not placeholder:
            text = "•" * len(text)

        effect = tostring(obj.props.get("TextEffect") or "").lower()
        # Rainbow é um efeito de texto real: cada caractere vira um run
        # independente, sem criar Labels separados na API do desenvolvedor.
        if effect == "rainbow" and text:
            colors = ((1,0.15,0.15,1), (1,0.55,0.05,1), (1,0.9,0.05,1),
                      (0.2,1,0.25,1), (0.1,0.85,1,1), (0.2,0.35,1,1), (0.7,0.2,1,1))
            cx = x
            for i, ch in enumerate(text):
                kw = dict(text=ch, font_size=fs, color=colors[i % len(colors)])
                if font_path:
                    kw["font_name"] = font_path
                lbl = CoreLabel(**kw)
                lbl.refresh()
                tex = lbl.texture
                if cx + tex.width > x + w and obj.cls != "textbox":
                    x = x
                Color(1, 1, 1, 1)
                Rectangle(pos=(self.to_stage(cx, y)[0], self.to_stage(cx, y + max(0, h - tex.height))[1]),
                          size=tex.size, texture=tex)
                cx += tex.width
            return

        kw = dict(text=text, font_size=fs, color=color)
        if font_path:
            kw["font_name"] = font_path
        lbl = CoreLabel(**kw)
        lbl.refresh()
        tex = lbl.texture
        tx = x
        align = tostring(obj.props.get("Align") or "left").lower()
        if align == "center":
            tx = x + max(0.0, (w - tex.width) / 2.0)
        elif align == "right":
            tx = x + max(0.0, w - tex.width)
        # Kivy text texture is drawn with its bottom-left at the converted
        # top-left-ish coordinate. Keep the baseline visually centered.
        top_y = y + max(0.0, (h - tex.height) / 2.0)
        kx, ky_top = self.to_stage(tx, top_y)
        Color(1, 1, 1, 1)
        Rectangle(pos=(kx, ky_top - tex.height), size=tex.size, texture=tex)

    def _sync_text_inputs(self):
        """Mantem TextBox/TextEdit/CodeEdit como widgets Kivy reais.
        Assim o teclado do Android/PC, selecao, cursor e IME funcionam
        nativamente sem a engine precisar implementar um editor de texto."""
        live = set()
        for obj in self.runtime.scene.objects:
            if obj.cls not in ("textbox", "textedit", "codeedit") or not obj.visible():
                continue
            live.add(obj)
            ti = self._text_inputs.get(obj)
            if ti is None:
                multiline = obj.cls != "textbox"
                ti = TextInput(
                    text=tostring(obj.props.get("Text") or ""),
                    multiline=multiline,
                    readonly=bool(obj.props.get("ReadOnly")),
                    font_size=float(obj.props.get("FontSize") or 20),
                    foreground_color=(0, 0, 0, 0),
                    background_color=(0, 0, 0, 0),
                    cursor_color=(0, 0, 0, 0),
                    padding=[float(obj.props.get("Padding") or 8)] * 4,
                    hint_text="",
                    hint_text_color=(0, 0, 0, 0),
                    selection_color=(0, 0, 0, 0),
                    password=bool(obj.props.get("Password")) and obj.cls == "textbox",
                    write_tab=False,
                )
                if obj.cls == "codeedit":
                    # Nao use um nome de fonte como "RobotoMono" aqui: Kivy
                    # nao registra esse alias por padrao e isso derruba o
                    # TextInput durante _refresh_line_options. O TextInput
                    # usa a fonte padrao do Kivy quando font_name fica vazio.
                    # Se o projeto fornecer Font, ela sera aplicada abaixo.
                    ti.background_color = (0, 0, 0, 0)
                    ti.foreground_color = (0, 0, 0, 0)
                    ti.cursor_color = (0, 0, 0, 0)
                # Aplica fonte customizada somente quando o projeto realmente
                # fornece uma fonte resolvivel. Caso contrario, deixa Kivy
                # escolher a fonte padrao e nunca tenta abrir um alias inexistente.
                font_value = tostring(obj.props.get("Font") or "").strip()
                if font_value:
                    try:
                        fm = getattr(self.runtime, "font_manager", None)
                        resolved = fm.get(font_value) if fm is not None else None
                        if resolved and resolved.lower().endswith((".ttf", ".otf", ".ttc")):
                            ti.font_name = resolved
                    except Exception:
                        pass
                ti._luastudio_obj = obj
                ti.bind(text=lambda w, value, o=obj: self._text_changed(o, value))
                ti.bind(focus=lambda w, focused, o=obj: self._text_focus(o, focused))
                ti.bind(on_text_validate=lambda w, o=obj: self._text_submitted(o))
                self._text_inputs[obj] = ti
                self.add_widget(ti)
            else:
                # Propriedades Lua podem mudar em runtime.
                ti.multiline = obj.cls != "textbox"
                ti.readonly = bool(obj.props.get("ReadOnly"))
                ti.background_color = (0, 0, 0, 0)
                ti.foreground_color = (0, 0, 0, 0)
                ti.cursor_color = (0, 0, 0, 0)
                ti.font_size = float(obj.props.get("FontSize") or 20)
                ti.hint_text = ""
                ti.hint_text_color = (0, 0, 0, 0)
                ti.selection_color = (0, 0, 0, 0)
                ti.password = bool(obj.props.get("Password")) and obj.cls == "textbox"
                # Font e opcional. IMPORTANTE: nunca use font_name="" no Kivy.
                # Em algumas versoes isso vira literalmente ".ttf" durante
                # a resolucao da fonte e derruba o TextInput no proximo frame.
                # Quando nao ha fonte customizada, restauramos o alias que o
                # Kivy distribui por padrao.
                font_value = tostring(obj.props.get("Font") or "").strip()
                try:
                    fm = getattr(self.runtime, "font_manager", None)
                    resolved = fm.get(font_value) if (font_value and fm is not None) else None
                    if resolved and resolved.lower().endswith((".ttf", ".otf", ".ttc")):
                        ti.font_name = resolved
                    else:
                        ti.font_name = "Roboto"
                except Exception:
                    ti.font_name = "Roboto"
                desired = tostring(obj.props.get("Text") or "")
                if ti.text != desired:
                    self._text_input_updating.add(obj)
                    ti.text = desired
                    self._text_input_updating.discard(obj)

            x, y, _ = obj.pos()
            w, h, _ = obj.eff_size()
            # TextInput usa coordenadas Kivy (origem embaixo); Lua usa y em cima.
            sx, sy = self.to_stage(x, y)
            ti.pos = (sx, sy - h)
            ti.size = (max(1.0, w), max(1.0, h))
            ti.opacity = max(0.0, min(1.0, float(obj.color()[3])))
            ti.disabled = not obj.visible()

        for obj, ti in list(self._text_inputs.items()):
            if obj not in live:
                try:
                    self.remove_widget(ti)
                except Exception:
                    pass
                self._text_inputs.pop(obj, None)

    def _text_focus(self, obj, focused):
        obj.set_prop("Focused", bool(focused))
        cb = obj.props.get("OnFocus" if focused else "OnBlur")
        if cb is not None:
            self.runtime.call(cb, obj)

    def _text_changed(self, obj, value):
        if obj in self._text_input_updating:
            return
        max_len = int(float(obj.props.get("MaxLength") or 0))
        if max_len > 0 and len(value) > max_len:
            value = value[:max_len]
            ti = self._text_inputs.get(obj)
            if ti is not None and ti.text != value:
                self._text_input_updating.add(obj)
                ti.text = value
                self._text_input_updating.discard(obj)
        obj.set_prop("Text", value)
        cb = obj.props.get("OnChange")
        if cb is not None:
            self.runtime.call(cb, obj, value)

    def _text_submitted(self, obj):
        cb = obj.props.get("OnSubmit")
        if cb is not None:
            self.runtime.call(cb, obj, tostring(obj.props.get("Text") or ""))

    def redraw(self, *_a):
        rt = self.runtime
        self._sync_text_inputs()
        rt.stage_size = (float(self.width), float(self.height))
        self._apply_anchors()
        prof = getattr(rt, "profiler", None)
        if prof:
            prof.frame_start()
        self.canvas.clear()
        fx = getattr(rt, "postfx", None)
        plan = fx.plan() if fx is not None else []
        if plan and self.width >= 1 and self.height >= 1:
            self._redraw_postfx(plan, prof)
        else:
            self._out = self.canvas
            with self.canvas:
                self._draw_scene(prof)
        if prof:
            prof.frame_end()

    def _draw_scene(self, prof):
        rt = self.runtime
        Color(*rt.background)
        Rectangle(pos=self.pos, size=self.size)
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

    def _fx_fbo(self, idx):
        size = (max(1, int(self.width)), max(1, int(self.height)))
        fbo = self._fx_fbos.get(idx)
        if fbo is None or (int(fbo.size[0]), int(fbo.size[1])) != size:
            fbo = Fbo(size=size)
            self._fx_fbos[idx] = fbo
        return fbo

    def _redraw_postfx(self, plan, prof):
        scene = self._fx_fbo(0)
        scene.clear()
        self._out = scene
        with scene:
            PushMatrix()
            Translate(-self.x, -self.y, 0)
            self._draw_scene(prof)
            PopMatrix()
        self._out = self.canvas
        self.canvas.add(scene)
        texture = scene.texture
        sw, sh = float(self.width), float(self.height)
        for i, (name, overrides) in enumerate(plan):
            last = i == len(plan) - 1
            if last:
                target, pos = self.canvas, self.pos
            else:
                target, pos = self._fx_fbo(1 + i), (0, 0)
                target.clear()
            rc = self._compose_shader(("fx", i), name, texture, pos, (sw, sh),
                                      resolution=(sw, sh), overrides=overrides)
            if rc is None:
                if last:
                    with self.canvas:
                        Color(1, 1, 1, 1)
                        Rectangle(pos=self.pos, size=self.size, texture=texture)
                else:
                    with target:
                        Color(1, 1, 1, 1)
                        Rectangle(pos=(0, 0), size=(sw, sh), texture=texture)
            else:
                target.add(rc)
            if not last:
                self.canvas.add(target)
                texture = target.texture

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
        glsl_groups = {}   # nome do material GLSL -> lista de faces dele nesse frame
        for face in faces:
            if "glsl_material" in face:
                glsl_groups.setdefault(face["glsl_material"], []).append(face)
                continue
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
        # Faces com Material GLSL sao desenhadas DEPOIS de todas as faces
        # normais (limitacao conhecida: um objeto GLSL sempre desenha por
        # cima de objetos sem shader, mesmo que devesse ficar atras deles;
        # entre objetos GLSL do MESMO material, a profundidade e respeitada).
        for material_name, group in glsl_groups.items():
            self._draw_glsl_group(material_name, group, cam)

    def _draw_glsl_group(self, material_name, faces, cam):
        """Desenha as faces de um `Material` GLSL usando um RenderContext do
        Kivy (shader real, GPU, por pixel). Qualquer falha aqui (shader que
        nao compila, textura que nao carrega, etc.) cai pro fallback de cor
        solida em vez de derrubar o resto do frame 3D."""
        rt = self.runtime
        if material_name in self._glsl_broken:
            self._draw_glsl_fallback(faces)
            return
        try:
            mat = glsl_mod.MATERIALS.get(material_name)
            prog = glsl_mod.SHADERS.program_3d(mat.shader)
            if prog is None:
                raise RuntimeError("shader %r nao registrado (create.shader.%s)" % (mat.shader, mat.shader))
            key = (material_name, prog.signature)
            rc = self._glsl_ctx.get(key)
            if rc is None:
                rc = RenderContext(use_parent_projection=True, use_parent_modelview=True,
                                   use_parent_frag_modelview=True)
                rc.shader.vs = prog.vs
                rc.shader.fs = prog.fs
                if not getattr(rc.shader, "success", True):
                    raise RuntimeError("o GLSL do material nao compilou (detalhes no log do Kivy)")
                self._glsl_ctx[key] = rc

            albedo_tex = self._texture(mat.albedo) if mat.albedo else None
            normal_tex = self._texture(mat.normal_map) if mat.normal_map else None
            base_color = faces[0]["obj"].color() if faces else (1, 1, 1, 1)
            t_now = time.time() - rt.start_time
            lights = faces[0].get("lights", []) if faces else []
            lpos, lcol, lisdir, lcount = glsl_mod.build_light_uniforms(lights)

            rc.clear()
            values = {
                "uTime": float(t_now),
                "uViewPos": [float(v) for v in cam.position],
                "uAmbient": float(faces[0].get("ambient", 0.12)) if faces else 0.12,
                "uBaseColor": [float(v) for v in base_color],
                "uRoughness": float(mat.roughness),
                "uMetallic": float(mat.metallic),
                "uLightCount": float(lcount),
                "uHasAlbedoMap": 1.0 if albedo_tex is not None else 0.0,
                "uHasNormalMap": 1.0 if normal_tex is not None else 0.0,
                "uAlbedoMap": 1,
                "uNormalMap": 2,
            }
            for i in range(glsl_mod.MAX_LIGHTS):
                values["uLightPos%d" % i] = [float(x) for x in lpos[i]]
                values["uLightColor%d" % i] = [float(x) for x in lcol[i]]
                values["uLightIsDirectional%d" % i] = float(lisdir[i])
            entry = prog.entry
            extras = []
            index = 3
            for uname, source in entry.textures.items():
                tex = self._texture(source)
                if tex is not None and uname in prog.types:
                    values[uname] = index
                    extras.append((tex, index))
                    index += 1
            for alias in glsl_mod.AUTO_TIME:
                values.setdefault(alias, float(t_now))
            user = dict(entry.uniforms)
            user.update(entry.runtime)
            for k, raw in user.items():
                spec = prog.types.get(k)
                if spec is None or k in values:
                    continue
                coerced = glsl_mod.coerce_uniform(raw, spec[0], spec[1])
                if coerced is not None:
                    values[k] = coerced
            prog.apply(rc, dict((k, v) for k, v in values.items() if k in prog.types))
            with rc:
                Color(1, 1, 1, 1)
                if albedo_tex is not None:
                    BindTexture(texture=albedo_tex, index=1)
                if normal_tex is not None:
                    BindTexture(texture=normal_tex, index=2)
                for tex, tidx in extras:
                    BindTexture(texture=tex, index=tidx)
                for face in sorted(faces, key=lambda d: -d["depth"]):
                    pts = [(self.x + p[0], self.y + p[1]) for p in face["points"]]
                    n = len(pts)
                    vtx = []
                    for i in range(n):
                        px, py = pts[i]
                        u, v = face["uv"][i]
                        wx, wy, wz = face["world"][i]
                        nx, ny, nz = face["normal"]
                        tx, ty, tz = face["tangent"]
                        vtx.extend([px, py, u, v, wx, wy, wz, nx, ny, nz, tx, ty, tz])
                    indices = []
                    for i in range(1, n - 1):
                        indices.extend([0, i, i + 1])
                    Mesh(vertices=vtx, indices=indices, fmt=glsl_mod.VERTEX_FORMAT, mode="triangles")
            self._out.add(rc)
        except Exception as ex:  # noqa - shader/material com problema nao pode derrubar o frame
            self._glsl_broken.add(material_name)
            rt.log("[GLSL] material %r desativado (caiu pro visual solido): %s: %s"
                   % (material_name, type(ex).__name__, ex))
            self._draw_glsl_fallback(faces)

    def _draw_glsl_fallback(self, faces):
        """Usado quando um Material GLSL nao compila/carrega: desenha a face
        com a cor base do objeto (sem luz calculada), so pra nao sumir da tela."""
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
                direction=nm2d._num(obj.props.get("Direction"), 0.0),
                color=to_color(obj.props.get("Color"), (1, 1, 1, 1))[:3],
                intensity=nm2d._num(obj.props.get("Intensity"), 1.0),
                range=nm2d._num(obj.props.get("Range"), 220.0),
                spot_angle=nm2d._num(obj.props.get("SpotAngle"), 45.0),
                casts_shadow=truthy(obj.props.get("CastShadow")),
                layer=obj.props.get("Layer") or 0,
                enabled=truthy(obj.props.get("Enabled", True)),
                height=nm2d._num(obj.props.get("Height"), 100.0),
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
    def _apply_anchors(self):
        """Anchors relativos a TELA (SUPER CUSTOMIZER, item 10): quando
        `Anchor = {Left=fracao, Top=fracao}`, a Position do objeto e
        recalculada todo frame a partir do tamanho atual do Stage - o mesmo
        ponto normalizado do objeto (Left/Top) fica colado nesse ponto da
        tela, deslocado por `AnchorOffset` (pixels). Sem tabela em Anchor
        (o padrao e a string "topleft"), nada muda - Position continua
        sendo usada do jeito de sempre."""
        sw, sh = float(self.width), float(self.height)
        if sw <= 0 or sh <= 0:
            return
        for obj in self.runtime.scene.objects:
            anchor = obj.props.get("Anchor")
            if not isinstance(anchor, LuaTable):
                continue
            left = anchor.get("Left")
            top = anchor.get("Top")
            if left is None and top is None:
                continue
            left = safe_float(left, 0.0)
            top = safe_float(top, 0.0)
            ox, oy, _ = to_vec(obj.props.get("AnchorOffset"), (0.0, 0.0, 0.0))
            w, h, _ = obj.eff_size()
            _, _, z = to_vec(obj.props.get("Position"), (0.0, 0.0, 0.0))
            new_x = sw * left - w * left + ox
            new_y = sh * top - h * top + oy
            obj.props["Position"] = vec_table(new_x, new_y, z)

    def _draw_2d(self):
        self._mask_frame_cache = {}
        objs = [o for o in self.runtime.scene.objects
                if o.cls in ("button", "label", "text", "frame", "image", "slider",
                             "toggle", "textbox", "textedit", "codeedit", "canvas",
                             "particles", "tilemap", "obstacle",
                             "destructmesh", "meshfragment")
                and o.visible()]
        objs.sort(key=lambda o: o.zindex())
        self._cur_2d_objs = objs
        self._cur_lights2d = self._collect_lights2d()
        cam = self._active_camera2d()
        layers = {}
        for o in objs:
            idx = int(o.props.get("RenderLayer") or 0)
            layers.setdefault(idx, []).append(o)
        layer_state = self.runtime.layer_state
        for idx in sorted(layers.keys()):
            layer_objs = layers[idx]
            state = layer_state.get(idx)
            if state is None or (float(state.get("opacity", 1.0)) >= 0.999 and not state.get("shader")):
                self._draw_objs_with_camera(layer_objs, cam)
            else:
                self._draw_layer_fbo(idx, layer_objs, cam, state)

    def _draw_objs_with_camera(self, objs, cam):
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

    def _get_layer_fbo(self, idx):
        size = (max(1, int(self.width)), max(1, int(self.height)))
        fbo = self._layer_fbos.get(idx)
        if fbo is None or (int(fbo.size[0]), int(fbo.size[1])) != size:
            fbo = Fbo(size=size)
            self._layer_fbos[idx] = fbo
        return fbo

    def _draw_layer_fbo(self, idx, layer_objs, cam, state):
        fbo = self._get_layer_fbo(idx)
        fbo.clear()
        parent = self._out
        self._out = fbo
        try:
            with fbo:
                PushMatrix()
                Translate(-self.x, -self.y, 0)
                self._draw_objs_with_camera(layer_objs, cam)
                PopMatrix()
        finally:
            self._out = parent
        parent.add(fbo)
        opacity = max(0.0, min(1.0, float(state.get("opacity", 1.0))))
        shader_name = state.get("shader")
        rc = None
        if shader_name:
            rc = self._compose_shader(("layer", idx), shader_name, fbo.texture, self.pos,
                                      (self.width, self.height),
                                      resolution=(self.width, self.height),
                                      opacity=opacity, overrides=state.get("uniforms"))
        if rc is not None:
            parent.add(rc)
        else:
            Color(1, 1, 1, opacity)
            Rectangle(pos=self.pos, size=self.size, texture=fbo.texture)

    def _compose_shader(self, scope, name, texture, pos, size, tex_coords=None,
                        resolution=None, color=(1, 1, 1, 1), opacity=1.0,
                        overrides=None, mask_tex=None, rect_uv=(0.0, 0.0, 1.0, 1.0)):
        """Monta um RenderContext que desenha `texture` num retangulo passando
        pelo shader registrado `name`. Devolve None se o shader nao existe ou
        nao compilou (o chamador cai pro desenho normal)."""
        prog = glsl_mod.SHADERS.program_2d(name, mask_tex is not None)
        if prog is None:
            key = ("missing", name)
            if key not in self._rc_broken:
                self._rc_broken.add(key)
                self.runtime.log("[Shader] '%s' nao foi registrado (create.shader.%s)" % (name, name))
            return None
        key = (scope, prog.signature)
        if key in self._rc_broken:
            return None
        rc = self._rc_cache.get(key)
        if rc is None:
            try:
                rc = RenderContext(use_parent_projection=True, use_parent_modelview=True)
                rc.shader.vs = prog.vs
                rc.shader.fs = prog.fs
                if not getattr(rc.shader, "success", True):
                    raise RuntimeError("o GLSL nao compilou (detalhes no log do Kivy)")
            except Exception as ex:  # noqa
                self._rc_broken.add(key)
                self.runtime.log("[Shader] '%s' desativado: %s: %s" % (name, type(ex).__name__, ex))
                return None
            self._rc_cache[key] = rc
        res = resolution or size
        values = prog.values(float(time.time() - self.runtime.start_time),
                             (float(res[0]), float(res[1])), color, rect_uv, overrides)
        if mask_tex is not None and "uMask" in prog.types:
            values["uMask"] = 1
        extras = []
        entry = prog.entry
        index = 2
        for uname, source in entry.textures.items():
            if uname not in prog.types:
                continue
            tex = self._texture(source)
            if tex is None:
                continue
            if entry.wrap:
                try:
                    tex.wrap = "repeat"
                except Exception:  # noqa
                    pass
            values[uname] = index
            extras.append((tex, index))
            index += 1
        if entry.wrap:
            try:
                texture.wrap = "repeat"
            except Exception:  # noqa
                pass
        rc.clear()
        prog.apply(rc, values)
        with rc:
            Color(1, 1, 1, opacity)
            if mask_tex is not None:
                BindTexture(texture=mask_tex, index=1)
            for tex, tidx in extras:
                BindTexture(texture=tex, index=tidx)
            if tex_coords is None:
                Rectangle(pos=pos, size=size, texture=texture)
            else:
                Rectangle(pos=pos, size=size, texture=texture, tex_coords=tex_coords)
        return rc

    def _draw_one(self, obj):
        """Desenha um objeto isolado: se ele tiver uma propriedade invalida
        (cor malformada, textura quebrada etc.) e o desenho falhar, so
        ESSE objeto some do frame - o resto da cena continua normal."""
        try:
            if obj.cls in ("textbox", "textedit", "codeedit"):
                self._draw_textbox(obj)
            elif obj.cls == "particles":
                self._draw_particles(obj)
            elif obj.cls == "tilemap":
                self._draw_tilemap(obj)
            elif obj.cls in ("destructmesh", "meshfragment"):
                self._draw_mesh2d(obj)
            elif obj.cls == "canvas":
                self._draw_with_effects(obj, lambda: self._draw_canvas(obj))
            else:
                self._draw_with_effects(obj, lambda: self._draw_widget(obj))
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

    def _draw_canvas(self, obj):
        """`canvas`: nao tem visual proprio - so um retangulo de fundo
        opcional (Color/BorderColor/Radius, iguais a um frame) mais o que
        o script desenhar sozinho em `OnDraw` (immediate-mode, ver
        canvasdraw.CanvasDrawContext). E a base pra Custom UI/Custom
        Widgets: HUDs, medidores, miras, barras nao-retangulares etc."""
        x, y, _ = obj.pos()
        w, h, _ = obj.eff_size()
        w = max(w, 1.0)
        h = max(h, 1.0)
        rot = obj.rot()
        sx, sy = self.to_stage(x, y)
        sy -= h
        cx, cy = sx + w / 2.0, sy + h / 2.0

        PushMatrix()
        if rot:
            Translate(cx, cy, 0)
            Rotate(angle=-rot, axis=(0, 0, 1))
            Translate(-cx, -cy, 0)

        # ---- fundo opcional, igual a um frame (Color/Radius/BorderColor) ----
        radius = float(obj.props.get("Radius") or 0)
        col = obj.color()
        if col[3] > 0:
            Color(*col)
            if radius > 0:
                RoundedRectangle(pos=(sx, sy), size=(w, h), radius=[radius])
            else:
                Rectangle(pos=(sx, sy), size=(w, h))
        border = obj.props.get("BorderColor")
        if border is not None:
            bsize = float(obj.props.get("BorderSize") or 1.4)
            Color(*to_color(border))
            Line(rounded_rectangle=(sx, sy, w, h, max(radius, 0.01)), width=bsize)

        # ---- desenho imediato do script (OnDraw) ----
        cb = obj.props.get("OnDraw")
        if cb is not None:
            ctx = CanvasDrawContext(self, x, y)
            self.runtime.call(cb, obj, ctx)

        PopMatrix()

    def _draw_mesh2d(self, obj):
        if obj.cls == "destructmesh" and not getattr(obj, "_mesh_tris", None):
            from . import destruction as destruction_mod
            destruction_mod.build_instance_mesh(obj, self.runtime.resolve)
        render_tris = getattr(obj, "_render_tris", None)
        if not render_tris:
            return
        x, y, _ = obj.pos()
        w, h, _ = obj.eff_size()
        w = max(w, 1.0)
        h = max(h, 1.0)
        sx, sy = self.to_stage(x, y)
        sy -= h
        rot = obj.rot()
        cx, cy = sx + w / 2.0, sy + h / 2.0
        src = str(obj.props.get("Source") or "")
        tex = self._texture(src, filter_mode=obj.props.get("Filter") or "linear")
        if tex is None:
            return
        PushMatrix()
        try:
            if rot:
                Translate(cx, cy, 0)
                Rotate(angle=-rot, axis=(0, 0, 1))
                Translate(-cx, -cy, 0)
            Color(1, 1, 1, 1)
            for tri in render_tris:
                flat = []
                for bu, bv, u, v in tri:
                    flat.extend([sx + bu * w, sy + (h - bv * h), u, v])
                Mesh(vertices=flat, indices=[0, 1, 2], texture=tex, mode="triangles")
        finally:
            PopMatrix()

    # ---- tilemap (create.tilemap.Nome = {File="assets/mapa.lsm"}) ----
    def _tilemap_visible_range(self, obj, map_data, cam):
        """Calcula so o retangulo de colunas/linhas VISIVEL na tela agora
        (culling) - essencial pra desempenho num mapa grande (ex: 100x100
        = 10 mil tiles): sem isso, cada frame teria que iterar/desenhar a
        grade INTEIRA mesmo quando so um pedacinho aparece na tela."""
        ox, oy, _ = obj.pos()
        try:
            sxv, syv, _ = to_vec(obj.props.get("Scale"), (1, 1, 1))
        except Exception:
            sxv, syv = 1.0, 1.0
        tw = max(0.01, map_data["tile_w"] * (sxv or 1.0))
        th = max(0.01, map_data["tile_h"] * (syv or 1.0))
        cols, rows = map_data["cols"], map_data["rows"]
        corners = [(self.x, self.y), (self.x + self.width, self.y),
                  (self.x, self.y + self.height), (self.x + self.width, self.y + self.height)]
        if cam is not None:
            world_pts = [self._cam2d_screen_to_world(cx, cy, cam) for cx, cy in corners]
        else:
            world_pts = [(cx - self.x, self.y + self.height - cy) for cx, cy in corners]
        xs = [p[0] - ox for p in world_pts]
        ys = [p[1] - oy for p in world_pts]
        col_min = max(0, int(min(xs) // tw) - 1)
        col_max = min(cols - 1, int(max(xs) // tw) + 1)
        row_min = max(0, int(min(ys) // th) - 1)
        row_max = min(rows - 1, int(max(ys) // th) + 1)
        return col_min, col_max, row_min, row_max, tw, th

    def _draw_tilemap(self, obj):
        path = self.runtime.resolve(str(obj.props.get("File") or ""))
        map_data = self.runtime.get_tilemap_data(path)
        if map_data is None:
            return
        abs_tex_path = tilemap_mod.tileset_path_for(path, map_data)
        tex = self._texture(abs_tex_path) if abs_tex_path else None
        if tex is None:
            return
        cam = self._active_camera2d() if not truthy(obj.props.get("IgnoreCamera")) else None
        col_min, col_max, row_min, row_max, tw, th = self._tilemap_visible_range(obj, map_data, cam)
        if col_min > col_max or row_min > row_max:
            return
        ox, oy, _ = obj.pos()
        cols = map_data["cols"]
        tile_w, tile_h = map_data["tile_w"], map_data["tile_h"]
        Color(1, 1, 1, 1)
        for layer in map_data.get("layers") or []:
            data = layer["data"]
            for row in range(row_min, row_max + 1):
                base_idx = row * cols
                for col in range(col_min, col_max + 1):
                    tid = data[base_idx + col]
                    if not tid:
                        continue
                    lx = ox + col * tw
                    ly = oy + row * th
                    sx, sy = self.to_stage(lx, ly + th)
                    u0, v0, u1, v1 = tilemap_mod.tile_uv(tid, tex.width, tex.height, tile_w, tile_h)
                    Rectangle(pos=(sx, sy), size=(tw, th), texture=tex,
                             tex_coords=(u0, v0, u1, v0, u1, v1, u0, v1))

    def _normalmap_rc(self, key):
        rc = self._normalmap_ctx.get(key)
        if rc is not None:
            return rc
        rc = RenderContext(use_parent_projection=True, use_parent_modelview=True,
                           use_parent_frag_modelview=True)
        rc.shader.vs = nm2d.VERTEX_SHADER
        rc.shader.fs = nm2d.fragment_source()
        if not getattr(rc.shader, "success", True):
            raise RuntimeError("shader do normal map nao compilou")
        self._normalmap_ctx[key] = rc
        return rc

    def _draw_image_normalmap(self, obj, tex, normal_tex, rect, rot, flip_x, flip_y, uvs=None, shadow=1.0, alpha=1.0):
        """Renderiza create.image + NormalMap + luzes 2D (difuso, especular
        half-vector, metallic, emission, AO) por pixel na GPU."""
        if tex is None or normal_tex is None:
            return False
        key = obj.name
        if key in self._normalmap_broken:
            return False
        try:
            rc = self._normalmap_rc(key)
            rx, ry, rw, rh = rect
            center = (rx + rw / 2.0, ry + rh / 2.0)
            max_lights = min(nm2d.MAX_NM_LIGHTS,
                             int(getattr(self.runtime, "max_lights2d", 8) or 8))
            ox, oy, _ = obj.pos()
            filtered = light2d_mod.filter_lights2d(
                self._cur_lights2d, (ox + rw / 2.0, oy + rh / 2.0), max_lights=max_lights)

            rc.clear()
            rc["u_rect_pos"] = [float(rx), float(ry)]
            rc["normal_map"] = 1
            rc["u_light_count"] = float(len(filtered))
            rc["u_shadow"] = float(shadow)
            for name, value in nm2d.material_uniforms(obj.props).items():
                rc[name] = float(value)
            has_lights = len(filtered) > 0
            rc["ambient"] = float(nm2d.resolve_ambient(
                obj.props, getattr(self.runtime, "ambient2d_explicit", False),
                getattr(self.runtime, "ambient2d_intensity", 1.0), has_lights))
            acol = getattr(self.runtime, "ambient2d_color", (1.0, 1.0, 1.0))
            rc["ambient_color"] = [float(acol[0]), float(acol[1]), float(acol[2])]
            for i, light in enumerate(filtered):
                u = nm2d.light_to_uniforms(light, rect, center, self.to_stage, rot, flip_x, flip_y)
                rc["u_l%d_pos" % i] = u["pos"]
                rc["u_l%d_color" % i] = u["color"]
                rc["u_l%d_params" % i] = u["params"]
                rc["u_l%d_dir" % i] = u["dir"]
            with rc:
                Color(1, 1, 1, float(alpha))
                BindTexture(texture=normal_tex, index=1)
                if uvs is None:
                    Rectangle(pos=(rx, ry), size=(rw, rh), texture=tex)
                else:
                    Rectangle(pos=(rx, ry), size=(rw, rh), texture=tex, tex_coords=uvs)
            self._out.add(rc)
            return True
        except Exception as ex:
            self._normalmap_broken.add(key)
            self.runtime.log("[NormalMap2D] '%s' desativado: %s: %s" % (obj.name, type(ex).__name__, ex))
            return False

    # ------------------------------------------------ Mask / Shader (SUPER CUSTOMIZER)
    def _render_mask(self, mobj):
        """Renderiza um `create.mask.X` (Shape/Position/Size/Text/Source)
        num Fbo do tamanho do Stage inteiro - o ALPHA desse Fbo e a
        mascara. Usar o Stage inteiro (em vez de um recorte justo) e o que
        permite comparar a mascara e o conteudo pixel-a-pixel depois, sem
        ter que alinhar dois retangulos diferentes na mao."""
        size = (max(1, int(self.width)), max(1, int(self.height)))
        fbo = self._mask_fbos.get(mobj.name)
        if fbo is None or (int(fbo.size[0]), int(fbo.size[1])) != size:
            fbo = Fbo(size=size)
            self._mask_fbos[mobj.name] = fbo
        fbo.clear()
        shape = str(mobj.props.get("Shape") or "rectangle").lower()
        x, y, _ = mobj.pos()
        w, h, _ = mobj.eff_size()
        w = max(w, 1.0)
        h = max(h, 1.0)
        sx, sy = self.to_stage(x, y)
        sy -= h
        radius = float(mobj.props.get("Radius") or 0)
        with fbo:
            PushMatrix()
            Translate(-self.x, -self.y, 0)
            if shape in ("sprite", "texture", "alpha"):
                src = str(mobj.props.get("Source") or "")
                tex = self._texture(src)
                if tex is not None:
                    Color(1, 1, 1, 1)
                    Rectangle(pos=(sx, sy), size=(w, h), texture=tex)
            elif shape == "text":
                txt = tostring(mobj.props.get("Text") or "")
                if txt:
                    fs = float(mobj.props.get("FontSize") or 48)
                    font_prop = mobj.props.get("Font")
                    font_path = self.runtime.fonts.get(tostring(font_prop)) if font_prop else None
                    if font_path:
                        lbl = CoreLabel(text=txt, font_size=fs, color=(1, 1, 1, 1), font_name=font_path)
                    else:
                        lbl = CoreLabel(text=txt, font_size=fs, color=(1, 1, 1, 1))
                    lbl.refresh()
                    ltex = lbl.texture
                    tx = sx + (w - ltex.width) / 2.0
                    ty = sy + (h - ltex.height) / 2.0
                    Color(1, 1, 1, 1)
                    Rectangle(pos=(tx, ty), size=ltex.size, texture=ltex)
            elif shape in ("circle", "ellipse"):
                Color(1, 1, 1, 1)
                Ellipse(pos=(sx, sy), size=(w, h))
            elif shape == "roundedrectangle":
                Color(1, 1, 1, 1)
                RoundedRectangle(pos=(sx, sy), size=(w, h), radius=[radius or min(w, h) * 0.15])
            else:
                # rectangle e fallback pra formas ainda nao implementadas
                # (polygon/gradient/custom) - area cheia, sem recorte.
                Color(1, 1, 1, 1)
                Rectangle(pos=(sx, sy), size=(w, h))
            PopMatrix()
        self._out.add(fbo)
        return fbo.texture

    def _mask_alpha_texture(self, mask_name):
        if mask_name in self._mask_frame_cache:
            return self._mask_frame_cache[mask_name]
        tex = None
        mobj = self.runtime.scene.by_name.get(mask_name)
        if mobj is not None and mobj.cls == "mask" and mobj.visible():
            try:
                tex = self._render_mask(mobj)
            except Exception as ex:  # noqa
                self.runtime.log("[Mask] '%s' desativada: %s: %s"
                                 % (mask_name, type(ex).__name__, ex))
        self._mask_frame_cache[mask_name] = tex
        return tex

    def _content_fbo(self, obj):
        size = (max(1, int(self.width)), max(1, int(self.height)))
        fbo = self._obj_fbos.get(obj.name)
        if fbo is None or (int(fbo.size[0]), int(fbo.size[1])) != size:
            fbo = Fbo(size=size)
            self._obj_fbos[obj.name] = fbo
        return fbo

    def _draw_with_effects(self, obj, content_fn):
        """Ponto de entrada de Mask/Shader por elemento: se o objeto nao usa
        nenhum dos dois, desenha normal (zero custo extra). Senao, desenha o
        conteudo normal (`content_fn`) num Fbo do tamanho do Stage e depois
        recompoe so o retangulo do objeto na tela, passando por um
        RenderContext que aplica a mascara e/ou o shader customizado."""
        mask_name = str(obj.props.get("Mask") or "").strip()
        shader_name = str(obj.props.get("Shader") or "").strip()
        if not mask_name and not shader_name:
            content_fn()
            return
        sw, sh = float(self.width), float(self.height)
        if sw <= 0 or sh <= 0:
            content_fn()
            return
        x, y, _ = obj.pos()
        w, h, _ = obj.eff_size()
        w = max(w, 1.0)
        h = max(h, 1.0)
        sx, sy = self.to_stage(x, y)
        sy -= h
        fbo = self._content_fbo(obj)
        fbo.clear()
        with fbo:
            PushMatrix()
            Translate(-self.x, -self.y, 0)
            content_fn()
            PopMatrix()
        self._out.add(fbo)
        u0, v0 = sx / sw, sy / sh
        u1, v1 = (sx + w) / sw, (sy + h) / sh
        tex_coords = (u0, v0, u1, v0, u1, v1, u0, v1)
        mask_tex = self._mask_alpha_texture(mask_name) if mask_name else None
        if shader_name:
            params = obj.props.get("ShaderParams")
            overrides = glsl_mod._table_to_dict(params) if params is not None else None
            rc = self._compose_shader(("obj", obj.name), shader_name, fbo.texture, (sx, sy), (w, h),
                                      tex_coords=tex_coords, resolution=(w, h), color=obj.color(),
                                      overrides=overrides, mask_tex=mask_tex,
                                      rect_uv=(u0, v0, u1 - u0, v1 - v0))
            if rc is not None:
                self._out.add(rc)
                return
        if mask_tex is not None:
            if self._mask_only_rc is None:
                rc = RenderContext(use_parent_projection=True, use_parent_modelview=True)
                rc.shader.vs = glsl_mod.DEFAULT_2D_VERTEX
                rc.shader.fs = glsl_mod.MASK_ONLY_FRAGMENT
                self._mask_only_rc = rc
            rc = self._mask_only_rc
            rc.clear()
            rc["uMask"] = 1
            with rc:
                Color(1, 1, 1, 1)
                BindTexture(texture=mask_tex, index=1)
                Rectangle(pos=(sx, sy), size=(w, h), texture=fbo.texture, tex_coords=tex_coords)
            self._out.add(rc)
            return
        Color(1, 1, 1, 1)
        Rectangle(pos=(sx, sy), size=(w, h), texture=fbo.texture, tex_coords=tex_coords)

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
        # ---- Theme/Style (SUPER CUSTOMIZER item 8): estado de interacao
        # atual do objeto, usado por `obj.themed_value/themed_color` pra
        # escolher Style.Hover/Pressed/Disabled/Focused em vez de Normal ----
        if truthy(obj.props.get("Disabled")):
            ui_state = "Disabled"
        elif obj in self._pressed.values():
            ui_state = "Pressed"
        elif self.runtime.hover_obj is obj:
            ui_state = "Hover"
        elif truthy(obj.props.get("Focused")):
            ui_state = "Focused"
        else:
            ui_state = "Normal"
        radius = float(obj.themed_value("Radius", ui_state) or 0)
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
        shadow_c = obj.themed_value("ShadowColor", ui_state)
        if shadow_c is not None:
            sc = to_color(shadow_c, (0, 0, 0, 0.5))
            blur = max(0.0, float(obj.themed_value("ShadowBlur", ui_state) or 0))
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
        nm_shadow = 1.0
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
            nm_shadow = shadow

        # ---- preenchimento: gradiente (se configurado) ou cor solida ----
        col = obj.themed_color("Color", ui_state, default=(0.2, 0.4, 0.9, 1))
        style_opacity = obj.themed_opacity(ui_state)
        if style_opacity < 1.0:
            col = (col[0], col[1], col[2], col[3] * style_opacity)
        if truthy(obj.props.get("Lit")) and self._cur_lights2d:
            col = (col[0] * lit_tint[0], col[1] * lit_tint[1], col[2] * lit_tint[2],
                  col[3] if len(col) > 3 else 1.0)
        # create.image com Source: o Color vira TINT/OPACIDADE da textura (nao um
        # retangulo solido atras dela - era isso que formava o quadrado branco).
        img_tinted = (obj.cls == "image" and bool(str(obj.props.get("Source") or "").strip()))
        img_tint = (lit_tint[0], lit_tint[1], lit_tint[2], style_opacity)
        if img_tinted and ("Color" in obj._explicit_keys
                           or obj.themed_value("Color", ui_state) != obj.props.get("Color")):
            img_tint = (col[0], col[1], col[2], col[3])   # col ja inclui luz 2D (Lit) e Style.Opacity
        # Color nunca setado => imagem normal (branco opaco); o default
        # "#00000000" so existe pra nao pintar fundo em outras classes.
        g1 = obj.themed_value("GradientColor1", ui_state)
        g2 = obj.themed_value("GradientColor2", ui_state)
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
        elif col[3] > 0 and not img_tinted:
            Color(*col)
            if radius > 0:
                RoundedRectangle(pos=(sx, sy), size=(w, h), radius=[radius])
            else:
                Rectangle(pos=(sx, sy), size=(w, h))

        # ---- borda (Stroke) ----
        border = obj.themed_value("BorderColor", ui_state)
        if border is not None:
            bsize = float(obj.themed_value("BorderSize", ui_state) or 1.4)
            Color(*to_color(border))
            Line(rounded_rectangle=(sx, sy, w, h, max(radius, 0.01)), width=bsize)

        # ---- imagem principal (Source) - com suporte a spritesheet ----
        if obj.cls == "image":
            src = str(obj.props.get("Source") or "")
            filter_mode = obj.props.get("Filter") or "linear"
            if src.strip().lower() == "camera":
                tex = self._camera_texture()
            else:
                tex = self._texture(src, filter_mode=filter_mode)
            normal_src = str(obj.props.get("NormalMap") or "")
            normal_tex = self._texture(normal_src, filter_mode=filter_mode) if normal_src else None
            if tex is not None:
                # UVs do frame atual: calculados UMA vez e reutilizados pelo
                # Source e pelo NormalMap (sincronia garantida).
                frame_uvs = sheet_mod.frame_uvs_from_props(obj.props)
                if normal_tex is not None:
                    # checagem de proporcao: so uma vez por (objeto, Source, NormalMap)
                    chk = (obj.name, src, normal_src)
                    if chk not in self._normalmap_aspect_warned:
                        self._normalmap_aspect_warned.add(chk)
                        if sheet_mod.aspect_mismatch((tex.width, tex.height),
                                                     (normal_tex.width, normal_tex.height)):
                            self.runtime.log(
                                "[NormalMap2D] '%s': NormalMap (%dx%d) e Source (%dx%d) tem "
                                "proporcoes diferentes; os frames do Normal Map nao vao alinhar "
                                "com os do Source." % (obj.name, normal_tex.width,
                                                       normal_tex.height, tex.width, tex.height))
                normal_drawn = False
                if normal_tex is not None and truthy(obj.props.get("Lit")):
                    if frame_uvs is None and truthy(obj.props.get("KeepAspect")) and tex.width and tex.height:
                        fit = min(w / float(tex.width), h / float(tex.height))
                        iw, ih = tex.width * fit, tex.height * fit
                        nm_rect = (sx + (w - iw) / 2.0, sy + (h - ih) / 2.0, iw, ih)
                    else:
                        nm_rect = (sx, sy, w, h)
                    normal_drawn = self._draw_image_normalmap(
                        obj, tex, normal_tex, nm_rect, rot, flip_x, flip_y, frame_uvs,
                        shadow=nm_shadow, alpha=img_tint[3])
                if not normal_drawn:
                    Color(*img_tint)
                    if frame_uvs is not None:
                        Rectangle(pos=(sx, sy), size=(w, h), texture=tex, tex_coords=frame_uvs)
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
            if truthy(obj.props.get("RichText")):
                self._draw_richtext(obj, text, x, y, w, h, pl, pr, pt, pb)
            else:
                fs = float(obj.themed_value("FontSize", ui_state) or 20)
                font_prop = obj.themed_value("Font", ui_state)
                font_path = self.runtime.fonts.get(tostring(font_prop)) if font_prop else None
                tcolor = obj.themed_color("TextColor", ui_state, default=(1, 1, 1, 1))
                if font_path:
                    lbl = CoreLabel(text=text, font_size=fs, color=tcolor, font_name=font_path)
                else:
                    lbl = CoreLabel(text=text, font_size=fs, color=tcolor)
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
        elif obj.cls in ("button", "label", "text", "frame", "toggle"):
            obj._richtext_links = None
        PopMatrix()

    def _draw_richtext(self, obj, markup, x, y, w, h, pl, pr, pt, pb):
        base_size = float(obj.props.get("FontSize") or 20)
        base_color = obj.text_color()
        font_prop = obj.props.get("Font")
        font_path = self.runtime.fonts.get(tostring(font_prop)) if font_prop else None
        runs = richtext_mod.parse(markup)
        inner_w = max(w - pl - pr, 1.0)

        tokens = []
        for run in runs:
            if run.image:
                tokens.append(("img", run))
                continue
            for i, part in enumerate(run.text.split("\n")):
                if i > 0:
                    tokens.append(("break", None))
                for word in re.findall(r"\S+\s*", part):
                    tokens.append(("word", (run, word)))

        cache = {}

        def _measure(run, word):
            size = run.size if run.size is not None else base_size
            color = run.color if run.color is not None else base_color
            key = (word, run.bold, run.italic, size, font_path)
            tex = cache.get(key)
            if tex is None:
                kw = dict(text=word, font_size=size, color=color, bold=run.bold, italic=run.italic)
                if font_path:
                    kw["font_name"] = font_path
                lbl = CoreLabel(**kw)
                lbl.refresh()
                tex = lbl.texture
                cache[key] = tex
            return tex, color

        lines = []
        cur = []
        cur_w = 0.0
        for kind, data in tokens:
            if kind == "break":
                lines.append(cur)
                cur = []
                cur_w = 0.0
                continue
            if kind == "img":
                run = data
                tex = self._texture(run.image) if run.image else None
                iw = float(tex.width) if tex is not None else base_size
                ih = float(tex.height) if tex is not None else base_size
                scale = min(1.0, (base_size * 1.4) / ih) if ih else 1.0
                iw *= scale
                ih *= scale
                if cur and cur_w + iw > inner_w:
                    lines.append(cur)
                    cur = []
                    cur_w = 0.0
                cur.append(("img", tex, iw, ih))
                cur_w += iw
                continue
            run, word = data
            tex, color = _measure(run, word)
            tw_ = float(tex.width)
            if cur and cur_w + tw_ > inner_w:
                lines.append(cur)
                cur = []
                cur_w = 0.0
            cur.append(("word", run, tex, color))
            cur_w += tw_
        lines.append(cur)

        line_heights = []
        for ln in lines:
            lh = base_size * 1.25
            for item in ln:
                if item[0] == "word":
                    lh = max(lh, item[2].height * 1.15)
                elif item[0] == "img":
                    lh = max(lh, item[3] * 1.05)
            line_heights.append(lh)

        align = str(obj.props.get("Align") or "left").lower()
        links = []
        cursor_y = y + pt
        for ln, lh in zip(lines, line_heights):
            line_w = sum((item[2].width if item[0] == "word" else item[2]) for item in ln)
            if align == "center":
                cursor_x = x + pl + max(0.0, (inner_w - line_w) / 2.0)
            elif align == "right":
                cursor_x = x + pl + max(0.0, inner_w - line_w)
            else:
                cursor_x = x + pl
            line_top = cursor_y
            for item in ln:
                if item[0] == "img":
                    _, tex, iw, ih = item
                    kx, ky_top = self.to_stage(cursor_x, line_top + (lh - ih) / 2.0)
                    ky = ky_top - ih
                    if tex is not None:
                        Color(1, 1, 1, 1)
                        Rectangle(pos=(kx, ky), size=(iw, ih), texture=tex)
                    cursor_x += iw
                else:
                    _, run, tex, color = item
                    kx, ky_top = self.to_stage(cursor_x, line_top + (lh - tex.height) / 2.0)
                    ky = ky_top - tex.height
                    Color(*color)
                    Rectangle(pos=(kx, ky), size=tex.size, texture=tex)
                    if run.underline:
                        Line(points=[kx, ky - 1, kx + tex.width, ky - 1], width=1.0)
                    if run.link:
                        links.append((cursor_x, line_top, float(tex.width), lh, run.link))
                    cursor_x += tex.width
            cursor_y += lh
        obj._richtext_links = links

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

        # Primeiro deixa os widgets Kivy filhos (principalmente TextInput)
        # receberem o toque. O TextInput precisa tratar o touch nativamente
        # para ganhar foco, cursor, selecao e abrir o teclado/IME do Android.
        # O Stage antigo interceptava o toque e nunca chamava Widget.on_touch_down,
        # entao os TextInput ficavam visiveis mas completamente sem input.
        if super().on_touch_down(touch):
            return True
        btn = getattr(touch, "button", None) or "left"
        self.runtime.mouse_buttons.add(btn)
        self.runtime.input.mouse_press(btn)
        tx = touch.x - self.x
        ty = self.y + self.height - touch.y
        self.runtime.dispatch_touch(tx, ty, "down", touch.uid)
        obj = self.hit_test(tx, ty)
        if obj is not None:
            if truthy(obj.props.get("RichText")):
                links = getattr(obj, "_richtext_links", None)
                if links:
                    qx, qy = self._local_point(tx, ty, obj, self._active_camera2d())
                    for lx, ly, lw, lh, url in links:
                        if lx <= qx <= lx + lw and ly <= qy <= ly + lh:
                            cb = obj.props.get("OnLinkClick")
                            if cb is not None:
                                self.runtime.call(cb, obj, url)
                            break
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
        # Preserve o comportamento nativo de selecao/cursor/scroll dos
        # TextInput enquanto o dedo/mouse estiver sobre ele.
        if super().on_touch_move(touch):
            return True
        self.runtime.dispatch_touch(touch.x - self.x,
                                    self.y + self.height - touch.y, "move", touch.uid)
        return True

    def on_touch_up(self, touch):
        # O TextInput precisa receber o touch_up para finalizar selecao e
        # manter o estado de foco corretamente.
        child_handled = super().on_touch_up(touch)
        btn = getattr(touch, "button", None) or "left"
        self.runtime.mouse_buttons.discard(btn)
        self.runtime.input.mouse_release(btn)
        pressed = self._pressed.pop(touch.uid, None)
        if pressed is not None and pressed.alive:
            spd = float(pressed.props.get("TransitionSpeed") or 0.12)
            self.runtime.tween.to(pressed, {"Scale": vec_table(1.0, 1.0, 1.0)}, spd, "ease_out")
        if not self.collide_point(*touch.pos):
            return False
        self.runtime.dispatch_touch(touch.x - self.x,
                                    self.y + self.height - touch.y, "up", touch.uid)
        return True or child_handled

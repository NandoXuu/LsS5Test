# -*- coding: utf-8 -*-
"""Editor de Tilemaps - app SEPARADO do LuaStudio (tem seu proprio ponto de
entrada: `tilemap_editor_main.py`, na raiz do projeto - abra ELE no Pydroid
3, nao o main.py do editor de codigo).

Cria ou edita um mapa de tiles: escolhe o tileset (PNG), o tamanho de cada
tile e o tamanho da grade, pinta com Pincel/Borracha/Balde/Retangulo num
viewport tipo "plano cartesiano" (com zoom e navegacao), e salva um pacote
pronto (mapa + imagem do tileset juntos na mesma pasta) em:

  - .lsm     - binario (RLE), recomendado: menor e mais rapido de ler.
  - .JsonTm  - JSON, bom pra debugar/editar na mao.

(Nao gera ".ts"/TypeScript porque essa engine e Lua+Python, sem runtime de
TypeScript - o .lsm binario cumpre o mesmo papel de "formato proprio da
engine", so que de verdade executavel aqui.)

Depois e so jogar o arquivo gerado (+ a imagem do tileset, que fica do
lado) dentro da pasta `assets/` do projeto e usar, no script Lua:

    create.tilemap.Mapa1 = { File = "mapa1.lsm", Position = {0, 0} }

A engine (Stage) le e desenha o mapa inteiro sozinha - com culling de
viewport (so desenha os tiles que aparecem na tela), sem precisar de
nenhum codigo Lua de tilemap escrito na mao.
"""

import os
import shutil

from kivy.app import App
try:
    from kivy.core.window import Window
except Exception:  # pragma: no cover - ambiente sem janela
    Window = None
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.graphics import Color, Rectangle, Line
from kivy.core.image import Image as CoreImage

from . import permissions as perms
from . import theme
from . import filebrowser
from . import tilemap

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TILE_EXTS = (tilemap.EXT_LSM.lower(), tilemap.EXT_JSONTM.lower())


def _popup(title, content, size_hint=(0.92, 0.86)):
    return theme.styled_popup(title, content, size_hint=size_hint)


def _write_crash_log(text):
    candidates = []
    try:
        candidates.append(os.path.join(perms.storage_dir(), "TilemapEditor_erro.txt"))
    except Exception:
        pass
    candidates.append(os.path.join(BASE, "TilemapEditor_erro.txt"))
    for path in candidates:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return path
        except Exception:
            continue
    return None


def _find_tilemap_files():
    """Procura .lsm/.JsonTm nos lugares mais comuns, igual ao "achador" de
    .Lsp do project.py, pra listar na tela inicial."""
    seen, out = set(), []
    storage = perms.storage_dir()
    bases = [storage]
    parent = os.path.dirname(storage.rstrip(os.sep))
    if parent:
        bases.append(parent)
        bases.append(os.path.join(parent, "Download"))
    for b in bases:
        if not b or not os.path.isdir(b):
            continue
        try:
            for fn in sorted(os.listdir(b)):
                if fn.lower().endswith(TILE_EXTS):
                    full = os.path.join(b, fn)
                    if full not in seen:
                        seen.add(full)
                        out.append(full)
        except Exception:
            pass
    return out


def _safe_filename(name):
    keep = [c if (c.isalnum() or c in " _-") else "_" for c in (name or "")]
    return "".join(keep).strip() or "mapa"


# ---------------------------------------------------------------- viewport
class TilemapCanvas(Widget):
    """O "plano cartesiano" central: grade + tiles pintados, com pan/zoom
    e as ferramentas de pintura. Linha 0 da grade fica no TOPO (como
    qualquer editor de tilemap/planilha), coerente com a Y-para-baixo que
    o resto da engine (Lua) ja usa."""

    def __init__(self, map_data, tileset_tex, **kw):
        Widget.__init__(self, **kw)
        self.map_data = map_data
        self.tileset_tex = tileset_tex
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.tool = "pincel"
        self.current_tile = 1
        self._undo_stack = []
        self._stroke = None
        self._rect_start = None
        self._rect_cur = None
        self._pan_last = None
        self._fitted = False
        self.on_hover = None   # callback opcional: (col, row) -> None
        self.bind(size=self._on_resize, pos=lambda *a: self.redraw())
        self.redraw()

    def set_tileset(self, tex):
        self.tileset_tex = tex
        self.redraw()

    def tile_w(self):
        return self.map_data["tile_w"]

    def tile_h(self):
        return self.map_data["tile_h"]

    def cols(self):
        return self.map_data["cols"]

    def rows(self):
        return self.map_data["rows"]

    def in_bounds(self, col, row):
        return 0 <= col < self.cols() and 0 <= row < self.rows()

    def _on_resize(self, *_a):
        if not self._fitted and self.width > 1 and self.height > 1:
            self.fit_to_view()
            self._fitted = True
        else:
            self.redraw()

    # ---------------------------------------------------------- geometria
    def tile_screen_rect(self, col, row):
        tw = self.tile_w() * self.zoom
        th = self.tile_h() * self.zoom
        sx = self.x + self.pan_x + col * tw
        sy = self.y + self.height - self.pan_y - (row + 1) * th
        return sx, sy, tw, th

    def tile_bounds_screen(self, cmin, cmax, rmin, rmax):
        tw = self.tile_w() * self.zoom
        th = self.tile_h() * self.zoom
        x0 = self.x + self.pan_x + cmin * tw
        x1 = self.x + self.pan_x + (cmax + 1) * tw
        y_top = self.y + self.height - self.pan_y - rmin * th
        y_bottom = self.y + self.height - self.pan_y - (rmax + 1) * th
        return x0, y_bottom, x1 - x0, y_top - y_bottom

    def screen_to_tile(self, sx, sy):
        tw = self.tile_w() * self.zoom
        th = self.tile_h() * self.zoom
        if tw <= 0 or th <= 0:
            return -1, -1
        lx = sx - self.x - self.pan_x
        ly = (self.y + self.height - self.pan_y) - sy
        col = int(lx // tw) if lx >= 0 else int(lx // tw)
        row = int(ly // th) if ly >= 0 else int(ly // th)
        return col, row

    def fit_to_view(self):
        cols, rows = self.cols(), self.rows()
        tw, th = self.tile_w(), self.tile_h()
        map_w, map_h = cols * tw, rows * th
        if map_w <= 0 or map_h <= 0 or self.width <= 1 or self.height <= 1:
            self.zoom = 1.0
        else:
            self.zoom = max(0.02, min(self.width / map_w, self.height / map_h) * 0.94)
        self.pan_x = (self.width - map_w * self.zoom) / 2.0
        self.pan_y = (self.height - map_h * self.zoom) / 2.0
        self.redraw()

    def zoom_by(self, factor, center=None):
        old_zoom = self.zoom
        new_zoom = max(0.05, min(16.0, self.zoom * factor))
        if center is None:
            center = (self.x + self.width / 2.0, self.y + self.height / 2.0)
        cx, cy = center
        wx = (cx - self.x - self.pan_x) / old_zoom
        wy = (cy - self.y - self.pan_y) / old_zoom
        self.zoom = new_zoom
        self.pan_x = (cx - self.x) - wx * new_zoom
        self.pan_y = (cy - self.y) - wy * new_zoom
        self.redraw()

    # -------------------------------------------------------------- desenho
    def _visible_range(self):
        cols, rows = self.cols(), self.rows()
        tw = self.tile_w() * self.zoom
        th = self.tile_h() * self.zoom
        if tw <= 0 or th <= 0:
            return 0, -1, 0, -1
        c0, r0 = self.screen_to_tile(self.x, self.y + self.height)
        c1, r1 = self.screen_to_tile(self.x + self.width, self.y)
        col_min = max(0, min(c0, c1) - 1)
        col_max = min(cols - 1, max(c0, c1) + 1)
        row_min = max(0, min(r0, r1) - 1)
        row_max = min(rows - 1, max(r0, r1) + 1)
        return col_min, col_max, row_min, row_max

    def redraw(self, *_a):
        self.canvas.clear()
        with self.canvas:
            Color(*theme.EDITOR_BG)
            Rectangle(pos=self.pos, size=self.size)
            self._draw_tiles()
            self._draw_grid()
            self._draw_rect_preview()

    def _draw_tiles(self):
        col_min, col_max, row_min, row_max = self._visible_range()
        if col_min > col_max or row_min > row_max:
            return
        cols = self.cols()
        tw_p = self.tile_w() * self.zoom
        th_p = self.tile_h() * self.zoom
        tex = self.tileset_tex
        data = self.map_data["layers"][0]["data"]
        Color(1, 1, 1, 1)
        for row in range(row_min, row_max + 1):
            base = row * cols
            for col in range(col_min, col_max + 1):
                tid = data[base + col]
                if not tid:
                    continue
                sx, sy, w, h = self.tile_screen_rect(col, row)
                if tex is not None:
                    u0, v0, u1, v1 = tilemap.tile_uv(tid, tex.width, tex.height,
                                                     self.tile_w(), self.tile_h())
                    Rectangle(pos=(sx, sy), size=(w, h), texture=tex,
                             tex_coords=(u0, v0, u1, v0, u1, v1, u0, v1))
                else:
                    Color(0.85, 0.35, 0.85, 1)
                    Rectangle(pos=(sx, sy), size=(w, h))
                    Color(1, 1, 1, 1)

    def _draw_grid(self):
        tw = self.tile_w() * self.zoom
        th = self.tile_h() * self.zoom
        if tw < 3 or th < 3:
            # zoom bem baixo: linha por tile so viraria ruido visual - so
            # a borda do mapa inteiro (ainda assim util pra se localizar).
            x0, y0, w, h = self.tile_bounds_screen(0, self.cols() - 1, 0, self.rows() - 1)
            Color(0.35, 0.42, 0.55, 0.9)
            Line(rectangle=(x0, y0, w, h), width=1.2)
            return
        col_min, col_max, row_min, row_max = self._visible_range()
        x0, y0, w, h = self.tile_bounds_screen(col_min, col_max, row_min, row_max)
        Color(0.3, 0.34, 0.42, 0.5)
        for col in range(col_min, col_max + 2):
            x = self.x + self.pan_x + col * tw
            Line(points=[x, y0, x, y0 + h], width=1.0)
        for row in range(row_min, row_max + 2):
            y = self.y + self.height - self.pan_y - row * th
            Line(points=[x0, y, x0 + w, y], width=1.0)

    def _draw_rect_preview(self):
        if self.tool != "rect" or not self._rect_start or not self._rect_cur:
            return
        c0, r0 = self._rect_start
        c1, r1 = self._rect_cur
        cmin, cmax = sorted((c0, c1))
        rmin, rmax = sorted((r0, r1))
        x0, y0, w, h = self.tile_bounds_screen(cmin, cmax, rmin, rmax)
        Color(1, 0.85, 0.2, 0.95)
        Line(rectangle=(x0, y0, w, h), width=2.0)

    # -------------------------------------------------------------- edicao
    def _begin_stroke(self):
        self._stroke = {}

    def _end_stroke(self):
        if self._stroke:
            self._undo_stack.append(self._stroke)
            if len(self._undo_stack) > 40:
                self._undo_stack.pop(0)
        self._stroke = None

    def undo(self):
        if not self._undo_stack:
            return False
        stroke = self._undo_stack.pop()
        data = self.map_data["layers"][0]["data"]
        for idx, old in stroke.items():
            data[idx] = old
        self.redraw()
        return True

    def _paint_tile(self, col, row, tid):
        if not self.in_bounds(col, row):
            return
        idx = row * self.cols() + col
        data = self.map_data["layers"][0]["data"]
        old = data[idx]
        if old == tid:
            return
        if self._stroke is not None and idx not in self._stroke:
            self._stroke[idx] = old
        data[idx] = tid
        self.redraw()

    def _flood_fill(self, col, row, new_tile):
        cols, rows = self.cols(), self.rows()
        data = self.map_data["layers"][0]["data"]
        start_idx = row * cols + col
        target = data[start_idx]
        if target == new_tile:
            return
        stack = [(col, row)]
        seen = set([start_idx])
        max_steps = cols * rows + 4
        steps = 0
        while stack and steps < max_steps:
            c, r = stack.pop()
            idx = r * cols + c
            if data[idx] != target:
                continue
            if self._stroke is not None and idx not in self._stroke:
                self._stroke[idx] = data[idx]
            data[idx] = new_tile
            steps += 1
            for nc, nr in ((c - 1, r), (c + 1, r), (c, r - 1), (c, r + 1)):
                if 0 <= nc < cols and 0 <= nr < rows:
                    nidx = nr * cols + nc
                    if nidx not in seen and data[nidx] == target:
                        seen.add(nidx)
                        stack.append((nc, nr))
        self.redraw()

    # --------------------------------------------------------------- touch
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        touch.grab(self)
        if self.tool == "pan":
            self._pan_last = touch.pos
            return True
        col, row = self.screen_to_tile(*touch.pos)
        if self.tool == "bucket":
            if self.in_bounds(col, row):
                self._begin_stroke()
                self._flood_fill(col, row, self.current_tile)
                self._end_stroke()
            return True
        if self.tool == "rect":
            if self.in_bounds(col, row):
                self._rect_start = (col, row)
                self._rect_cur = (col, row)
                self.redraw()
            return True
        self._begin_stroke()
        tid = 0 if self.tool == "eraser" else self.current_tile
        self._paint_tile(col, row, tid)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        if self.tool == "pan" and self._pan_last is not None:
            lx, ly = self._pan_last
            dx, dy = touch.x - lx, touch.y - ly
            self.pan_x += dx
            self.pan_y -= dy
            self._pan_last = touch.pos
            self.redraw()
            return True
        col, row = self.screen_to_tile(*touch.pos)
        if self.tool == "rect":
            if self.in_bounds(col, row):
                self._rect_cur = (col, row)
                self.redraw()
            return True
        if self.tool in ("pincel", "eraser"):
            tid = 0 if self.tool == "eraser" else self.current_tile
            self._paint_tile(col, row, tid)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        if self.tool == "rect" and self._rect_start:
            c0, r0 = self._rect_start
            c1, r1 = self._rect_cur or self._rect_start
            self._begin_stroke()
            for row in range(min(r0, r1), max(r0, r1) + 1):
                for col in range(min(c0, c1), max(c0, c1) + 1):
                    self._paint_tile(col, row, self.current_tile)
            self._end_stroke()
            self._rect_start = None
            self._rect_cur = None
            self.redraw()
        elif self.tool in ("pincel", "eraser"):
            self._end_stroke()
        return True


# ------------------------------------------------------------ paleta (tile)
class TileSwatch(Widget):
    """Um "botao" quadrado que mostra um tile do tileset (ou o simbolo de
    vazio/apagar, pro tile_id 0) - toca pra selecionar como tile atual."""

    def __init__(self, tile_id, tex, tile_w, tile_h, on_pick, **kw):
        Widget.__init__(self, **kw)
        self.tile_id = tile_id
        self.tex = tex
        self.tile_w = tile_w
        self.tile_h = tile_h
        self.on_pick = on_pick
        self.selected = False
        self.bind(pos=lambda *a: self.redraw(), size=lambda *a: self.redraw())
        self.redraw()

    def redraw(self):
        self.canvas.clear()
        with self.canvas:
            Color(*theme.SURFACE_2)
            Rectangle(pos=self.pos, size=self.size)
            if self.tile_id == 0:
                Color(0.85, 0.4, 0.4, 1)
                Line(points=[self.x + 6, self.y + 6, self.x + self.width - 6,
                            self.y + self.height - 6], width=1.4)
                Line(points=[self.x + self.width - 6, self.y + 6, self.x + 6,
                            self.y + self.height - 6], width=1.4)
            elif self.tex is not None:
                Color(1, 1, 1, 1)
                u0, v0, u1, v1 = tilemap.tile_uv(self.tile_id, self.tex.width, self.tex.height,
                                                 self.tile_w, self.tile_h)
                Rectangle(pos=(self.x + 2, self.y + 2), size=(self.width - 4, self.height - 4),
                         texture=self.tex, tex_coords=(u0, v0, u1, v0, u1, v1, u0, v1))
            if self.selected:
                Color(*theme.ACCENT)
                Line(rectangle=(self.x + 1, self.y + 1, self.width - 2, self.height - 2), width=2.2)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.on_pick(self.tile_id)
            return True
        return False


# -------------------------------------------------------------------- App
class TilemapEditorApp(App):
    title = "LuaStudio - Editor de Tilemaps"

    def build(self):
        if Window is not None:
            try:
                Window.clearcolor = theme.BG
            except Exception:
                pass
        # esse app e feito pra usar em paisagem (landscape) - so tem
        # efeito de verdade num APK exportado; no Pydroid/desktop e no-op.
        perms.set_orientation("landscape")
        self.root_box = BoxLayout(orientation="vertical")
        self.map_data = None
        self.map_path = None
        self.tileset_abs = None
        self.tileset_tex = None
        self.canvas_widget = None
        self.status_label = None
        try:
            self._show_launcher()
        except Exception:
            import traceback
            tb = traceback.format_exc()
            print("[TilemapEditor] ERRO AO ABRIR:\n%s" % tb)
            saved_at = _write_crash_log(tb)
            self.root_box.clear_widgets()
            self.root_box.add_widget(self._crash_widget(tb, saved_at))
        return self.root_box

    def _crash_widget(self, tb, saved_at):
        box = BoxLayout(orientation="vertical", padding=14, spacing=8)
        box.add_widget(Label(text="[erro] O Editor de Tilemaps nao conseguiu abrir",
                             font_size=16, color=(1, 0.4, 0.4, 1), size_hint_y=None, height=36))
        if saved_at:
            box.add_widget(Label(text="Erro salvo em:\n%s" % saved_at, font_size=12,
                                 color=theme.TEXT_DIM, size_hint_y=None, height=44))
        scroll = ScrollView()
        err_label = Label(text=tb, font_size=11, color=theme.TEXT, halign="left", valign="top")
        err_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        scroll.add_widget(err_label)
        box.add_widget(scroll)
        return box

    def _log(self, msg):
        print("[TilemapEditor] %s" % msg)
        self._set_status(str(msg))

    def _set_status(self, text):
        if self.status_label is not None:
            self.status_label.text = text

    # -------------------------------------------------------------- telas
    def _show_launcher(self):
        self.map_data = None
        self.canvas_widget = None
        self.root_box.clear_widgets()
        box = BoxLayout(orientation="vertical", spacing=10, padding=18)
        box.add_widget(Label(text="Editor de Tilemaps", font_size=24, bold=True,
                             color=theme.TEXT, size_hint_y=None, height=42))
        box.add_widget(Label(text="Crie um mapa novo ou abra um .lsm / .JsonTm existente.",
                             font_size=13, color=theme.TEXT_DIM, size_hint_y=None, height=26))

        new_btn = theme.IconButton(icon="add", text="Novo mapa", size_hint_y=None, height=54,
                                    font_size=16, bg_color=theme.PLAY, radius=14)
        new_btn.bind(on_release=lambda *a: self.open_new_map_dialog())
        box.add_widget(new_btn)

        open_btn = theme.IconButton(icon="folder", text="Abrir mapa existente...", size_hint_y=None,
                                     height=54, font_size=15, bg_color=theme.ACCENT, radius=14)
        open_btn.bind(on_release=lambda *a: self._open_existing_dialog())
        box.add_widget(open_btn)

        box.add_widget(Label(text="Mapas encontrados (Armazenamento / Download)",
                             size_hint_y=None, height=24, font_size=12, color=theme.TEXT_DIM))
        scroll = ScrollView()
        listing = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None, padding=(0, 4))
        listing.bind(minimum_height=lambda w, v: setattr(w, "height", v))
        scroll.add_widget(listing)
        box.add_widget(scroll)

        files = _find_tilemap_files()
        if not files:
            listing.add_widget(Label(text="Nenhum .lsm/.JsonTm encontrado ainda.",
                                     color=theme.TEXT_DIM, size_hint_y=None, height=36))
        for full in files:
            b = theme.RoundButton(text=os.path.basename(full), size_hint_y=None, height=46,
                                  font_size=13, bg_color=theme.SURFACE_2, radius=10)
            b.bind(on_release=lambda _b, f=full: self._load_existing(f))
            listing.add_widget(b)

        self.status_label = Label(text="", size_hint_y=None, height=24, font_size=12,
                                  color=theme.STOP)
        box.add_widget(self.status_label)
        self.root_box.add_widget(box)

    def _open_existing_dialog(self):
        filebrowser.open_picker(
            title="Abrir mapa (.lsm / .JsonTm)", mode="file", start=perms.storage_dir(),
            extensions=[tilemap.EXT_LSM, tilemap.EXT_JSONTM, ".json"],
            shortcuts=filebrowser.default_shortcuts(), on_select=self._load_existing)

    def _load_existing(self, path):
        try:
            map_data = tilemap.load(path)
        except Exception as ex:
            self._log("[erro ao abrir '%s'] %s" % (os.path.basename(path), ex))
            return
        tex_path = tilemap.tileset_path_for(path, map_data)
        if not tex_path or not os.path.isfile(tex_path):
            self._log("[aviso] tileset '%s' nao encontrado do lado do mapa - "
                      "use 'Trocar tileset' no editor." % (map_data.get("tileset") or "?"))
            tex_path = None
        self._open_editor(map_data, tileset_abs=tex_path, map_path=path)

    def open_new_map_dialog(self):
        box = BoxLayout(orientation="vertical", spacing=6, padding=10)
        popup = _popup("Novo Mapa", box)

        def label(text):
            box.add_widget(Label(text=text, size_hint_y=None, height=20, font_size=12,
                                 color=theme.TEXT_DIM))

        def text_input(default, filt=None):
            return TextInput(text=str(default), multiline=False, input_filter=filt,
                             background_color=theme.EDITOR_BG, foreground_color=theme.TEXT,
                             cursor_color=theme.CURSOR, padding=(10, 10),
                             size_hint_y=None, height=42)

        label("Nome do pacote/mapa")
        name_in = text_input("mapa1")
        box.add_widget(name_in)

        label("Tamanho do tile em pixels (largura x altura)")
        row1 = BoxLayout(size_hint_y=None, height=42, spacing=8)
        tw_in = text_input(64, filt="int")
        th_in = text_input(64, filt="int")
        row1.add_widget(tw_in)
        row1.add_widget(Label(text="x", size_hint_x=None, width=18, color=theme.TEXT_DIM))
        row1.add_widget(th_in)
        box.add_widget(row1)

        label("Tamanho da grade (colunas x linhas)")
        row2 = BoxLayout(size_hint_y=None, height=42, spacing=8)
        cols_in = text_input(100, filt="int")
        rows_in = text_input(100, filt="int")
        row2.add_widget(cols_in)
        row2.add_widget(Label(text="x", size_hint_x=None, width=18, color=theme.TEXT_DIM))
        row2.add_widget(rows_in)
        box.add_widget(row2)

        label("Tileset (PNG com os tiles lado a lado, todos do mesmo tamanho)")
        tileset_state = {"path": None}
        tileset_label = Label(text="(nenhum tileset escolhido)", font_size=12,
                              color=theme.TEXT_DIM, size_hint_y=None, height=28)
        box.add_widget(tileset_label)

        def pick_tileset(*_a):
            def picked(p):
                tileset_state["path"] = p
                tileset_label.text = os.path.basename(p)
                tileset_label.color = theme.TEXT
            filebrowser.open_picker(title="Escolher tileset (PNG)", mode="file",
                                    start=perms.storage_dir(), extensions=[".png", ".jpg", ".jpeg"],
                                    shortcuts=filebrowser.default_shortcuts(), on_select=picked)
        tset_btn = theme.IconButton(icon="image", text="Escolher imagem...", size_hint_y=None,
                                     height=42, bg_color=theme.WARN, radius=10)
        tset_btn.bind(on_release=pick_tileset)
        box.add_widget(tset_btn)

        err_label = Label(text="", font_size=12, color=theme.STOP, size_hint_y=None, height=24)
        box.add_widget(err_label)

        bottom = BoxLayout(size_hint_y=None, height=48, spacing=6)

        def do_create(*_a):
            try:
                tw = max(1, min(1024, int(tw_in.text or 64)))
                th = max(1, min(1024, int(th_in.text or 64)))
                cols = max(1, min(1000, int(cols_in.text or 100)))
                rows = max(1, min(1000, int(rows_in.text or 100)))
            except Exception:
                err_label.text = "Numeros invalidos."
                return
            if not tileset_state["path"]:
                err_label.text = "Escolha um tileset (PNG) antes de criar."
                return
            name = (name_in.text or "mapa1").strip() or "mapa1"
            map_data = tilemap.new_map(package=name, tile_w=tw, tile_h=th, cols=cols, rows=rows,
                                       tileset=os.path.basename(tileset_state["path"]))
            popup.dismiss()
            self._open_editor(map_data, tileset_abs=tileset_state["path"], map_path=None)
        create_btn = theme.IconButton(icon="check", text="Criar", bg_color=theme.PLAY, radius=12)
        create_btn.bind(on_release=do_create)
        cancel_btn = theme.RoundButton(text="Cancelar", size_hint_x=None, width=110,
                                       bg_color=theme.SURFACE_2, radius=12)
        cancel_btn.bind(on_release=lambda *a: popup.dismiss())
        bottom.add_widget(create_btn)
        bottom.add_widget(cancel_btn)
        box.add_widget(bottom)
        popup.open()

    # ------------------------------------------------------------- editor
    def _open_editor(self, map_data, tileset_abs=None, map_path=None):
        self.map_data = map_data
        self.map_path = map_path
        self.tileset_abs = tileset_abs
        self.tileset_tex = None
        if tileset_abs and os.path.isfile(tileset_abs):
            try:
                tex = CoreImage(tileset_abs).texture
                tex.mag_filter = "nearest"
                tex.min_filter = "nearest"
                self.tileset_tex = tex
            except Exception as ex:
                self._log("[erro ao carregar tileset] %s" % ex)
        self.root_box.clear_widgets()
        self.root_box.add_widget(self._build_editor())

    def _build_editor(self):
        root = BoxLayout(orientation="vertical")
        root.add_widget(self._editor_topbar())
        body = BoxLayout()
        body.add_widget(self._tool_column())
        self.canvas_widget = TilemapCanvas(self.map_data, self.tileset_tex)
        body.add_widget(self.canvas_widget)
        body.add_widget(self._palette_column())
        root.add_widget(body)
        self.status_label = Label(text="", size_hint_y=None, height=24, font_size=12,
                                  color=theme.TEXT_DIM)
        root.add_widget(self.status_label)
        self._set_status("Pronto - toque no viewport pra pintar.")
        return root

    def _bar(self, height):
        bar = BoxLayout(size_hint_y=None, height=height, spacing=6, padding=(8, 6))
        with bar.canvas.before:
            Color(*theme.SURFACE)
            bg = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(pos=lambda *a: setattr(bg, "pos", bar.pos),
                size=lambda *a: setattr(bg, "size", bar.size))
        return bar

    def _editor_topbar(self):
        bar = self._bar(52)
        back_btn = theme.RoundButton(text="Voltar", size_hint_x=None, width=46,
                                     bg_color=theme.SURFACE_2, radius=10)
        back_btn.bind(on_release=lambda *a: self._show_launcher())
        bar.add_widget(back_btn)

        md = self.map_data
        title = Label(text="Mapa: %s  (%dx%d tiles, %dx%dpx)" % (
            md.get("package") or "mapa", md["cols"], md["rows"], md["tile_w"], md["tile_h"]),
            font_size=13, color=theme.TEXT, halign="left", valign="middle")
        title.bind(size=lambda w, v: setattr(w, "text_size", v))
        bar.add_widget(title)

        undo_btn = theme.IconButton(icon="undo", text="Desfazer", size_hint_x=None, width=110,
                                     bg_color=theme.SURFACE_2, radius=10)
        undo_btn.bind(on_release=lambda *a: self._do_undo())
        bar.add_widget(undo_btn)

        zoom_out = theme.IconButton(icon="zoom_out", text="", size_hint_x=None, width=42,
                                     bg_color=theme.SURFACE_2, radius=10)
        zoom_out.bind(on_release=lambda *a: self.canvas_widget.zoom_by(0.8))
        zoom_in = theme.IconButton(icon="zoom_in", text="", size_hint_x=None, width=42,
                                    bg_color=theme.SURFACE_2, radius=10)
        zoom_in.bind(on_release=lambda *a: self.canvas_widget.zoom_by(1.25))
        fit_btn = theme.IconButton(icon="fit", text="", size_hint_x=None, width=42,
                                    bg_color=theme.SURFACE_2, radius=10)
        fit_btn.bind(on_release=lambda *a: self.canvas_widget.fit_to_view())
        bar.add_widget(zoom_out)
        bar.add_widget(zoom_in)
        bar.add_widget(fit_btn)

        save_btn = theme.IconButton(icon="save", text="Salvar", size_hint_x=None, width=104,
                                     bg_color=theme.PLAY, radius=10)
        save_btn.bind(on_release=lambda *a: self.open_save_dialog())
        bar.add_widget(save_btn)
        return bar

    def _tool_column(self):
        col = BoxLayout(orientation="vertical", size_hint_x=None, width=60, spacing=4, padding=4)
        with col.canvas.before:
            Color(*theme.SURFACE)
            bg = Rectangle(pos=col.pos, size=col.size)
        col.bind(pos=lambda *a: setattr(bg, "pos", col.pos),
                size=lambda *a: setattr(bg, "size", col.size))

        tools = [("pincel", "Pincel", "Pincel"), ("eraser", "Borracha", "Borracha"),
                ("bucket", "Balde", "Balde"), ("rect", "▭", "Retangulo"),
                ("pan", "Mover", "Mover")]
        self._tool_buttons = {}

        def pick_tool(name, label):
            self.canvas_widget.tool = name
            for n, b in self._tool_buttons.items():
                b.bg_color = list(theme.ACCENT if n == name else theme.SURFACE_2)
            self._set_status("Ferramenta: %s" % label)

        for name, icon, label_txt in tools:
            b = theme.RoundButton(text=icon, font_size=20, size_hint_y=None, height=50,
                                  bg_color=theme.ACCENT if name == "pincel" else theme.SURFACE_2,
                                  radius=12)
            b.bind(on_release=lambda _b, n=name, lb=label_txt: pick_tool(n, lb))
            self._tool_buttons[name] = b
            col.add_widget(b)
        col.add_widget(Widget())
        return col

    def _palette_column(self):
        col = BoxLayout(orientation="vertical", size_hint_x=None, width=164, spacing=4, padding=4)
        with col.canvas.before:
            Color(*theme.SURFACE)
            bg = Rectangle(pos=col.pos, size=col.size)
        col.bind(pos=lambda *a: setattr(bg, "pos", col.pos),
                size=lambda *a: setattr(bg, "size", col.size))
        col.add_widget(Label(text="TILESET", size_hint_y=None, height=20, font_size=11,
                             color=theme.TEXT_DIM, bold=True))

        scroll = ScrollView()
        grid = GridLayout(cols=3, spacing=3, size_hint_y=None, padding=2)
        grid.bind(minimum_height=lambda w, v: setattr(w, "height", v))
        scroll.add_widget(grid)
        col.add_widget(scroll)

        self._swatches = []

        def pick(tid):
            self.canvas_widget.current_tile = tid
            for sw in self._swatches:
                sw.selected = (sw.tile_id == tid)
                sw.redraw()
            self._set_status("Tile atual: %s" % ("vazio/apagar" if tid == 0 else tid))

        empty_sw = TileSwatch(0, None, self.map_data["tile_w"], self.map_data["tile_h"], pick,
                              size_hint_y=None, height=46)
        grid.add_widget(empty_sw)
        self._swatches.append(empty_sw)

        default_tid = 0
        if self.tileset_tex is not None:
            _c, _r, total = tilemap.tileset_tile_count(
                self.tileset_tex.width, self.tileset_tex.height,
                self.map_data["tile_w"], self.map_data["tile_h"])
            for tid in range(1, total + 1):
                sw = TileSwatch(tid, self.tileset_tex, self.map_data["tile_w"],
                                self.map_data["tile_h"], pick, size_hint_y=None, height=46)
                grid.add_widget(sw)
                self._swatches.append(sw)
            if total >= 1:
                default_tid = 1
        else:
            col.add_widget(Label(text="(sem tileset)", font_size=11, color=theme.STOP,
                                 size_hint_y=None, height=22))

        relink_btn = theme.IconButton(icon="image", text="Trocar tileset", size_hint_y=None, height=38,
                                       font_size=11, bg_color=theme.WARN, radius=10)
        relink_btn.bind(on_release=lambda *a: self._pick_relink_tileset())
        col.add_widget(relink_btn)

        pick(default_tid)
        return col

    def _pick_relink_tileset(self):
        def picked(p):
            try:
                tex = CoreImage(p).texture
                tex.mag_filter = "nearest"
                tex.min_filter = "nearest"
            except Exception as ex:
                self._log("[erro ao carregar tileset] %s" % ex)
                return
            self.tileset_abs = p
            self.tileset_tex = tex
            self.map_data["tileset"] = os.path.basename(p)
            self.canvas_widget.set_tileset(tex)
            self.root_box.clear_widgets()
            self.root_box.add_widget(self._build_editor())
        filebrowser.open_picker(title="Escolher tileset (PNG)", mode="file",
                                start=perms.storage_dir(), extensions=[".png", ".jpg", ".jpeg"],
                                shortcuts=filebrowser.default_shortcuts(), on_select=picked)

    def _do_undo(self):
        if self.canvas_widget is not None and self.canvas_widget.undo():
            self._set_status("Desfeito.")
        else:
            self._set_status("Nada pra desfazer.")

    # -------------------------------------------------------------- salvar
    def open_save_dialog(self):
        if self.map_data is None:
            return
        box = BoxLayout(orientation="vertical", spacing=6, padding=10)
        popup = _popup("Salvar Tilemap", box)

        box.add_widget(Label(text="Nome do pacote/arquivo", size_hint_y=None, height=20,
                             font_size=12, color=theme.TEXT_DIM))
        name_in = TextInput(text=self.map_data.get("package") or "mapa1", multiline=False,
                            background_color=theme.EDITOR_BG, foreground_color=theme.TEXT,
                            cursor_color=theme.CURSOR, padding=(10, 10),
                            size_hint_y=None, height=42)
        box.add_widget(name_in)

        box.add_widget(Label(text="Formato", size_hint_y=None, height=20, font_size=12,
                             color=theme.TEXT_DIM))
        fmt_state = {"fmt": "lsm"}
        fmt_row = BoxLayout(size_hint_y=None, height=44, spacing=6)
        lsm_btn = theme.RoundButton(text="Binario .lsm binario (recomendado)", font_size=12,
                                    bg_color=theme.ACCENT, radius=10)
        json_btn = theme.RoundButton(text="JSON .JsonTm (JSON)", font_size=12,
                                     bg_color=theme.SURFACE_2, radius=10)

        def pick_fmt(fmt):
            fmt_state["fmt"] = fmt
            lsm_btn.bg_color = list(theme.ACCENT if fmt == "lsm" else theme.SURFACE_2)
            json_btn.bg_color = list(theme.ACCENT if fmt == "json" else theme.SURFACE_2)
        lsm_btn.bind(on_release=lambda *a: pick_fmt("lsm"))
        json_btn.bind(on_release=lambda *a: pick_fmt("json"))
        fmt_row.add_widget(lsm_btn)
        fmt_row.add_widget(json_btn)
        box.add_widget(fmt_row)
        box.add_widget(Label(
            text="Dica: .lsm e binario (RLE) - menor e mais rapido de carregar.\n"
                 ".JsonTm e texto legivel, bom pra debugar/editar na mao.",
            font_size=11, color=theme.TEXT_DIM, size_hint_y=None, height=44))

        box.add_widget(Label(text="Pasta de destino", size_hint_y=None, height=20,
                             font_size=12, color=theme.TEXT_DIM))
        folder_state = {"path": os.path.dirname(self.map_path) if self.map_path
                        else perms.storage_dir()}
        folder_label = Label(text=folder_state["path"], font_size=11, color=theme.TEXT,
                             size_hint_y=None, height=28)
        box.add_widget(folder_label)

        def do_browse(*_a):
            def picked(p):
                folder_state["path"] = p
                folder_label.text = p
            filebrowser.open_picker(title="Pasta de destino", mode="folder",
                                    start=folder_state["path"],
                                    shortcuts=filebrowser.default_shortcuts(), on_select=picked)
        browse_btn = theme.IconButton(icon="folder", text="Escolher pasta...", size_hint_y=None,
                                       height=40, bg_color=theme.WARN, radius=10)
        browse_btn.bind(on_release=do_browse)
        box.add_widget(browse_btn)

        err_label = Label(text="", font_size=12, color=theme.STOP, size_hint_y=None, height=22)
        box.add_widget(err_label)

        bottom = BoxLayout(size_hint_y=None, height=48, spacing=6)

        def do_save(*_a):
            name = (name_in.text or "mapa1").strip() or "mapa1"
            self.map_data["package"] = name
            safe = _safe_filename(name)
            dest_folder = folder_state["path"]
            try:
                if not os.path.isdir(dest_folder):
                    os.makedirs(dest_folder)
            except Exception as ex:
                err_label.text = "Nao foi possivel usar essa pasta: %s" % ex
                return
            tileset_name = self.map_data.get("tileset") or ""
            if self.tileset_abs and os.path.isfile(self.tileset_abs):
                tileset_name = os.path.basename(self.tileset_abs)
                dest_tex = os.path.join(dest_folder, tileset_name)
                try:
                    if os.path.abspath(dest_tex) != os.path.abspath(self.tileset_abs):
                        shutil.copyfile(self.tileset_abs, dest_tex)
                except Exception as ex:
                    self._log("[aviso] nao copiou o tileset: %s" % ex)
            self.map_data["tileset"] = tileset_name
            dest_map = os.path.join(dest_folder, safe)
            try:
                final_path = tilemap.save(self.map_data, dest_map, fmt=fmt_state["fmt"])
            except Exception as ex:
                err_label.text = "Erro ao salvar: %s" % ex
                return
            self.map_path = final_path
            popup.dismiss()
            self._log("[salvo] %s" % final_path)
        save_btn = theme.IconButton(icon="save", text="Salvar", bg_color=theme.PLAY, radius=12)
        save_btn.bind(on_release=do_save)
        cancel_btn = theme.RoundButton(text="Cancelar", size_hint_x=None, width=110,
                                       bg_color=theme.SURFACE_2, radius=12)
        cancel_btn.bind(on_release=lambda *a: popup.dismiss())
        bottom.add_widget(save_btn)
        bottom.add_widget(cancel_btn)
        box.add_widget(bottom)
        popup.open()


def main():
    TilemapEditorApp().run()

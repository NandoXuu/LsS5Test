# -*- coding: utf-8 -*-
"""Tela inicial do LuaStudio.

E a PRIMEIRA coisa que aparece ao abrir a engine - sem editor, sem
console. Mostra os projetos salvos em `Documents/` como cards (com icone,
nome e botoes Play / Editar / Apagar) e o botao de criar projeto novo.

Criar projeto abre uma janelinha pra escolher o icone (glifo + cor, ou uma
imagem do dispositivo) e o nome; o projeto ganha a propria pasta em
`Documents/<nome>/`.
"""

import os
import time

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from . import theme
from . import filebrowser
from . import permissions as perms
from . import project as luaproject

CARD_H = 134
CARD_MIN_W = 400          # largura minima de um card (define quantas colunas)

ICON_IMAGE_MAP = {
    "🎮":"play", "🚀":"play", "👾":"plugin", "🐉":"map", "🧙":"system",
    "🧩":"plugin", "🌌":"screen", "🔥":"warning", "🐱":"home", "🐸":"home",
    "🎯":"target", "🏰":"map", "🤖":"system", "🎲":"pages", "💎":"star",
    "🍄":"image", "🌈":"image", "👻":"system", "🦊":"home", "🚗":"screen",
    "🦖":"map", "🐧":"screen", "🛸":"screen",
}


# ------------------------------------------------------------------ utils
def _lbl(text, size=14, color=theme.TEXT, bold=False, halign="left",
         shorten=False, **kw):
    """Label de uma linha alinhado (sem precisar repetir o bind de
    text_size toda vez)."""
    kw.setdefault("valign", "middle")
    if shorten:
        kw["shorten"] = True
        kw["shorten_from"] = "right" if halign == "left" else "left"
    lab = Label(text=text, font_size=size, color=color, bold=bold,
                halign=halign, **kw)
    lab.bind(size=lambda w, v: setattr(w, "text_size", v))
    return lab


def _wrap_label(text, size=13, color=theme.TEXT_DIM, halign="left", height=None):
    """Label com quebra de linha; a altura acompanha o texto (a menos que
    `height` seja dado)."""
    lab = Label(text=text, font_size=size, color=color, halign=halign,
                valign="top", size_hint_y=None)
    lab.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
    if height:
        lab.height = height
    else:
        lab.bind(texture_size=lambda w, v: setattr(w, "height", v[1] + 4))
    return lab


def _short_path(path, keep=38):
    if len(path) <= keep:
        return path
    return "…" + path[-(keep - 1):]


def _fmt_date(ts):
    try:
        return time.strftime("%d/%m/%Y", time.localtime(float(ts)))
    except Exception:
        return ""


# --------------------------------------------------------------- IconTile
class IconTile(FloatLayout):
    """Quadradinho arredondado do icone do projeto: bloco colorido com um
    glifo (ou a inicial do nome) ou uma imagem."""

    def __init__(self, icon=None, name="", base_path=None, size_px=60,
                 radius=14, **kw):
        kw.setdefault("size_hint", (None, None))
        kw["size"] = (size_px, size_px)
        FloatLayout.__init__(self, **kw)
        self._px = size_px
        with self.canvas.before:
            self._col = Color(*theme.SURFACE_2)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                          radius=[radius])
        self.bind(pos=self._sync, size=self._sync)
        self._label = Label(text="", bold=True, font_size=size_px * 0.46,
                            color=(1, 1, 1, 0.96))
        self._img = None
        self.add_widget(self._label)
        self.set_icon(icon, name, base_path)

    def _sync(self, *_a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_icon(self, icon, name="", base_path=None, image_abs=None):
        """`image_abs`: caminho absoluto de uma imagem (usado no preview do
        dialogo de criacao, antes do projeto existir em disco)."""
        icon = luaproject.normalize_icon(icon)
        self._col.rgba = theme.hex_to_rgba(icon["color"])
        if self._img is not None:
            self.remove_widget(self._img)
            self._img = None
        img_path = image_abs
        if not img_path and icon.get("image") and base_path:
            img_path = os.path.join(base_path, icon["image"])
        if img_path and os.path.isfile(img_path):
            inner = self._px * 0.78
            try:
                img = Image(source=img_path, size_hint=(None, None),
                            size=(inner, inner),
                            pos_hint={"center_x": 0.5, "center_y": 0.5},
                            fit_mode="contain")
            except TypeError:  # Kivy antigo (sem fit_mode)
                img = Image(source=img_path, size_hint=(None, None),
                            size=(inner, inner),
                            pos_hint={"center_x": 0.5, "center_y": 0.5},
                            allow_stretch=True, keep_ratio=True)
            self._img = img
            self.add_widget(img)
            self._label.text = ""
            return
        glyph = icon.get("glyph") or "@initial"
        mapped_icon = ICON_IMAGE_MAP.get(glyph)
        if mapped_icon:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", mapped_icon + ".png")
            if os.path.isfile(icon_path):
                inner = self._px * 0.62
                try:
                    img = Image(source=icon_path, size_hint=(None, None), size=(inner, inner),
                                pos_hint={"center_x": 0.5, "center_y": 0.5}, fit_mode="contain")
                except TypeError:
                    img = Image(source=icon_path, size_hint=(None, None), size=(inner, inner),
                                pos_hint={"center_x": 0.5, "center_y": 0.5}, allow_stretch=True, keep_ratio=True)
                self._img = img
                self.add_widget(img)
                self._label.text = ""
                return
        if glyph == "@initial":
            text = ""
            for ch in (name or ""):
                if ch.isalnum():
                    text = ch.upper()
                    break
            glyph = text or "?"
            self._label.font_size = self._px * 0.46
        else:
            self._label.font_size = self._px * 0.50
        self._label.text = glyph


# ------------------------------------------------------------- HomeScreen
class HomeScreen(Screen):
    def __init__(self, app, **kw):
        Screen.__init__(self, name="home", **kw)
        self.app = app
        self._last_refresh = 0.0
        self._asked_storage = False
        self._flash_ev = None

        root = BoxLayout(orientation="vertical", padding=(18, 14, 18, 10),
                         spacing=12)
        root.add_widget(self._top_bar())
        root.add_widget(self._actions())
        root.add_widget(self._section_header())

        self.scroll = ScrollView(bar_width=4, bar_color=(1, 1, 1, 0.18),
                                 bar_inactive_color=(1, 1, 1, 0.07),
                                 scroll_type=["bars", "content"])
        self.grid = GridLayout(cols=1, spacing=12, size_hint_y=None,
                               padding=(0, 2, 0, 14))
        self.grid.bind(minimum_height=lambda w, v: setattr(w, "height", v))
        self.scroll.add_widget(self.grid)
        self.scroll.bind(width=self._on_scroll_width)
        root.add_widget(self.scroll)

        self.flash_label = Label(text="", font_size=13, color=theme.TEXT_DIM,
                                 size_hint_y=None, height=22)
        root.add_widget(self.flash_label)
        self.add_widget(root)

    # ------------------------------------------------------------ pecas
    def _rb(self, text, cb, color=theme.SURFACE_2, **kw):
        kw.setdefault("font_size", 14)
        kw.setdefault("radius", 12)
        b = theme.RoundButton(text=text, bg_color=color, **kw)
        b.bind(on_release=lambda *_a: self._safe(cb))
        return b

    def _safe(self, fn, *a):
        try:
            fn(*a)
        except Exception as ex:
            import traceback
            self.app.log("[erro] %s" % ex)
            self.app.log(traceback.format_exc())
            self.flash("Erro: %s" % ex, theme.STOP)

    def _top_bar(self):
        bar = BoxLayout(size_hint_y=None, height=56, spacing=12)
        bar.add_widget(IconTile({"glyph": "@initial", "color": "#6680D9"},
                                name="L", size_px=46, radius=13))
        col = BoxLayout(orientation="vertical", spacing=0)
        col.add_widget(_lbl("LuaStudio", 22, theme.TEXT, bold=True))
        col.add_widget(_lbl("Seus jogos em Lua", 12, theme.TEXT_DIM))
        bar.add_widget(col)
        plugin_btn = theme.IconButton(icon="plugin", text="", bg_color=theme.SURFACE_2, radius=12, size_hint=(None, None), size=(46, 46), pos_hint={"center_y": 0.5})
        plugin_btn.bind(on_release=lambda *_: self.app.open_plugin_manager())
        bar.add_widget(plugin_btn)
        perm_btn = theme.IconButton(icon="lock", text="", bg_color=theme.SURFACE_2, radius=12, size_hint=(None, None),
                                size=(46, 46), pos_hint={"center_y": 0.5})
        perm_btn.bind(on_release=lambda *_: self._ask_perms())
        bar.add_widget(perm_btn)
        return bar

    def _actions(self):
        row = BoxLayout(size_hint_y=None, height=54, spacing=10)
        create_btn = theme.IconButton(icon="add", text="Criar projeto",
                                      bg_color=theme.ACCENT, size_hint_x=0.62,
                                      font_size=16, radius=12, bold=True)
        create_btn.bind(on_release=lambda *_: self._safe(self.open_create_dialog))
        import_btn = theme.IconButton(icon="import", text="Importar .Lsp",
                                      bg_color=theme.SURFACE_2, size_hint_x=0.38,
                                      font_size=14, radius=12)
        import_btn.bind(on_release=lambda *_: self._safe(self.app.open_import_lsp))
        row.add_widget(create_btn)
        row.add_widget(import_btn)
        return row

    def _section_header(self):
        row = BoxLayout(size_hint_y=None, height=22, spacing=8)
        self.count_label = _lbl("SEUS PROJETOS", 11, theme.TEXT_DIM, bold=True,
                                size_hint_x=0.4)
        self.path_label = _lbl("", 11, theme.TEXT_DIM, halign="right",
                               shorten=True)
        row.add_widget(self.count_label)
        row.add_widget(self.path_label)
        return row

    # ----------------------------------------------------------- avisos
    def flash(self, msg, color=theme.TEXT_DIM, seconds=5.0):
        """Mensagem curtinha no rodape da tela inicial (some sozinha)."""
        if self._flash_ev is not None:
            self._flash_ev.cancel()
        self.flash_label.text = msg
        self.flash_label.color = color
        theme.fade_in(self.flash_label, duration=0.18)
        self._flash_ev = Clock.schedule_once(self._clear_flash, seconds)

    def _clear_flash(self, *_a):
        self._flash_ev = None
        Animation(opacity=0, d=0.25).start(self.flash_label)

    def _ask_perms(self):
        res = perms.request(["storage"])
        ok = all(res.values()) if res else True
        self.flash("Armazenamento: %s" % ("permitido" if ok else "negado - "
                   "libere nas configurações do app"),
                   theme.PLAY if ok else theme.STOP)
        self.refresh(force=True)

    # ---------------------------------------------------------- listagem
    def on_pre_enter(self, *_a):
        self.refresh()

    def _cols(self):
        return max(1, int(self.scroll.width // CARD_MIN_W))

    def _on_scroll_width(self, _w, _v):
        if self.grid.children and not getattr(self, "_empty", False):
            self.grid.cols = self._cols()

    def refresh(self, force=False):
        now = time.time()
        if not force and now - self._last_refresh < 0.3:
            return
        self._last_refresh = now
        if not self._asked_storage:
            # primeira vez: pede permissao de armazenamento ANTES de listar
            # (sem ela o Android nao deixa ler/gravar em Documents/)
            self._asked_storage = True
            try:
                perms.request(["storage"])
            except Exception:
                pass
        try:
            entries = luaproject.list_project_entries()
            root = luaproject.projects_root()
        except Exception as ex:
            entries, root = [], ""
            self.flash("Não consegui ler os projetos: %s" % ex, theme.STOP)
        self.count_label.text = "SEUS PROJETOS  ·  %d" % len(entries)
        self.path_label.text = _short_path(root)
        self.grid.clear_widgets()
        self._empty = not entries
        if not entries:
            self.grid.cols = 1
            empty = self._empty_state()
            self.grid.add_widget(empty)
            theme.fade_in(empty, delay=0.05, duration=0.3)
            return
        self.grid.cols = self._cols()
        for i, e in enumerate(entries):
            self.grid.add_widget(self._make_card(e, i))

    def _empty_state(self):
        box = BoxLayout(orientation="vertical", size_hint_y=None, height=250,
                        spacing=10, padding=(20, 30, 20, 10))
        row = BoxLayout(size_hint_y=None, height=72)
        row.add_widget(Widget())
        row.add_widget(IconTile({"glyph": "🎮", "color": "#3A3B45"},
                                size_px=72, radius=20))
        row.add_widget(Widget())
        box.add_widget(row)
        box.add_widget(_lbl("Nenhum projeto ainda", 18, theme.TEXT, bold=True,
                            halign="center", size_hint_y=None, height=30))
        box.add_widget(_wrap_label(
            "Toque em “Criar projeto” pra começar.\n"
            "Cada projeto vira uma pasta em Documents/<nome>.",
            13, theme.TEXT_DIM, halign="center"))
        return box

    def _make_card(self, e, index):
        wrap = FloatLayout(size_hint_y=None, height=CARD_H)
        card = BoxLayout(orientation="vertical", padding=12, spacing=10,
                         size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        theme.paint_rounded(card, theme.SURFACE, radius=16, border=theme.BORDER)

        top = BoxLayout(size_hint_y=None, height=60, spacing=12)
        top.add_widget(IconTile(e["icon"], name=e["name"], base_path=e["path"],
                                size_px=60))
        info = BoxLayout(orientation="vertical", spacing=2)
        info.add_widget(_lbl(e["name"], 17, theme.TEXT, bold=True, shorten=True))
        n = e["scripts"]
        meta = "%d script%s" % (n, "s" if n != 1 else "")
        date = _fmt_date(e["modified"])
        if date:
            meta += "  ·  %s" % date
        if e["legacy"]:
            meta += "  ·  pasta antiga"
        info.add_widget(_lbl(meta, 12, theme.TEXT_DIM, shorten=True))
        info.add_widget(_lbl(_short_path(e["path"], 44), 11,
                             (0.42, 0.42, 0.47, 1), shorten=True))
        top.add_widget(info)
        card.add_widget(top)

        bottom = BoxLayout(size_hint_y=None, height=40, spacing=8)
        path = e["path"]
        play_btn = theme.IconButton(icon="play", text="Play", bg_color=theme.PLAY, bold=True, radius=12)
        play_btn.bind(on_release=lambda *_: self._open(path, True))
        bottom.add_widget(play_btn)
        edit_btn = theme.IconButton(icon="edit", text="Editar", bg_color=theme.SURFACE_2, radius=12)
        edit_btn.bind(on_release=lambda *_: self._open(path, False))
        bottom.add_widget(edit_btn)
        del_btn = theme.IconButton(icon="delete", text="", bg_color=theme.SURFACE_2, radius=12, size_hint_x=None, width=48)
        del_btn.bind(on_release=lambda *_: self._confirm_delete(e))
        bottom.add_widget(del_btn)
        card.add_widget(bottom)
        wrap.add_widget(card)

        # entrada em cascata: cada card sobe um pouquinho + fade
        card.opacity = 0
        card.pos_hint = {"x": 0, "y": -0.12}

        def go(*_a, c=card):
            Animation(opacity=1, pos_hint={"x": 0, "y": 0}, d=0.30,
                      t="out_cubic").start(c)
        Clock.schedule_once(go, min(index, 8) * 0.05)
        return wrap

    # ------------------------------------------------------------- acoes
    def _open(self, path, play):
        try:
            proj = luaproject.load_project(path)
        except Exception as ex:
            self.flash("Erro ao abrir o projeto: %s" % ex, theme.STOP)
            return
        self.app.open_project(proj, play=play)

    def _confirm_delete(self, e):
        box = BoxLayout(orientation="vertical", padding=14, spacing=12)
        popup = theme.styled_popup("Apagar projeto?", box, size_hint=(0.88, 0.55))
        box.add_widget(_wrap_label(
            "A pasta inteira de “%s” será apagada do dispositivo:\n%s\n\n"
            "Isso não pode ser desfeito." % (e["name"], e["path"]),
            13, theme.TEXT))
        row = BoxLayout(size_hint_y=None, height=48, spacing=8)

        def do_delete(*_a):
            popup.dismiss()
            ok = luaproject.delete_project(e["path"])
            if ok:
                self.flash("Projeto “%s” apagado" % e["name"], theme.TEXT_DIM)
            else:
                self.flash("Não consegui apagar “%s”" % e["name"], theme.STOP)
            self.refresh(force=True)

        cancel = theme.RoundButton(text="Cancelar", bg_color=theme.SURFACE_2,
                                   radius=12)
        cancel.bind(on_release=lambda *_a: popup.dismiss())
        delete = theme.IconButton(icon="delete", text="Apagar", bg_color=theme.STOP,
                                   radius=12)
        delete.bind(on_release=do_delete)
        row.add_widget(cancel)
        row.add_widget(delete)
        box.add_widget(row)
        popup.open()

    # -------------------------------------------------- criar projeto
    def open_create_dialog(self):
        state = {"glyph": "@initial", "color": luaproject.ICON_COLORS[0],
                 "image": None}

        body = BoxLayout(orientation="vertical", spacing=10, padding=(2, 4))
        popup = theme.styled_popup("Novo projeto", body, size_hint=(0.94, 0.94))

        scroll = ScrollView(bar_width=3)
        form = BoxLayout(orientation="vertical", spacing=12, size_hint_y=None,
                         padding=(6, 4, 6, 8))
        form.bind(minimum_height=lambda w, v: setattr(w, "height", v))
        scroll.add_widget(form)
        body.add_widget(scroll)

        # ---- preview + nome ----
        top = BoxLayout(size_hint_y=None, height=78, spacing=14)
        preview = IconTile(None, name="", size_px=76, radius=20)
        top.add_widget(preview)
        namecol = BoxLayout(orientation="vertical", spacing=4)
        namecol.add_widget(_lbl("NOME DO PROJETO", 11, theme.TEXT_DIM, bold=True,
                                size_hint_y=None, height=18))
        name_in = theme.make_input(hint_text="ex: my_game", size_hint_y=None,
                                   height=50)
        namecol.add_widget(name_in)
        top.add_widget(namecol)
        form.add_widget(top)

        # ---- icone (glifos) ----
        form.add_widget(_lbl("ÍCONE", 11, theme.TEXT_DIM, bold=True,
                             size_hint_y=None, height=18))
        glyph_grid = GridLayout(cols=6, spacing=6, size_hint_y=None,
                                row_default_height=46, row_force_default=True)
        options = ["@initial"] + list(luaproject.ICON_GLYPHS)
        rows = (len(options) + 5) // 6
        glyph_grid.height = rows * 46 + (rows - 1) * 6
        glyph_btns = {}
        for g in options:
            if g == "@initial":
                b = theme.RoundButton(text="Aa", font_size=16, radius=12, bg_color=theme.SURFACE_2)
            else:
                b = theme.IconButton(icon=ICON_IMAGE_MAP.get(g, "image"), text="",
                                     icon_size=24, radius=12, bg_color=theme.SURFACE_2)
            b.bind(on_release=lambda _b, v=g: pick_glyph(v))
            glyph_btns[g] = b
            glyph_grid.add_widget(b)
        form.add_widget(glyph_grid)

        # ---- cor ----
        form.add_widget(_lbl("COR", 11, theme.TEXT_DIM, bold=True,
                             size_hint_y=None, height=18))
        color_row = BoxLayout(size_hint_y=None, height=34, spacing=8)
        color_btns = {}
        for c in luaproject.ICON_COLORS:
            sw = theme.RoundButton(text="", size_hint=(None, None), size=(32, 32),
                                   bg_color=list(theme.hex_to_rgba(c)),
                                   radius=8)
            sw.bind(on_release=lambda _b, v=c: pick_color(v))
            color_btns[c] = sw
            color_row.add_widget(sw)
        color_row.add_widget(Widget())
        form.add_widget(color_row)

        # ---- imagem do dispositivo ----
        img_row = BoxLayout(size_hint_y=None, height=46, spacing=8)
        img_btn = theme.IconButton(icon="image", text="Usar uma imagem do dispositivo...",
                                    font_size=14, radius=12,
                                    bg_color=theme.SURFACE_2)
        img_clear = theme.IconButton(icon="close", text="", font_size=14, radius=12,
                                      size_hint_x=None, width=46,
                                      bg_color=theme.SURFACE_2)
        img_clear.opacity = 0
        img_clear.disabled = True
        img_row.add_widget(img_btn)
        img_row.add_widget(img_clear)
        form.add_widget(img_row)

        # ---- caminho + erro ----
        path_label = _wrap_label("", 12, theme.TEXT_DIM)
        form.add_widget(path_label)
        err_label = _wrap_label("", 13, theme.STOP)
        form.add_widget(err_label)

        # ---- rodape ----
        bottom = BoxLayout(size_hint_y=None, height=52, spacing=8)
        cancel = theme.RoundButton(text="Cancelar", size_hint_x=None, width=112,
                                   bg_color=theme.SURFACE_2, radius=12)
        create = theme.RoundButton(text="OK  Criar projeto", bg_color=theme.ACCENT,
                                   radius=12, bold=True)
        bottom.add_widget(cancel)
        bottom.add_widget(create)
        body.add_widget(bottom)

        # ------------------------------------------------- comportamento
        def icon_dict():
            return {"glyph": state["glyph"], "color": state["color"]}

        def refresh_preview():
            preview.set_icon(icon_dict(), name=name_in.text,
                             image_abs=state["image"])

        def show_error(msg):
            err_label.text = msg
            if msg:
                # tremidinha no campo de nome (feedback de erro leve)
                x0 = name_in.x
                Animation.cancel_all(name_in, "x")
                (Animation(x=x0 - 8, d=0.04) + Animation(x=x0 + 8, d=0.06)
                 + Animation(x=x0, d=0.04)).start(name_in)

        def refresh_path(*_a):
            name = name_in.text.strip()
            folder = luaproject.folder_name(name) if name else "<nome>"
            path_label.text = "Pasta %s" % os.path.join(luaproject.projects_root(),
                                                       folder)

        def on_name(*_a):
            refresh_preview()
            refresh_path()
            if err_label.text:
                show_error("")

        def pick_glyph(g):
            state["glyph"] = g
            state["image"] = None
            update_image_ui()
            for k, b in glyph_btns.items():
                b.bg_color = list(theme.ACCENT if k == g else theme.SURFACE_2)
            refresh_preview()

        def pick_color(c):
            state["color"] = c
            for k, b in color_btns.items():
                Animation.cancel_all(b, "radius")
                Animation(radius=16 if k == c else 8, d=0.14,
                          t="out_quad").start(b)
            refresh_preview()

        def update_image_ui():
            if state["image"]:
                img_btn.text = "Imagem: %s" % os.path.basename(state["image"])
                img_btn.bg_color = list(theme.ACCENT)
                img_clear.disabled = False
                Animation(opacity=1, d=0.15).start(img_clear)
                for b in glyph_btns.values():
                    b.bg_color = list(theme.SURFACE_2)
            else:
                img_btn.text = "Imagem Usar uma imagem do dispositivo…"
                img_btn.bg_color = list(theme.SURFACE_2)
                img_clear.disabled = True
                img_clear.opacity = 0

        def choose_image(*_a):
            def on_pick(path):
                state["image"] = path
                update_image_ui()
                refresh_preview()
            filebrowser.open_picker(
                title="Escolher imagem do ícone", mode="file",
                start=perms.storage_dir(),
                extensions=list(luaproject.ICON_IMAGE_EXTS),
                shortcuts=filebrowser.default_shortcuts(),
                on_select=on_pick)

        def clear_image(*_a):
            state["image"] = None
            update_image_ui()
            pick_glyph(state["glyph"])

        def do_create(*_a):
            name = name_in.text.strip()
            if not name:
                show_error("Dê um nome ao projeto.")
                return
            if luaproject.project_exists(name):
                show_error("Já existe uma pasta “%s” em Documents. "
                           "Escolha outro nome." % luaproject.folder_name(name))
                return
            try:
                perms.request(["storage"])
            except Exception:
                pass
            try:
                proj = luaproject.create_project(
                    name, icon=icon_dict(), image_src=state["image"])
            except FileExistsError:
                show_error("Já existe uma pasta com esse nome em Documents.")
                return
            except Exception as ex:
                show_error("Não consegui criar a pasta do projeto: %s\n"
                           "Confira a permissão de armazenamento (botão Permissao)." % ex)
                return
            popup.dismiss()
            self.app.open_project(proj)

        name_in.bind(text=on_name)
        name_in.bind(on_text_validate=do_create)
        img_btn.bind(on_release=choose_image)
        img_clear.bind(on_release=clear_image)
        cancel.bind(on_release=lambda *_a: popup.dismiss())
        create.bind(on_release=lambda *_a: self._safe(do_create))

        pick_glyph("@initial")
        pick_color(state["color"])
        refresh_path()
        popup.open()
        Clock.schedule_once(lambda *_a: setattr(name_in, "focus", True), 0.25)

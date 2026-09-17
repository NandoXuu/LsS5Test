# -*- coding: utf-8 -*-
"""LuaStudio Mobile - IDE Kivy (Android / Pydroid 3).

Agora com sistema de PROJETOS: cada projeto e uma pasta em
`LuaStudio/Projects/<nome>/` que pode conter varios scripts/modulos Lua.
Os scripts de um mesmo projeto rodam todos no mesmo runtime, entao podem
se comunicar entre si (`require("outro_script")`) e editar os mesmos
objetos da cena. Um projeto pode ser exportado como um pacote `.Lsp`
(um zip com o manifesto + scripts + assets), que tanto pode ser reaberto
aqui pra editar quanto rodado em tela cheia pelo LuaStudio Player.
"""

import os

from kivy.app import App
from kivy.clock import Clock
try:
    from kivy.core.window import Window
except Exception:  # pragma: no cover - ambiente sem janela
    Window = None
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput

from .editor import EditorPane
from .stage import Stage
from .runtime import Runtime
from . import permissions as perms
from . import project as luaproject
from . import filebrowser
from . import theme

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(BASE, "examples")


class Console(ScrollView):
    def __init__(self, **kw):
        ScrollView.__init__(self, **kw)
        # IMPORTANTE: NAO chamar canvas.before.clear() aqui. O ScrollView
        # ja usa canvas.before/canvas.after pra montar o "StencilPush /
        # StencilUse ... StencilUnUse / StencilPop" que recorta o
        # conteudo na hora de rolar. Limpar canvas.before apaga o
        # StencilPush mas deixa o StencilPop la no canvas.after, e o Kivy
        # fecha o app com "Too much StencilPop (stack underflow)" no
        # primeiro desenho. A gente so ADICIONA nosso retangulo de fundo,
        # sem tocar no que o ScrollView ja desenhou.
        with self.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(*theme.CONSOLE_BG)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *a: setattr(self._bg, "pos", self.pos),
                 size=lambda *a: setattr(self._bg, "size", self.size))
        self.label = Label(text="", size_hint_y=None, halign="left", valign="top",
                           font_size=13, color=theme.TEXT, markup=False,
                           padding=(10, 8))
        self.label.bind(texture_size=lambda w, v: setattr(w, "height", v[1]))
        self.label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self.add_widget(self.label)
        self.lines = []

    def write(self, msg):
        self.lines.append(str(msg))
        if len(self.lines) > 250:
            self.lines = self.lines[-250:]
        self.label.text = "\n".join(self.lines)
        Clock.schedule_once(lambda *a: setattr(self, "scroll_y", 0), 0)

    def clear(self):
        self.lines = []
        self.label.text = ""


def _popup(title, content, size_hint=(0.9, 0.8)):
    return Popup(title=title, content=content, size_hint=size_hint,
                title_color=theme.TEXT, title_size=17,
                separator_color=theme.ACCENT, background_color=theme.BG)


def _write_crash_log(text):
    """Grava o erro num arquivo texto, pra dar pra ler mesmo se o console
    do Pydroid nao mostrar nada. Tenta a pasta de armazenamento primeiro,
    cai pra pasta do proprio app se nao der."""
    candidates = []
    try:
        candidates.append(os.path.join(perms.storage_dir(), "LuaStudio_erro.txt"))
    except Exception:
        pass
    candidates.append(os.path.join(BASE, "LuaStudio_erro.txt"))
    for path in candidates:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return path
        except Exception:
            continue
    return None


class LuaStudioApp(App):
    title = "LuaStudio Mobile"

    def build(self):
        # Window pode ser None se o provider SDL2 falhar; nao deve derrubar o app.
        if Window is not None:
            try:
                Window.clearcolor = theme.BG
            except Exception:
                pass
        try:
            return self._build_ui()
        except Exception:
            import traceback
            tb = traceback.format_exc()
            print("[LuaStudio] ERRO AO ABRIR:\n%s" % tb)
            saved_at = _write_crash_log(tb)
            return self._crash_screen(tb, saved_at)

    def _crash_screen(self, tb, saved_at):
        """Tela de erro visivel dentro do proprio app - assim, mesmo se o
        console do Pydroid nao mostrar nada, da pra ver (e copiar) o erro."""
        box = BoxLayout(orientation="vertical", padding=14, spacing=8)
        box.add_widget(Label(text="[erro] O LuaStudio nao conseguiu abrir", font_size=18,
                             color=(1, 0.4, 0.4, 1), size_hint_y=None, height=36))
        if saved_at:
            box.add_widget(Label(text="Erro salvo em:\n%s" % saved_at, font_size=13,
                                 color=theme.TEXT_DIM, size_hint_y=None, height=48))
        scroll = ScrollView()
        err_label = Label(text=tb, font_size=12, color=theme.TEXT, halign="left",
                          valign="top", size_hint_y=None, markup=False)
        err_label.bind(texture_size=lambda w, v: setattr(w, "height", v[1]))
        err_label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        scroll.add_widget(err_label)
        box.add_widget(scroll)
        return box

    def _build_ui(self):
        root = BoxLayout(orientation="vertical")
        self.console = Console(size_hint_y=0.22)
        self.runtime = Runtime(log=self.log, base_dir=BASE)
        self.stage = Stage(self.runtime)
        self.editor = EditorPane()
        self.view = "editor"

        # ---- projeto atual (comeca com um projeto novo em memoria) ----
        # Se o sistema de projetos falhar por qualquer motivo (ex.: sem
        # permissao de armazenamento ainda), cai pra um projeto simples
        # totalmente em memoria - o app continua abrindo normalmente.
        self._project_error = None
        try:
            self.project = luaproject.create_project("Meu Projeto")
        except Exception:
            import traceback
            self._project_error = traceback.format_exc()
            self.project = luaproject.Project(name="Meu Projeto")
            self.project.scripts["main.lua"] = luaproject.DEFAULT_MAIN
            self.project.entry = "main.lua"
        self.current_script = self.project.entry
        self.editor.text = self.project.scripts[self.current_script]

        root.add_widget(self._header())
        root.add_widget(self._toolbar())
        root.add_widget(self._toolbar2())
        root.add_widget(self._script_bar())

        self.body = BoxLayout()
        self.body.add_widget(self.editor)
        root.add_widget(self._panel(self.body, self._panel_title_text(), "panel_title"))
        root.add_widget(self._panel(self.console, "CONSOLE"))
        root.add_widget(self._status_bar())

        Clock.schedule_interval(self._tick, 1.0 / 45.0)
        self._set_status("pronto", theme.TEXT_DIM)
        self.log("LuaStudio Mobile pronto. Android=%s" % perms.ANDROID)
        self.log("[projeto] \"%s\" (%d script%s) - toque em 📁 pra criar/abrir projetos"
                 % (self.project.name, len(self.project.scripts),
                    "s" if len(self.project.scripts) != 1 else ""))
        if self._project_error:
            self.log("[aviso] sistema de projetos com problema, modo simples ativado:\n%s"
                     % self._project_error)
        return root

    # ------------------------------------------------------------ toolbar
    def _bar(self, height=58):
        bar = BoxLayout(size_hint_y=None, height=height, spacing=6, padding=(8, 7))
        with bar.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(*theme.SURFACE)
            bg = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(pos=lambda *a: setattr(bg, "pos", bar.pos),
                size=lambda *a: setattr(bg, "size", bar.size))
        return bar

    def _divider(self):
        """Uma linha vertical fina pra separar grupos de botoes na
        toolbar - o mesmo truque visual que Unity/Godot usam pra
        agrupar acoes relacionadas."""
        from kivy.graphics import Color, Rectangle
        from kivy.uix.widget import Widget
        w = Widget(size_hint_x=None, width=1)
        with w.canvas:
            Color(*theme.BORDER)
            rect = Rectangle(pos=w.pos, size=w.size)
        w.bind(pos=lambda *a: setattr(rect, "pos", w.pos),
              size=lambda *a: setattr(rect, "size", w.size))
        return w

    def _panel(self, widget, title, title_attr=None):
        """Envolve um widget num 'painel dockable' com titulo, no estilo
        Godot/Unity: uma faixa fininha com o nome do painel em cima do
        conteudo, e uma borda sutil em volta."""
        wrap = BoxLayout(orientation="vertical")
        with wrap.canvas.before:
            from kivy.graphics import Color, Rectangle, Line
            Color(*theme.BORDER)
            border = Rectangle(pos=wrap.pos, size=wrap.size)
        wrap.bind(pos=lambda *a: setattr(border, "pos", wrap.pos),
                 size=lambda *a: setattr(border, "size", wrap.size))
        head = BoxLayout(size_hint_y=None, height=26, padding=(10, 0))
        with head.canvas.before:
            Color(*theme.SURFACE_2)
            hbg = Rectangle(pos=head.pos, size=head.size)
        head.bind(pos=lambda *a: setattr(hbg, "pos", head.pos),
                 size=lambda *a: setattr(hbg, "size", head.size))
        label = Label(text=title, font_size=11, color=theme.TEXT_DIM,
                      halign="left", valign="middle", bold=True)
        label.bind(size=lambda w, v: setattr(w, "text_size", v))
        head.add_widget(label)
        if title_attr:
            setattr(self, title_attr, label)
        wrap.add_widget(head)
        inner = BoxLayout(padding=(1, 1, 1, 1))
        inner.add_widget(widget)
        wrap.add_widget(inner)
        return wrap

    def _panel_title_text(self):
        return "📝  CÓDIGO — %s" % self.current_script

    def _btn(self, bar, text, cb, color=theme.SURFACE_2, width=None):
        def safe_cb(*_a):
            try:
                cb()
            except Exception as ex:
                import traceback
                self.log("[erro] %s" % ex)
                self.log(traceback.format_exc())
        kw = dict(text=text, font_size=14, bg_color=color, radius=10)
        if width:
            kw["size_hint_x"] = None
            kw["width"] = width
        b = theme.RoundButton(**kw)
        b.bind(on_release=safe_cb)
        bar.add_widget(b)
        return b

    def _toolbar(self):
        bar = self._bar(height=60)
        self._btn(bar, "▶   PLAY", self.run_code, theme.PLAY)
        self._btn(bar, "■", self.stop_code, theme.STOP, width=52)
        bar.add_widget(self._divider())
        self.view_btn = self._btn(bar, "🎮  Palco", self.toggle_view, theme.ACCENT)
        bar.add_widget(self._divider())
        self._btn(bar, "📁  Projetos", self.open_project_manager)
        return bar

    def _toolbar2(self):
        bar = self._bar(height=50)
        self._btn(bar, "💾  Salvar", self.save_project)
        self._btn(bar, "📦  Exportar", self.export_lsp, theme.WARN)
        bar.add_widget(self._divider())
        self._btn(bar, "📂  Exemplos", self.open_examples)
        self._btn(bar, "🖼  Assets", self.open_import_assets)
        self._btn(bar, "🔐  Perms", self.ask_perms)
        bar.add_widget(self._divider())
        self._btn(bar, "🧹", self.console.clear, width=44)
        return bar

    def _header(self):
        """Faixa fina no topo com o nome do app - da uma cara de "janela
        de editor de verdade" em vez de so uma pilha de botoes."""
        from kivy.graphics import Color, Rectangle
        bar = BoxLayout(size_hint_y=None, height=34, padding=(12, 0))
        with bar.canvas.before:
            Color(*theme.BG)
            bg = Rectangle(pos=bar.pos, size=bar.size)
            Color(*theme.ACCENT)
            underline = Rectangle(pos=(bar.x, bar.y), size=(bar.width, 2))
        def _sync(*_a):
            bg.pos, bg.size = bar.pos, bar.size
            underline.pos, underline.size = (bar.x, bar.y), (bar.width, 2)
        bar.bind(pos=_sync, size=_sync)
        title = Label(text="⚙  LuaStudio", font_size=15, bold=True,
                     color=theme.TEXT, halign="left", valign="middle",
                     size_hint_x=0.5)
        title.bind(size=lambda w, v: setattr(w, "text_size", v))
        bar.add_widget(title)
        self.header_project_label = Label(text=self.project.name, font_size=12,
                                          color=theme.TEXT_DIM, halign="right",
                                          valign="middle")
        self.header_project_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        bar.add_widget(self.header_project_label)
        return bar

    def _status_bar(self):
        """Barra de status no rodape (igual Godot/Unity): um pontinho
        colorido + texto de estado a esquerda, e o painel ativo a
        direita."""
        from kivy.graphics import Color, Ellipse, Rectangle
        bar = BoxLayout(size_hint_y=None, height=26, padding=(10, 0), spacing=6)
        with bar.canvas.before:
            Color(*theme.SURFACE)
            bg = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(pos=lambda *a: setattr(bg, "pos", bar.pos),
                size=lambda *a: setattr(bg, "size", bar.size))

        dot_holder = BoxLayout(size_hint_x=None, width=14)
        with dot_holder.canvas:
            self._status_dot_color = Color(*theme.TEXT_DIM)
            self._status_dot = Ellipse(pos=(0, 0), size=(9, 9))
        def _sync_dot(*_a):
            cx = dot_holder.x + dot_holder.width / 2 - 4.5
            cy = dot_holder.y + dot_holder.height / 2 - 4.5
            self._status_dot.pos = (cx, cy)
        dot_holder.bind(pos=_sync_dot, size=_sync_dot)
        bar.add_widget(dot_holder)

        self.status_label = Label(text="pronto", font_size=11, color=theme.TEXT_DIM,
                                  halign="left", valign="middle", size_hint_x=0.7)
        self.status_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        bar.add_widget(self.status_label)

        self.status_view_label = Label(text="Código", font_size=11, color=theme.TEXT_DIM,
                                       halign="right", valign="middle")
        self.status_view_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        bar.add_widget(self.status_view_label)
        return bar

    def _set_status(self, text, color=theme.TEXT_DIM):
        self.status_label.text = text
        self._status_dot_color.rgba = color
        self.status_view_label.text = "Palco" if self.view == "stage" else "Código"

    def _script_bar(self):
        bar = self._bar(height=44)
        self.project_label = Label(text=self._project_label_text(), font_size=13,
                                   color=theme.TEXT_DIM, halign="left", valign="middle",
                                   size_hint_x=0.55)
        self.project_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        bar.add_widget(self.project_label)
        self.script_btn = theme.RoundButton(text=self._script_btn_text(), font_size=14,
                                            bg_color=theme.SURFACE_2, radius=10,
                                            size_hint_x=0.45)

        def safe_open_scripts(*_a):
            try:
                self.open_script_manager()
            except Exception as ex:
                import traceback
                self.log("[erro] %s" % ex)
                self.log(traceback.format_exc())
        self.script_btn.bind(on_release=safe_open_scripts)
        bar.add_widget(self.script_btn)
        return bar

    def _project_label_text(self):
        return "Projeto: %s" % self.project.name

    def _script_btn_text(self):
        star = "⭐ " if self.current_script == self.project.entry else ""
        return "📄 %s%s ▾" % (star, self.current_script)

    def _refresh_project_bar(self):
        self.project_label.text = self._project_label_text()
        self.script_btn.text = self._script_btn_text()
        if hasattr(self, "header_project_label"):
            self.header_project_label.text = self.project.name
        if hasattr(self, "panel_title"):
            self.panel_title.text = self._panel_title_text()

    # -------------------------------------------------------------- acoes
    def log(self, msg):
        try:
            self.console.write(msg)
        except Exception:
            print(msg)

    def _sync_editor_to_script(self):
        """Guarda o texto atual do editor no script selecionado, antes de
        trocar de script, salvar, rodar ou exportar."""
        if self.project and self.current_script:
            self.project.scripts[self.current_script] = self.editor.text

    def _select_script(self, name):
        self._sync_editor_to_script()
        self.current_script = name
        self.editor.text = self.project.scripts.get(name, "")
        self.editor.clear_error_line()
        self._refresh_project_bar()

    def run_code(self):
        self._sync_editor_to_script()
        self.console.clear()
        # limpa o outline do erro anterior - se der erro de novo (mesma
        # linha ou outra), ele volta a aparecer logo abaixo.
        self.editor.clear_error_line()
        self._set_status("executando...", theme.WARN)
        ok = self.runtime.run_project(self.project.scripts, self.project.entry)
        n = len(self.project.scripts)
        if ok:
            self.show_stage()
            self.stage.redraw()
            self._set_status("rodando", theme.PLAY)
            self.log("[ok] projeto executado (%d script%s)" % (n, "s" if n != 1 else ""))
            return
        # falhou: acha a linha do erro (se o erro foi no script que esta
        # aberto agora) e poe o outline vermelho nela, em vez de ir pro
        # palco vazio.
        err = getattr(self.runtime, "last_error", None)
        self._set_status("erro - veja a linha marcada", theme.STOP)
        if err and err.get("line") and err.get("chunk") in (self.current_script,
                                                             self.project.entry):
            self.editor.mark_error_line(err["line"])
            self.log("[falhou] linha %d marcada em vermelho - corrija e aperte Play de novo"
                     % err["line"])
        else:
            self.log("[falhou] veja o erro acima")
        self.show_editor()

    def stop_code(self):
        self.runtime.stop()
        self._set_status("parado", theme.TEXT_DIM)
        self.log("[parado]")

    def toggle_view(self):
        if self.view == "editor":
            self.show_stage()
        else:
            self.show_editor()

    def show_stage(self):
        if self.view != "stage":
            self.body.clear_widgets()
            self.body.add_widget(self.stage)
            self.view = "stage"
            self.view_btn.text = "📝  Código"
            self.stage.redraw()
        if hasattr(self, "panel_title"):
            self.panel_title.text = "🎮  PALCO"
        if hasattr(self, "status_view_label"):
            self.status_view_label.text = "Palco"

    def show_editor(self):
        if self.view != "editor":
            self.body.clear_widgets()
            self.body.add_widget(self.editor)
            self.view = "editor"
            self.view_btn.text = "🎮  Palco"
        if hasattr(self, "panel_title"):
            self.panel_title.text = self._panel_title_text()
        if hasattr(self, "status_view_label"):
            self.status_view_label.text = "Código"

    # ------------------------------------------------------------ projeto
    def save_project(self):
        self._sync_editor_to_script()
        try:
            perms.request(["storage"])
            path = luaproject.save_project(self.project)
            self.log("[salvo] projeto \"%s\" em %s" % (self.project.name, path))
        except Exception as ex:
            self.log("[erro ao salvar projeto] %s" % ex)

    def export_lsp(self):
        self._sync_editor_to_script()
        try:
            perms.request(["storage"])
            luaproject.save_project(self.project)
            dest = luaproject.export_lsp(self.project)
            self.log("[exportado] %s" % dest)
        except Exception as ex:
            self.log("[erro ao exportar .Lsp] %s" % ex)

    def _load_project(self, proj):
        self._sync_editor_to_script()
        self.project = proj
        self.current_script = proj.entry
        self.editor.text = proj.scripts.get(proj.entry, "")
        self.editor.clear_error_line()
        self._refresh_project_bar()
        self.show_editor()
        self.log("[projeto] \"%s\" aberto (%d scripts)" % (proj.name, len(proj.scripts)))

    def open_project_manager(self):
        box = BoxLayout(orientation="vertical", spacing=6, padding=10)
        popup = _popup("Projetos", box)

        top = BoxLayout(size_hint_y=None, height=50, spacing=6)
        name_in = TextInput(hint_text="nome do novo projeto", multiline=False,
                            background_color=theme.EDITOR_BG, foreground_color=theme.TEXT,
                            cursor_color=theme.CURSOR, padding=(10, 12))
        top.add_widget(name_in)

        def create_new(*_a):
            name = name_in.text.strip() or "Novo Projeto"
            proj = luaproject.create_project(name)
            popup.dismiss()
            self._load_project(proj)
        new_btn = theme.RoundButton(text="＋ Criar", size_hint_x=None, width=90,
                                    bg_color=theme.PLAY, radius=10)
        new_btn.bind(on_release=create_new)
        top.add_widget(new_btn)
        box.add_widget(top)

        import_btn = theme.RoundButton(text="📥  Importar .Lsp", size_hint_y=None,
                                       height=46, bg_color=theme.WARN, radius=12)
        import_btn.bind(on_release=lambda *a: (popup.dismiss(), self.open_import_lsp()))
        box.add_widget(import_btn)

        box.add_widget(Label(text="Projetos salvos", size_hint_y=None, height=28,
                             color=theme.TEXT_DIM, font_size=13))
        scroll = ScrollView()
        listing = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None,
                            padding=(0, 4))
        listing.bind(minimum_height=lambda w, v: setattr(w, "height", v))
        scroll.add_widget(listing)
        box.add_widget(scroll)

        projects = luaproject.list_projects()
        if not projects:
            listing.add_widget(Label(text="Nenhum projeto salvo ainda",
                                     color=theme.TEXT_DIM, size_hint_y=None, height=40))
        for folder, path, display in projects:
            row = BoxLayout(size_hint_y=None, height=48, spacing=6)
            b = theme.RoundButton(text=display, font_size=14, bg_color=theme.SURFACE_2,
                                  radius=10)

            def do_open(_b, p=path):
                try:
                    proj = luaproject.load_project(p)
                except Exception as ex:
                    self.log("[erro ao abrir projeto] %s" % ex)
                    return
                popup.dismiss()
                self._load_project(proj)
            b.bind(on_release=do_open)
            row.add_widget(b)

            def do_delete(_b, p=path, d=display):
                luaproject.delete_project(p)
                self.log("[apagado] projeto \"%s\"" % d)
                popup.dismiss()
                self.open_project_manager()
            db = theme.RoundButton(text="🗑", font_size=14, size_hint_x=None, width=48,
                                   bg_color=theme.STOP, radius=10)
            db.bind(on_release=do_delete)
            row.add_widget(db)
            listing.add_widget(row)
        popup.open()

    def open_import_lsp(self):
        box = BoxLayout(orientation="vertical", spacing=6, padding=10)
        popup = _popup("Importar .Lsp", box, size_hint=(0.9, 0.6))

        def do_import_from(f):
            try:
                proj = luaproject.import_lsp_as_project(f)
            except Exception as ex:
                self.log("[erro ao importar .Lsp] %s" % ex)
                return
            self._load_project(proj)

        browse_btn = theme.RoundButton(
            text="📂  Procurar em qualquer pasta...", size_hint_y=None,
            height=48, font_size=14, bg_color=theme.ACCENT, radius=12)

        def do_browse(*_a):
            popup.dismiss()
            filebrowser.open_picker(
                title="Escolher arquivo .Lsp", mode="file",
                start=perms.storage_dir(), extensions=[luaproject.LSP_EXT],
                shortcuts=filebrowser.default_shortcuts(project=self.project),
                on_select=do_import_from)
        browse_btn.bind(on_release=do_browse)
        box.add_widget(browse_btn)

        box.add_widget(Label(text="Sugestões (Armazenamento / Download)",
                             size_hint_y=None, height=26, font_size=12,
                             color=theme.TEXT_DIM))
        scroll = ScrollView()
        listing = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None,
                            padding=(0, 4))
        listing.bind(minimum_height=lambda w, v: setattr(w, "height", v))
        scroll.add_widget(listing)
        box.add_widget(scroll)

        files = luaproject.find_lsp_files()
        if not files:
            listing.add_widget(Label(text="Nenhum arquivo .Lsp encontrado nos\n"
                                          "lugares comuns - use \"Procurar\" acima",
                                     color=theme.TEXT_DIM, size_hint_y=None, height=44))
        for full in files:
            b = theme.RoundButton(text=os.path.basename(full), size_hint_y=None,
                                  height=50, font_size=14, bg_color=theme.SURFACE_2,
                                  radius=12)

            def do_import(_b, f=full):
                popup.dismiss()
                do_import_from(f)
            b.bind(on_release=do_import)
            listing.add_widget(b)
        popup.open()

    def open_import_assets(self):
        """Abre o navegador de arquivos livre pra copiar qualquer
        arquivo do dispositivo (imagem, som etc.) pra pasta
        'assets/' (Source/Assets) do projeto atual."""
        if not self.project:
            return
        if not self.project.path:
            luaproject.save_project(self.project)

        def do_copy(src):
            rel = luaproject.import_asset_file(self.project, src)
            if rel:
                self.log("[assets] \"%s\" importado -> %s" % (os.path.basename(src), rel))
            else:
                self.log("[erro] não foi possível importar \"%s\"" % src)

        filebrowser.open_picker(
            title="Importar arquivo pra Assets", mode="file",
            start=perms.storage_dir(),
            shortcuts=filebrowser.default_shortcuts(project=self.project),
            on_select=do_copy)

    # ------------------------------------------------------------ scripts
    def open_script_manager(self):
        self._sync_editor_to_script()
        box = BoxLayout(orientation="vertical", spacing=6, padding=10)
        popup = _popup("Scripts de \"%s\"" % self.project.name, box, size_hint=(0.9, 0.75))

        scroll = ScrollView()
        listing = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None,
                            padding=(0, 4))
        listing.bind(minimum_height=lambda w, v: setattr(w, "height", v))
        scroll.add_widget(listing)
        box.add_widget(scroll)

        for name in self.project.order():
            row = BoxLayout(size_hint_y=None, height=48, spacing=6)
            label = "⭐ %s" % name if name == self.project.entry else name
            b = theme.RoundButton(text=label, font_size=14,
                                  bg_color=(theme.ACCENT if name == self.current_script
                                            else theme.SURFACE_2), radius=10)

            def do_select(_b, n=name):
                popup.dismiss()
                self._select_script(n)
            b.bind(on_release=do_select)
            row.add_widget(b)

            def do_entry(_b, n=name):
                self.project.set_entry(n)
                popup.dismiss()
                self._refresh_project_bar()
                self.open_script_manager()
            eb = theme.RoundButton(text="⭐", font_size=14, size_hint_x=None, width=44,
                                   bg_color=theme.WARN, radius=10)
            eb.bind(on_release=do_entry)
            row.add_widget(eb)

            if len(self.project.scripts) > 1:
                def do_remove(_b, n=name):
                    self.project.remove_script(n)
                    if self.current_script == n:
                        self.current_script = self.project.entry
                        self.editor.text = self.project.scripts.get(self.current_script, "")
                    popup.dismiss()
                    self._refresh_project_bar()
                    self.open_script_manager()
                rb = theme.RoundButton(text="🗑", font_size=14, size_hint_x=None, width=44,
                                       bg_color=theme.STOP, radius=10)
                rb.bind(on_release=do_remove)
                row.add_widget(rb)
            listing.add_widget(row)

        bottom = BoxLayout(size_hint_y=None, height=50, spacing=6, padding=(0, 6, 0, 0))
        name_in = TextInput(hint_text="nome_do_script.lua", multiline=False,
                            background_color=theme.EDITOR_BG, foreground_color=theme.TEXT,
                            cursor_color=theme.CURSOR, padding=(10, 12))
        bottom.add_widget(name_in)

        def do_add(*_a):
            name = name_in.text.strip() or "script.lua"
            real = self.project.add_script(name, "-- %s\n" % name)
            popup.dismiss()
            self._select_script(real)
        add_btn = theme.RoundButton(text="＋ Novo", size_hint_x=None, width=90,
                                    bg_color=theme.PLAY, radius=10)
        add_btn.bind(on_release=do_add)
        bottom.add_widget(add_btn)
        box.add_widget(bottom)
        popup.open()

    def ask_perms(self):
        res = perms.request(["storage", "microphone", "vibrate"])
        for k, v in res.items():
            self.log("%s -> %s" % (k, "concedida" if v else "negada"))
        self.log("armazenamento: %s" % perms.storage_dir())

    def open_examples(self):
        box = BoxLayout(orientation="vertical", spacing=6, padding=10)
        popup = _popup("Exemplos", box, size_hint=(0.9, 0.7))
        names = sorted(os.listdir(EXAMPLES)) if os.path.isdir(EXAMPLES) else []
        for name in names:
            b = theme.RoundButton(text=name, size_hint_y=None, height=50,
                                  font_size=14, bg_color=theme.SURFACE_2, radius=12)
            def load(_b, n=name):
                with open(os.path.join(EXAMPLES, n)) as fh:
                    code = fh.read()
                self.project.scripts[self.current_script] = code
                self.editor.text = code
                self.show_editor()
                popup.dismiss()
                self.log("[carregado] %s -> %s" % (n, self.current_script))
            b.bind(on_release=load)
            box.add_widget(b)
        if not names:
            box.add_widget(Label(text="Nenhum exemplo encontrado", color=theme.TEXT_DIM))
        popup.open()

    def _tick(self, dt):
        if self.runtime.running:
            try:
                self.runtime.update(dt)
            except Exception as ex:  # noqa - nunca deixa o Clock morrer
                import traceback
                self.log("[erro no update] %s: %s" % (type(ex).__name__, ex))
                self.log(traceback.format_exc())
            if self.view == "stage":
                try:
                    self.stage.redraw()
                except Exception as ex:  # noqa
                    import traceback
                    self.log("[erro no desenho] %s: %s" % (type(ex).__name__, ex))
                    self.log(traceback.format_exc())


def main():
    if Window is None:
        print("[LuaStudio] Kivy nao conseguiu abrir uma janela.\n"
              "No Pydroid 3: use 'Play' neste main.py, nao importe pygame antes\n"
              "do Kivy e verifique se o Kivy foi instalado pelo Pip do Pydroid.")
        return
    LuaStudioApp().run()

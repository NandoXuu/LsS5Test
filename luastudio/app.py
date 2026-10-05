# -*- coding: utf-8 -*-
"""LuaStudio Mobile - IDE Kivy (Android / Pydroid 3).

Ao abrir, aparece a TELA INICIAL (criar / editar / dar play em projetos);
o editor so aparece ao abrir um projeto. Cada projeto e uma pasta em
`Documents/<nome>/` que pode conter varios scripts/modulos Lua.
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
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.metrics import dp

from .editor import EditorPane
from .stage import Stage
from . import uiguard
from . import playlaunch
from .runtime import Runtime
from . import permissions as perms
from . import project as luaproject
from . import apkexport
from . import filebrowser
from . import theme
from . import prefs
from . import screenfit
from . import plugins as pluginsys
from .home import HomeScreen

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(BASE, "examples")


def _kivy_version():
    try:
        import kivy
        return kivy.__version__
    except Exception:
        return "0.0.0"


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


class _OutputResizeHandle(Widget):
    """Alça fina entre o editor e o Output.
    Arrastar para cima aumenta o Output; para baixo diminui.
    """
    def __init__(self, panel, **kw):
        Widget.__init__(self, **kw)
        self.panel = panel
        self._drag_y = None
        from kivy.graphics import Color, Rectangle
        with self.canvas:
            Color(*theme.BORDER)
            self._line = Rectangle(pos=self.pos, size=self.size)
            Color(*theme.ACCENT)
            self._accent = Rectangle(pos=(self.x + self.width * 0.42, self.y),
                                     size=(self.width * 0.16, 2))
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_a):
        self._line.pos = self.pos
        self._line.size = self.size
        self._accent.pos = (self.x + self.width * 0.42,
                            self.y + max(0, (self.height - 2) / 2))
        self._accent.size = (self.width * 0.16, 2)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._drag_y = touch.y
            touch.grab(self)
            return True
        return Widget.on_touch_down(self, touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self and self._drag_y is not None:
            dy = touch.y - self._drag_y
            self._drag_y = touch.y
            self.panel.set_output_height(self.panel.height + dy)
            return True
        return Widget.on_touch_move(self, touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._drag_y = None
            return True
        return Widget.on_touch_up(self, touch)


class _OutputPanel(BoxLayout):
    """Output dock redimensionável e fechável, sem cobrir o editor."""
    def __init__(self, app, content, close_callback, **kw):
        BoxLayout.__init__(self, orientation="vertical",
                           size_hint_y=None, height=dp(180), **kw)
        self.app = app
        self.min_height = dp(76)
        self.max_height = dp(520)
        self.content = content

        with self.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(*theme.BORDER)
            self._border = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *_: setattr(self._border, "pos", self.pos),
                  size=lambda *_: setattr(self._border, "size", self.size))

        head = BoxLayout(size_hint_y=None, height=dp(30),
                         padding=(dp(10), dp(2), dp(6), dp(2)))
        with head.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(*theme.SURFACE)
            self._head_bg = Rectangle(pos=head.pos, size=head.size)
        head.bind(pos=lambda *_: setattr(self._head_bg, "pos", head.pos),
                  size=lambda *_: setattr(self._head_bg, "size", head.size))

        label = Label(text="OUTPUT", font_size=11, color=theme.TEXT_DIM,
                      halign="left", valign="middle", bold=True)
        label.bind(size=lambda w, v: setattr(w, "text_size", v))
        head.add_widget(label)

        clear_btn = theme.RoundButton(text="LIMPAR", font_size=10, radius=8,
                                      bg_color=theme.SURFACE_2,
                                      size_hint_x=None, width=dp(58))
        clear_btn.bind(on_release=lambda *_: content.clear())
        head.add_widget(clear_btn)

        close_btn = theme.IconButton(icon="close", text="", font_size=16, radius=8,
                                      bg_color=theme.SURFACE_2,
                                      size_hint_x=None, width=dp(34))
        close_btn.bind(on_release=lambda *_: close_callback())
        head.add_widget(close_btn)

        self.add_widget(head)
        self.add_widget(_OutputResizeHandle(self, size_hint_y=None,
                                            height=dp(8)))
        inner = BoxLayout(padding=(1, 1, 1, 1))
        inner.add_widget(content)
        self.add_widget(inner)

    def set_output_height(self, value):
        self.height = max(self.min_height, min(self.max_height, value))


def _popup(title, content, size_hint=(0.9, 0.8)):
    return theme.styled_popup(title, content, size_hint=size_hint)


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
        self.console = Console()
        self.runtime = Runtime(log=self.log, base_dir=BASE)
        self.stage = Stage(self.runtime)

        # ---- sistema de plugins ----
        # engine_context=self da a plugins Python acesso controlado a app
        # (self.plugin_manager.engine dentro do main.py de um plugin).
        # confirm_callback=None aqui porque a confirmacao de instalacao ja
        # acontece na propria UI (open_plugin_manager), antes de chamar
        # manager.install(); ativacoes automaticas no boot (plugins ja
        # instalados/habilitados por uma instalacao ja confirmada) nao
        # pedem confirmacao de novo.
        try:
            self.plugin_manager = pluginsys.PluginManager(
                plugins_dir=os.path.join(BASE, "plugins"),
                engine_base_dir=BASE,
                engine_version="7.0.0",
                kivy_version=_kivy_version(),
                engine_context=self,
            )
        except Exception:
            import traceback
            self.log("[plugins] falha ao iniciar o Plugin Manager:\n%s" % traceback.format_exc())
            self.plugin_manager = None
        # preview do Palco com a proporcao de tela do projeto (letterbox,
        # sem esticar) - o fullscreen de verdade so acontece rodando o
        # jogo (LuaStudio Player); aqui dentro do editor e so a moldura.
        self.stage_fit = screenfit.FitContainer(self.stage, bars_color=theme.BG)
        self.editor = EditorPane()
        self.view = "editor"
        # True enquanto a tela de jogo (Play) esta ativa
        self.playing = False
        self._play_ev = None

        # ---- nenhum projeto aberto ao iniciar ----
        # A engine abre na tela inicial (HomeScreen). O projeto so passa a
        # existir quando o usuario cria/abre um la (open_project).
        self.project = None
        self.current_script = None
        self._project_error = None
        self._plugin_project_open = False

        # ---- tela do editor (montada agora, mostrada so ao abrir projeto) ----
        editor_root = BoxLayout(orientation="vertical")
        self.editor_root = editor_root
        editor_root.add_widget(self._topbar())

        self.body = BoxLayout()
        self.body.add_widget(self.editor)
        editor_root.add_widget(self._panel(self.body, self._panel_title_text(), "panel_title"))
        self.output_panel = _OutputPanel(self, self.console,
                                          self._close_output_panel)
        editor_root.add_widget(self.output_panel)
        editor_root.add_widget(self._status_bar())

        # ---- telas: inicial (projetos) e editor, com transicao suave ----
        # sem animacao de deslizar: trocar de tela e instantaneo (o slide deixava
        # widgets/UI fora da tela quando a transicao travava ou era interrompida)
        self.sm = ScreenManager(transition=NoTransition())
        self.home = HomeScreen(self)
        editor_screen = Screen(name="editor")
        editor_screen.add_widget(editor_root)
        self.sm.add_widget(self.home)
        self.sm.add_widget(editor_screen)
        self.sm.add_widget(self._build_play_screen())

        self._ui_guard = uiguard.UIGuard(self, self.sm).install()
        self._autosave_sig = None
        Clock.schedule_interval(self._autosave, 15.0)

        Clock.schedule_interval(self._tick, 1.0 / 45.0)
        self._set_status("pronto", theme.TEXT_DIM)
        self.log("LuaStudio Mobile pronto. Android=%s" % perms.ANDROID)
        if Window is not None:
            try:
                Window.bind(on_keyboard=self._on_keyboard)
            except Exception:
                pass

        # carrega/ativa plugins ja instalados e dispara engine_start/
        # editor_ready depois que a UI terminou de montar (schedule_once
        # com timeout 0 garante que roda no proximo frame, com tudo ja
        # pronto - inclusive se um plugin reagir criando widgets).
        Clock.schedule_once(lambda *_a: self._boot_plugins(), 0)
        # garante a lista de projetos na primeira tela (o on_pre_enter da
        # tela inicial pode nao disparar pra tela que ja nasce ativa)
        Clock.schedule_once(lambda *_a: self.home.refresh(), 0.05)
        return self.sm

    def _boot_plugins(self):
        if not self.plugin_manager:
            return
        failures = self.plugin_manager.load_all_enabled()
        for exc in failures:
            self.log("[plugins] erro ao carregar plugin: %s" % exc)
        n = len(self.plugin_manager.list_installed())
        if n:
            self.log("[plugins] %d plugin%s instalado%s" % (n, "s" if n != 1 else "", "s" if n != 1 else ""))
        self.plugin_manager.events.emit("engine_start", app=self)
        self.plugin_manager.events.emit("editor_ready", app=self)

    # ------------------------------------------------------------ toolbar
    def _bar(self, height=58):
        bar = BoxLayout(size_hint_y=None, height=height, spacing=6, padding=(8, 7))
        with bar.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(*theme.SURFACE)
            bg = Rectangle(pos=bar.pos, size=bar.size)
            Color(*theme.BORDER)
            line = Rectangle(pos=bar.pos, size=(bar.width, 1))
        def _sync(*_a):
            bg.pos, bg.size = bar.pos, bar.size
            line.pos, line.size = bar.pos, (bar.width, 1)
        bar.bind(pos=_sync, size=_sync)
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

    def _panel(self, widget, title, title_attr=None, action=None):
        """Envolve um widget num 'painel dockable' com titulo, no estilo
        Godot/Unity: uma faixa fininha com o nome do painel em cima do
        conteudo, e uma borda sutil em volta."""
        wrap = BoxLayout(orientation="vertical")
        with wrap.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(*theme.BORDER)
            border = Rectangle(pos=wrap.pos, size=wrap.size)
        wrap.bind(pos=lambda *a: setattr(border, "pos", wrap.pos),
                 size=lambda *a: setattr(border, "size", wrap.size))
        head = BoxLayout(size_hint_y=None, height=30 if action else 26,
                         padding=(10, 2 if action else 0, 6, 2 if action else 0))
        with head.canvas.before:
            Color(*theme.SURFACE)
            hbg = Rectangle(pos=head.pos, size=head.size)
        head.bind(pos=lambda *a: setattr(hbg, "pos", head.pos),
                 size=lambda *a: setattr(hbg, "size", head.size))
        label = Label(text=title, font_size=11, color=theme.TEXT_DIM,
                      halign="left", valign="middle", bold=True)
        label.bind(size=lambda w, v: setattr(w, "text_size", v))
        head.add_widget(label)
        if action:
            act = theme.RoundButton(text=action[0], font_size=11, radius=8,
                                    size_hint_x=None, width=64,
                                    bg_color=theme.SURFACE_2)
            act.bind(on_release=lambda *_a: action[1]())
            head.add_widget(act)
        if title_attr:
            setattr(self, title_attr, label)
        wrap.add_widget(head)
        inner = BoxLayout(padding=(1, 1, 1, 1))
        inner.add_widget(widget)
        wrap.add_widget(inner)
        return wrap

    def _close_output_panel(self):
        if getattr(self, "output_panel", None) is not None:
            try:
                if self.output_panel.parent is self.editor_root:
                    self.editor_root.remove_widget(self.output_panel)
            except Exception:
                pass
        if getattr(self, "output_btn", None) is not None:
            self.output_btn.text = "OUTPUT"

    def _open_output_panel(self):
        panel = getattr(self, "output_panel", None)
        if panel is None or getattr(self, "editor_root", None) is None:
            return
        if panel.parent is None:
            # index 1 mantém o Output entre o editor e a barra de status.
            self.editor_root.add_widget(panel, index=1)
        if getattr(self, "output_btn", None) is not None:
            self.output_btn.text = "OUTPUT"

    def _panel_title_text(self):
        name = self.project.name if self.project else "—"
        return "%s / %s" % (name, self.current_script or "")

    def _btn(self, bar, text, cb, color=theme.SURFACE_2, width=None, icon=None):
        def safe_cb(*_a):
            try:
                cb()
            except Exception as ex:
                import traceback
                self.log("[erro] %s" % ex)
                self.log(traceback.format_exc())
        kw = dict(text=text, font_size=14, bg_color=color, radius=12)
        if width:
            kw["size_hint_x"] = None
            kw["width"] = width
        b = (theme.IconButton(icon=icon, **kw) if icon else theme.RoundButton(**kw))
        b.bind(on_release=safe_cb)
        bar.add_widget(b)
        return b

    def _topbar(self):
        bar = self._bar(height=54)
        self._btn(bar, "", lambda: self.go_home(), theme.SURFACE_2, width=46, icon="back")
        self.script_btn = theme.RoundButton(
            text=self._script_btn_text(), font_size=14, radius=12,
            bg_color=theme.SURFACE_2, shorten=True, shorten_from="right")
        self.script_btn.bind(
            size=lambda w, v: setattr(w, "text_size", (max(v[0] - 20, 0), None)))
        self.script_btn.bind(on_release=lambda *_a: self._safe(self.open_script_manager))
        bar.add_widget(self.script_btn)
        self._btn(bar, "", self.run_code, theme.PLAY, width=58, icon="play")
        self._btn(bar, "", self.stop_code, theme.STOP, width=46, icon="stop")
        self.view_btn = self._btn(bar, "", self.toggle_view, theme.SURFACE_2, width=46, icon="screen")
        self._btn(bar, "", lambda: self.open_settings(), theme.SURFACE_2, width=46, icon="settings")
        self.output_btn = self._btn(bar, "OUTPUT", self._toggle_output_panel,
                                    theme.SURFACE_2, width=82, icon="output")
        return bar

    def _toggle_output_panel(self):
        panel = getattr(self, "output_panel", None)
        if panel is not None and panel.parent is not None:
            self._close_output_panel()
        else:
            self._open_output_panel()

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

    def _script_btn_text(self):
        if not self.project or not self.current_script:
            return "SCRIPT"
        star = ""
        return "%s%s" % (star, self.current_script)

    def _refresh_project_bar(self):
        self.script_btn.text = self._script_btn_text()
        if hasattr(self, "panel_title") and self.view == "editor":
            self.panel_title.text = self._panel_title_text()

    # -------------------------------------------------------------- acoes
    def log(self, msg):
        try:
            self.console.write(msg)
        except Exception:
            print(msg)

    def _safe(self, fn, *a):
        """Roda fn(*a) sem deixar uma excecao derrubar o app - o erro vai
        pro console."""
        try:
            fn(*a)
        except Exception as ex:
            import traceback
            self.log("[erro] %s" % ex)
            self.log(traceback.format_exc())

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
        self.start_play()

    def run_in_stage(self):
        if not self.project:
            return
        self._sync_editor_to_script()
        self._release_text_focus()
        self.console.clear()
        # limpa o outline do erro anterior - se der erro de novo (mesma
        # linha ou outra), ele volta a aparecer logo abaixo.
        self.editor.clear_error_line()
        self.editor.clear_warning_lines()
        self._set_status("executando...", theme.WARN)
        if self.plugin_manager:
            self.plugin_manager.events.emit("before_run", project=self.project)
        ok = self.runtime.run_project(self.project.scripts, self.project.entry)
        self._mark_run_warnings()
        n = len(self.project.scripts)
        if ok:
            self.show_stage()
            self.stage.redraw()
            self._set_status("rodando", theme.PLAY)
            self.log("[ok] projeto executado (%d script%s)" % (n, "s" if n != 1 else ""))
            if self.plugin_manager:
                self.plugin_manager.events.emit("after_run", project=self.project, ok=True)
            return
        if self.plugin_manager:
            self.plugin_manager.events.emit("after_run", project=self.project, ok=False)
        self._report_run_error()

    def _mark_run_warnings(self):
        """Pinta de amarelo, na coluna de linhas, os avisos do ultimo run
        (so vale pro script de entrada, que e o que foi analisado)."""
        warnings = getattr(self.runtime, "last_warnings", []) or []
        if self.current_script == self.project.entry:
            self.editor.mark_warning_lines([w[0] for w in warnings])

    def _report_run_error(self):
        """Marca a linha do erro no editor (se o erro foi no script aberto)
        e mostra o editor, em vez do palco vazio."""
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
            self._release_text_focus()
            self.body.clear_widgets()
            self.stage_fit.set_from_config(self.project.screen)
            self.body.add_widget(self.stage_fit)
            self.view = "stage"
            self.view_btn.text = "📝"
            self.stage.redraw()
        if hasattr(self, "panel_title"):
            self.panel_title.text = "Palco PALCO"
        if hasattr(self, "status_view_label"):
            self.status_view_label.text = "Palco"

    def show_editor(self):
        if self.view != "editor":
            self.body.clear_widgets()
            self.body.add_widget(self.editor)
            self.view = "editor"
            self.view_btn.text = "🎮"
        if hasattr(self, "panel_title"):
            self.panel_title.text = self._panel_title_text()
        if hasattr(self, "status_view_label"):
            self.status_view_label.text = "Código"

    # ------------------------------------------------------------ projeto
    def save_project(self):
        if not self.project:
            return
        self._sync_editor_to_script()
        try:
            perms.request(["storage"])
            path = luaproject.save_project(self.project)
            self.log("[salvo] projeto \"%s\" em %s" % (self.project.name, path))
        except Exception as ex:
            self.log("[erro ao salvar projeto] %s" % ex)

    def export_lsp(self):
        if not self.project:
            return
        self._sync_editor_to_script()
        try:
            perms.request(["storage"])
            luaproject.save_project(self.project)
            dest = luaproject.export_lsp(self.project)
            self.log("[exportado] %s" % dest)
        except Exception as ex:
            self.log("[erro ao exportar .Lsp] %s" % ex)

    # ------------------------------------------------------------- tela
    def _settings_tab_tela(self, popup):
        """Popup pra configurar como o jogo vai rodar: fullscreen,
        proporcao de tela (16:9, 9:16, 4:3...), orientacao (paisagem/
        retrato/automatico) e modo de encaixe - tudo salvo no projeto e
        usado pelo LuaStudio Player (e pelo preview do Palco aqui do
        lado) pra NUNCA esticar/deformar o jogo."""
        cfg = dict(self.project.screen)
        box = BoxLayout(orientation="vertical", spacing=10, padding=(4, 6),
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))

        def _section(title):
            box.add_widget(Label(text=title, size_hint_y=None, height=26,
                                 font_size=13, color=theme.TEXT_DIM, bold=True))

        def _row_buttons(options, current, on_pick, labels=None):
            row = BoxLayout(size_hint_y=None, height=44, spacing=6)
            btns = {}

            def pick(value):
                for v, b in btns.items():
                    b.bg_color = list(theme.ACCENT if v == value else theme.SURFACE_2)
                on_pick(value)

            for opt in options:
                text = (labels or {}).get(opt, opt)
                b = theme.RoundButton(text=text, font_size=13, radius=10,
                                      bg_color=theme.ACCENT if opt == current else theme.SURFACE_2)
                b.bind(on_release=lambda _b, v=opt: pick(v))
                btns[opt] = b
                row.add_widget(b)
            box.add_widget(row)
            return btns

        _section("Fullscreen (tela cheia de verdade ao rodar o jogo)")

        def set_fullscreen(v):
            cfg["fullscreen"] = (v == "on")
        _row_buttons(["on", "off"], "on" if cfg.get("fullscreen", True) else "off",
                    set_fullscreen, labels={"on": "OK Ligado", "off": "Janela Janela"})

        _section("Proporcao de tela (aspect ratio)")

        def set_aspect(v):
            cfg["aspect"] = v
        _row_buttons(screenfit.ASPECT_ORDER, cfg.get("aspect", "16:9"), set_aspect)

        _section("Orientacao")

        def set_orientation(v):
            cfg["orientation"] = v
        _row_buttons(list(screenfit.ORIENTATIONS), cfg.get("orientation", "landscape"),
                    set_orientation, labels={"landscape": "Tela Paisagem",
                                             "portrait": "Mobile Retrato", "auto": "Atualizar Automatico"})

        _section("Encaixe (como o jogo cabe na tela, sem esticar)")

        def set_fit(v):
            cfg["fit"] = v
        _row_buttons(list(screenfit.FIT_MODES), cfg.get("fit", "letterbox"), set_fit,
                    labels={"letterbox": "Uniforme Uniforme", "pixel_perfect": "Pixel Pixel perfeito"})

        box.add_widget(Label(
            text="O jogo fica centralizado, do tamanho da proporcao escolhida, "
                 "com barras preenchendo o resto - nunca deformado.\n"
                 "\"Pixel perfeito\" arredonda a escala pro inteiro mais proximo "
                 "(melhor pra tilemaps/pixel art).",
            font_size=12, color=theme.TEXT_DIM, size_hint_y=None, height=64))

        bottom = BoxLayout(size_hint_y=None, height=50, spacing=6)

        def do_save(*_a):
            self.project.screen = cfg
            self.stage_fit.set_from_config(cfg)
            self.log("[tela] %s, %s, %s, fullscreen=%s" % (
                cfg.get("aspect"), cfg.get("orientation"), cfg.get("fit"), cfg.get("fullscreen")))
            popup.dismiss()
        save_btn = theme.RoundButton(text="OK Aplicar", bg_color=theme.PLAY, radius=12)
        save_btn.bind(on_release=do_save)
        cancel_btn = theme.RoundButton(text="Cancelar", size_hint_x=None, width=110,
                                       bg_color=theme.SURFACE_2, radius=12)
        cancel_btn.bind(on_release=lambda *a: popup.dismiss())
        bottom.add_widget(save_btn)
        bottom.add_widget(cancel_btn)
        scroll = ScrollView(do_scroll_x=False, bar_width=4)
        scroll.add_widget(box)
        wrapper = BoxLayout(orientation="vertical", spacing=6)
        wrapper.add_widget(scroll)
        wrapper.add_widget(bottom)
        return wrapper

    _APK_PERM_LABELS = {
        "internet": "Internet", "vibrate": "Vibração", "camera": "Câmera",
        "microphone": "Microfone", "location": "Localização",
        "storage": "Armazenamento", "notifications": "Notificações",
        "bluetooth": "Bluetooth",
    }
    _APK_FEATURE_LABELS = {
        "numpy": "numpy (pitch/HRTF)", "tts": "Voz (gTTS)",
        "pygame": "pygame (áudio)",
    }
    _APK_ARCH_LABELS = {
        "arm64-v8a": "arm64-v8a", "armeabi-v7a": "armeabi-v7a", "both": "Ambas",
    }

    def generate_apk_template(self):
        if not self.project:
            return None
        self._sync_editor_to_script()
        perms.request(["storage"])
        luaproject.save_project(self.project)
        folder, zip_path = apkexport.export_template(self.project, self.project.apk)
        self.log("[apk] modelo Buildozer gerado em %s" % folder)
        self.log("[apk] zip pra enviar ao Colab: %s" % zip_path)
        return folder, zip_path

    def _settings_tab_apk(self, popup):
        cfg = apkexport.normalize_config(self.project.apk, self.project)
        box = BoxLayout(orientation="vertical", spacing=8, padding=(4, 6),
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        inputs = {}
        state = {"arch": cfg["arch"]}
        perms_sel = list(cfg["permissions"])
        feats_sel = list(cfg["features"])
        opts_sel = ["wakelock"] if cfg["wakelock"] else []

        def field(key, label, hint="", input_filter=None):
            box.add_widget(self._section_label(label))
            ti = theme.make_input(text=str(cfg[key]), hint_text=hint,
                                  size_hint_y=None, height=50,
                                  input_filter=input_filter)
            inputs[key] = ti
            box.add_widget(ti)

        def toggles(title, keys, labels, chosen):
            box.add_widget(self._section_label(title))
            row = None
            for i, key in enumerate(keys):
                if i % 2 == 0:
                    row = BoxLayout(size_hint_y=None, height=44, spacing=6)
                    box.add_widget(row)
                b = theme.RoundButton(
                    text=labels[key], font_size=13, radius=10,
                    bg_color=theme.ACCENT if key in chosen else theme.SURFACE_2)

                def flip(btn, k=key):
                    if k in chosen:
                        chosen.remove(k)
                        btn.bg_color = list(theme.SURFACE_2)
                    else:
                        chosen.append(k)
                        btn.bg_color = list(theme.ACCENT)
                b.bind(on_release=flip)
                row.add_widget(b)
            if len(keys) % 2:
                row.add_widget(Widget())

        field("title", "Nome do app")
        field("package_domain", "Domínio do pacote", "org.luastudio")
        field("package_name", "Nome do pacote", "meujogo")
        field("version", "Versão", "1.0")
        field("api", "API alvo (android.api)", input_filter="int")
        field("minapi", "API mínima (android.minapi)", input_filter="int")
        field("ndk", "NDK", "25b")

        box.add_widget(self._section_label("Arquitetura"))
        arch_row = BoxLayout(size_hint_y=None, height=44, spacing=6)
        arch_btns = {}

        def pick_arch(value):
            state["arch"] = value
            for v, b in arch_btns.items():
                b.bg_color = list(theme.ACCENT if v == value else theme.SURFACE_2)
        for arch in apkexport.ARCH_CHOICES:
            b = theme.RoundButton(
                text=self._APK_ARCH_LABELS[arch], font_size=13, radius=10,
                bg_color=theme.ACCENT if arch == cfg["arch"] else theme.SURFACE_2)
            b.bind(on_release=lambda _b, v=arch: pick_arch(v))
            arch_btns[arch] = b
            arch_row.add_widget(b)
        box.add_widget(arch_row)

        toggles("Permissões", apkexport.PERMISSION_KEYS, self._APK_PERM_LABELS,
                perms_sel)
        toggles("Recursos opcionais", apkexport.FEATURE_KEYS,
                self._APK_FEATURE_LABELS, feats_sel)
        toggles("Opções", ("wakelock",), {"wakelock": "Tela sempre ligada"},
                opts_sel)
        field("extra_requirements", "Requisitos extras (separados por vírgula)",
              "pacote1, pacote2")

        box.add_widget(self._note_label(
            "Orientação e tela cheia seguem a aba Tela. O ícone usa a imagem "
            "do ícone do projeto, se houver.", theme.TEXT_DIM, 12))
        result = self._note_label("", theme.TEXT, 12)
        box.add_widget(result)

        def collect():
            raw = dict((k, ti.text) for k, ti in inputs.items())
            raw["arch"] = state["arch"]
            raw["permissions"] = list(perms_sel)
            raw["features"] = list(feats_sel)
            raw["wakelock"] = "wakelock" in opts_sel
            return apkexport.normalize_config(raw, self.project)

        def do_save(*_a):
            self.project.apk = collect()
            self._safe(self.save_project)
            result.text = "Configuração salva no projeto."

        def do_generate(*_a):
            self.project.apk = collect()
            try:
                folder, zip_path = self.generate_apk_template()
                result.text = "Modelo gerado:\n%s\n%s" % (folder, zip_path)
            except Exception as ex:
                self.log("[erro ao gerar modelo Buildozer] %s" % ex)
                result.text = "Erro: %s" % ex

        bottom = BoxLayout(size_hint_y=None, height=50, spacing=6)
        save_btn = theme.RoundButton(text="Salvar config", bg_color=theme.SURFACE_2,
                                     radius=12, size_hint_x=None, width=140)
        save_btn.bind(on_release=do_save)
        gen_btn = theme.RoundButton(text="Gerar modelo Buildozer",
                                    bg_color=theme.PLAY, radius=12)
        gen_btn.bind(on_release=do_generate)
        bottom.add_widget(save_btn)
        bottom.add_widget(gen_btn)

        scroll = ScrollView(do_scroll_x=False, bar_width=4)
        scroll.add_widget(box)
        wrapper = BoxLayout(orientation="vertical", spacing=6)
        wrapper.add_widget(scroll)
        wrapper.add_widget(bottom)
        return wrapper

    def _load_project(self, proj):
        self._sync_editor_to_script()
        self.project = proj
        # Source = pasta do projeto (Documents/<nome>/): e dali que saem os
        # assets (Source = "Assets/hero.png"), sons, fontes etc.
        self.runtime.set_base_dir(proj.path or BASE)
        self.current_script = proj.entry
        self.editor.text = proj.scripts.get(proj.entry, "")
        self.editor.clear_error_line()
        self.stage_fit.set_from_config(proj.screen)
        self.console.clear()
        self._refresh_project_bar()
        self.show_editor()
        self.log("[projeto] \"%s\" aberto (%d scripts) em %s"
                 % (proj.name, len(proj.scripts), proj.path))
        if self.plugin_manager:
            if self._plugin_project_open:
                self.plugin_manager.events.emit("project_close")
            self.plugin_manager.events.emit("project_open", project=proj)
            self._plugin_project_open = True

    # ------------------------------------------------------- navegacao
    def _goto(self, name, direction="left"):
        uiguard.goto(self.sm, name, direction)
        Clock.schedule_once(self._ui_guard.snap, 0)
        Clock.schedule_once(self._ui_guard.snap, 0.15)

    def _release_text_focus(self):
        try:
            self.editor.focus = False
        except Exception:
            pass
        try:
            from . import softkeyboard
            softkeyboard.hide_virtual()
            uiguard.lock_android_pan()
        except Exception:
            pass

    def _autosave(self, _dt=None):
        proj = self.project
        if not proj or not getattr(proj, "path", None):
            return
        if self.sm.current != "editor":
            return
        try:
            self._sync_editor_to_script()
            sig = hash(tuple(sorted(proj.scripts.items())))
            if sig == self._autosave_sig:
                return
            luaproject.save_project(proj)
            self._autosave_sig = sig
        except Exception as ex:
            self.log("[autosave] falhou: %s" % ex)

    def on_pause(self):
        self._autosave()
        return True

    def open_project(self, proj, play=False):
        """Abre `proj` (com transicao).
        - `play=False` (botao Editar): abre o EDITOR (codigo, scripts...).
        - `play=True`  (botao Play): roda o JOGO numa tela propria, em tela
          cheia, sem editor/console. Sair volta pra tela inicial."""
        self._load_project(proj)
        self._set_status("pronto", theme.TEXT_DIM)
        if play:
            self.start_play()
        else:
            self._goto("editor", "left")

    # ------------------------------------------------------ tela de jogo
    def _build_play_screen(self):
        """Tela do Play: fundo preto + o jogo (Stage) ocupando tudo. Dois
        botoezinhos translucidos no canto: ✕ sair e ✏ editar."""
        from kivy.graphics import Color, Rectangle
        screen = Screen(name="play")
        root = FloatLayout()
        with root.canvas.before:
            Color(0, 0, 0, 1)
            bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=lambda *a: setattr(bg, "pos", root.pos),
                  size=lambda *a: setattr(bg, "size", root.size))
        # o Stage (dentro do stage_fit) entra aqui quando o Play comeca
        self.play_holder = FloatLayout()
        root.add_widget(self.play_holder)

        bar = BoxLayout(size_hint=(None, None), size=(104, 40), spacing=8,
                        pos_hint={"right": 0.99, "top": 0.985}, opacity=0.5)
        edit_btn = theme.IconButton(icon="edit", text="", font_size=16, radius=12,
                                     bg_color=(0, 0, 0, 0.6))
        edit_btn.bind(on_release=lambda *_a: self._safe(self.exit_play, "editor"))
        exit_btn = theme.IconButton(icon="close", text="", font_size=16, radius=12,
                                     bg_color=(0, 0, 0, 0.6))
        exit_btn.bind(on_release=lambda *_a: self._safe(self.exit_play, "home"))
        bar.add_widget(edit_btn)
        bar.add_widget(exit_btn)
        root.add_widget(bar)
        screen.add_widget(root)
        return screen

    def start_play(self):
        """Play: empacota o projeto (codigo + assets + tela) num .Lsp temporario
        e abre no Player. No desktop e outro processo (player_main.py); no
        Android/Pydroid so cabe um app Kivy por vez, entao o Player ocupa a
        janela no lugar da interface do editor e devolve ela ao sair."""
        if not self.project or self.playing:
            return
        proc = getattr(self, "_play_proc", None)
        if proc is not None and proc.poll() is None:
            self.log("[aviso] o Player ja esta aberto")
            return
        self._sync_editor_to_script()
        self._release_text_focus()
        self.console.clear()
        self.editor.clear_error_line()
        self.editor.clear_warning_lines()
        err = playlaunch.precheck(self.project)
        if err:
            self._set_status("erro - veja a linha marcada", theme.STOP)
            self.log("[erro de sintaxe] %s: %s" % (err["chunk"], err["message"]))
            if err.get("line") and err["chunk"] == self.current_script:
                self.editor.mark_error_line(err["line"])
            self.show_editor()
            self._goto("editor", "left")
            return
        try:
            luaproject.save_project(self.project)
        except Exception as ex:
            self.log("[aviso] nao consegui salvar antes do Play: %s" % ex)
        self.runtime.stop()
        try:
            tmpdir, lsp = playlaunch.export_for_play(self.project)
        except Exception as ex:
            self.log("[erro ao empacotar o projeto] %s" % ex)
            self._set_status("erro ao empacotar", theme.STOP)
            return
        if self.plugin_manager:
            self.plugin_manager.events.emit("before_run", project=self.project)
        proc = playlaunch.spawn_player(lsp)
        if proc is not None:
            self._play_proc = proc
            self._play_tmp = tmpdir
            self._set_status("rodando no Player", theme.PLAY)
            self.log("[ok] Player aberto (%s)" % os.path.basename(lsp))
            Clock.schedule_interval(self._poll_player, 0.5)
            return
        self._play_tmp = tmpdir
        self._enter_player_takeover(lsp)

    def _poll_player(self, _dt):
        proc = getattr(self, "_play_proc", None)
        if proc is not None and proc.poll() is None:
            return True
        self._play_proc = None
        playlaunch.cleanup(getattr(self, "_play_tmp", None))
        self._play_tmp = None
        self._set_status("parado", theme.TEXT_DIM)
        return False

    def _enter_player_takeover(self, lsp):
        from .player_app import PlayerSession
        self.playing = True
        self._play_session = PlayerSession(
            autoload=lsp, on_exit=lambda: self._safe(self.exit_play, "editor"))
        if self.sm.parent is not None:
            Window.remove_widget(self.sm)
        Window.add_widget(self._play_session)
        self._play_session.attach()
        self._set_status("rodando no Player", theme.PLAY)
        self.log("[ok] jogo aberto no Player (%s)" % os.path.basename(lsp))

    def _leave_play_mode(self):
        """Fecha o Player (se estiver ocupando a janela) e devolve o editor."""
        sess = getattr(self, "_play_session", None)
        self.playing = False
        if sess is not None:
            self._play_session = None
            try:
                sess.detach()
            except Exception:
                pass
            if sess.parent is not None:
                Window.remove_widget(sess)
        if self.sm.parent is None:
            Window.add_widget(self.sm)
        try:
            self.runtime.stop()
        except Exception:
            pass
        screenfit.restore_screen_mode()
        playlaunch.cleanup(getattr(self, "_play_tmp", None))
        self._play_tmp = None
        try:
            self._release_text_focus()
            self._ui_guard.snap()
        except Exception:
            pass

    def exit_play(self, to="home"):
        """Sai do Play. `to="home"` volta pra tela inicial; `to="editor"`
        abre o projeto no editor."""
        self._leave_play_mode()
        if to == "editor":
            self.show_editor()
            self._set_status("parado", theme.TEXT_DIM)
            self._goto("editor", "right")
        else:
            self._close_to_home()

    def go_home(self):
        """Salva o projeto, para o jogo e volta pra tela inicial. Se o
        salvamento falhar, NAO sai (pra nao perder o que foi editado)."""
        if self.project:
            self._sync_editor_to_script()
            try:
                luaproject.save_project(self.project)
            except Exception as ex:
                self.log("[erro ao salvar - continuando no editor] %s" % ex)
                self._set_status("erro ao salvar", theme.STOP)
                return
        self._close_to_home()

    def _close_to_home(self):
        """Para o jogo, fecha o projeto (plugins) e mostra a tela inicial."""
        self.runtime.stop()
        self._set_status("parado", theme.TEXT_DIM)
        if self.plugin_manager and self._plugin_project_open:
            self.plugin_manager.events.emit("project_close")
            self._plugin_project_open = False
        self.home.refresh(force=True)
        self._goto("home", "right")

    def open_project_manager(self):
        """Compatibilidade: o antigo popup de projetos virou a tela
        inicial."""
        self.go_home()

    def _on_keyboard(self, _window, key, *_args):
        """Botao Voltar do Android (tecla 27): no editor volta pra tela de
        projetos; na tela inicial fecha o app."""
        if key != 27:
            return False
        if self.playing:
            return True
        try:
            if self.runtime.input.pad_recent():
                return True
        except Exception:
            pass
        if self.sm.current == "play":
            self._safe(self.exit_play)
            return True
        if self.sm.current == "editor":
            self._safe(self.go_home)
            return True
        if perms.ANDROID:
            self.stop()
            return True
        return False

    def open_import_lsp(self):
        box = BoxLayout(orientation="vertical", spacing=6, padding=10)
        popup = _popup("Importar .Lsp", box, size_hint=(0.9, 0.6))

        def do_import_from(f):
            try:
                proj = luaproject.import_lsp_as_project(f)
            except Exception as ex:
                self.log("[erro ao importar .Lsp] %s" % ex)
                self.home.flash("Erro ao importar .Lsp: %s" % ex, theme.STOP)
                return
            self.open_project(proj)

        browse_btn = theme.RoundButton(
            text="Pasta Procurar em qualquer pasta...", size_hint_y=None,
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
            title="Importar arquivo (Assets/Sound)", mode="file",
            start=perms.storage_dir(),
            shortcuts=filebrowser.default_shortcuts(project=self.project),
            on_select=do_copy)

    _SETTINGS_TABS = (
        ("projeto", "Pasta Projeto", True),
        ("tela", "Tela Tela", True),
        ("apk", "Android APK", True),
        ("editor", "Editor Editor", False),
        ("exemplos", "Pasta Exemplos", True),
        ("plugins", "Plugins Plugins", False),
        ("sistema", "Sistema Sistema", False),
    )

    def _note_label(self, text, color=theme.TEXT_DIM, size=12):
        lbl = Label(text=text, font_size=size, color=color, halign="left",
                    valign="top", size_hint_y=None)
        lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        lbl.bind(texture_size=lambda w, v: setattr(w, "height", v[1] + 6))
        return lbl

    def _section_label(self, text):
        lbl = Label(text=text, font_size=13, color=theme.TEXT_DIM, bold=True,
                    halign="left", valign="middle", size_hint_y=None, height=28)
        lbl.bind(size=lambda w, v: setattr(w, "text_size", v))
        return lbl

    def _action_btn(self, text, fn, popup=None, color=theme.SURFACE_2, height=50):
        b = theme.RoundButton(text=text, font_size=14, radius=12, bg_color=color,
                              size_hint_y=None, height=height)

        def go(*_a):
            if popup is not None:
                popup.dismiss()
            self._safe(fn)
        b.bind(on_release=go)
        return b

    def open_settings(self, tab="projeto"):
        root = BoxLayout(orientation="vertical", spacing=8, padding=(6, 4, 6, 6))
        popup = _popup("Configurações", root, size_hint=(0.96, 0.92))

        tabs_scroll = ScrollView(size_hint_y=None, height=46, do_scroll_y=False,
                                 bar_width=0)
        tabbar = BoxLayout(size_hint_x=None, spacing=6, padding=(0, 2))
        tabbar.bind(minimum_width=tabbar.setter("width"))
        tabs_scroll.add_widget(tabbar)
        root.add_widget(tabs_scroll)

        content = BoxLayout()
        root.add_widget(content)

        close = theme.RoundButton(text="Fechar", font_size=14, radius=12,
                                  bg_color=theme.SURFACE_2, size_hint_y=None, height=44)
        close.bind(on_release=lambda *_a: popup.dismiss())
        root.add_widget(close)

        buttons = {}
        needs_project = dict((k, n) for k, _t, n in self._SETTINGS_TABS)

        def select(key):
            for k, b in buttons.items():
                b.bg_color = list(theme.ACCENT if k == key else theme.SURFACE_2)
            content.clear_widgets()
            try:
                if needs_project[key] and not self.project:
                    view = self._note_label("Abra um projeto pra usar esta aba.",
                                            size=14)
                else:
                    view = getattr(self, "_settings_tab_%s" % key)(popup)
            except Exception as ex:
                import traceback
                self.log("[erro] aba %s: %s" % (key, ex))
                self.log(traceback.format_exc())
                view = self._note_label("Erro ao abrir esta aba - veja o console.",
                                        theme.STOP, 14)
            content.add_widget(view)
            theme.fade_in(content, duration=0.15)

        for key, title, _needs in self._SETTINGS_TABS:
            b = theme.RoundButton(text=title, font_size=14, radius=12,
                                  size_hint_x=None, width=138,
                                  bg_color=theme.SURFACE_2)
            b.bind(on_release=lambda _b, k=key: select(k))
            buttons[key] = b
            tabbar.add_widget(b)

        select(tab if tab in buttons else "projeto")
        popup.open()

    def _settings_tab_projeto(self, popup):
        box = BoxLayout(orientation="vertical", spacing=8, padding=(4, 6))
        proj = self.project
        box.add_widget(self._note_label(proj.name, theme.TEXT, 17))
        box.add_widget(self._note_label(
            "Entrada: %s\nScripts: %d\nPasta: %s" % (
                proj.entry, len(proj.scripts), proj.path or "(ainda não salvo)"),
            theme.TEXT_DIM, 12))
        box.add_widget(self._action_btn("Salvar Salvar projeto", self.save_project, popup))
        box.add_widget(self._action_btn("Lsp Exportar como .Lsp", self.export_lsp, popup))
        box.add_widget(self._action_btn("Imagem Importar arquivo (Assets/Sound)",
                                        self.open_import_assets, popup))
        box.add_widget(self._action_btn("Arquivo Gerenciar scripts",
                                        self.open_script_manager, popup))
        box.add_widget(Widget())
        return box

    def _settings_tab_editor(self, popup):
        box = BoxLayout(orientation="vertical", spacing=8, padding=(4, 6))

        box.add_widget(self._section_label("Tamanho da fonte"))
        row = BoxLayout(size_hint_y=None, height=50, spacing=8)
        size_lbl = Label(text=str(int(prefs.get("font_size") or 15)), font_size=18,
                         color=theme.TEXT)

        def change(delta):
            cur = int(prefs.get("font_size") or 15)
            new = max(10, min(28, cur + delta))
            self.editor.set_font_size(new)
            size_lbl.text = str(new)
        minus = theme.RoundButton(text="A-", font_size=16, radius=12,
                                  bg_color=theme.SURFACE_2, size_hint_x=None, width=90)
        plus = theme.RoundButton(text="A+", font_size=16, radius=12,
                                 bg_color=theme.SURFACE_2, size_hint_x=None, width=90)
        minus.bind(on_release=lambda *_a: change(-1))
        plus.bind(on_release=lambda *_a: change(+1))
        row.add_widget(minus)
        row.add_widget(size_lbl)
        row.add_widget(plus)
        box.add_widget(row)

        box.add_widget(self._section_label("Guias de indent coloridas"))
        grow = BoxLayout(size_hint_y=None, height=46, spacing=6)
        gbtns = {}

        def set_guides(on):
            self.editor.set_indent_guides(on)
            for v, b in gbtns.items():
                b.bg_color = list(theme.ACCENT if v == on else theme.SURFACE_2)
        cur_on = bool(prefs.get("indent_guides"))
        for val, label in ((True, "🌈  Ligadas"), (False, "Desligadas")):
            b = theme.RoundButton(text=label, font_size=13, radius=10,
                                  bg_color=theme.ACCENT if val == cur_on else theme.SURFACE_2)
            b.bind(on_release=lambda _b, v=val: set_guides(v))
            gbtns[val] = b
            grow.add_widget(b)
        box.add_widget(grow)
        box.add_widget(self._note_label(
            "Cada nível de indentação ganha uma cor (rosa, laranja, amarelo, "
            "verde, ciano, roxo) pra você enxergar onde cada bloco começa e termina."))

        box.add_widget(self._section_label("Tema do editor"))
        box.add_widget(self._note_label("Monokai (fundo #272822).", theme.TEXT, 13))
        box.add_widget(Widget())
        return box

    def _settings_tab_sistema(self, popup):
        box = BoxLayout(orientation="vertical", spacing=8, padding=(4, 6))
        box.add_widget(self._action_btn(
            "Permissoes Permissões (armazenamento, microfone, vibração)", self.ask_perms, popup))
        box.add_widget(self._action_btn("Limpar Limpar console", self.console.clear, popup))
        try:
            storage = perms.storage_dir()
        except Exception:
            storage = "?"
        box.add_widget(self._note_label(
            "Armazenamento: %s\nKivy %s  |  Android: %s" % (
                storage, _kivy_version(), "sim" if perms.ANDROID else "não")))
        box.add_widget(Widget())
        return box

    def open_screen_settings(self):
        self.open_settings("tela")

    def open_plugin_manager(self):
        self.open_settings("plugins")

    def open_examples(self):
        self.open_settings("exemplos")

    # ------------------------------------------------------------ plugins
    def _settings_tab_plugins(self, popup):
        """Popup de gerenciamento de plugins: lista os instalados (com
        botões pra ativar/desativar/remover) e permite instalar um novo
        pacote .lpkg/.zip a partir do armazenamento do dispositivo."""
        if not self.plugin_manager:
            return self._note_label("Sistema de plugins indisponível nesta sessão.")

        box = BoxLayout(orientation="vertical", spacing=6, padding=(4, 6))

        install_btn = theme.IconButton(icon="plugin", text="Instalar plugin (.lpkg / .zip)",
                                        size_hint_y=None, height=48,
                                        bg_color=theme.ACCENT, radius=12)
        box.add_widget(install_btn)

        box.add_widget(Label(text="Instalados", size_hint_y=None, height=24,
                             font_size=12, color=theme.TEXT_DIM))
        scroll = ScrollView()
        listing = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None,
                            padding=(0, 4))
        listing.bind(minimum_height=lambda w, v: setattr(w, "height", v))
        scroll.add_widget(listing)
        box.add_widget(scroll)

        def refresh_list():
            listing.clear_widgets()
            records = self.plugin_manager.list_installed()
            if not records:
                listing.add_widget(Label(
                    text="Nenhum plugin instalado ainda.", color=theme.TEXT_DIM,
                    size_hint_y=None, height=44))
                return
            for rec in records:
                row = BoxLayout(size_hint_y=None, height=64, spacing=6)
                status = "✅ ativo" if rec.enabled else "Desativado desativado"
                if rec.state == pluginsys.STATE_ERROR:
                    status = "Aviso: erro"
                info = Label(
                    text="%s\nv%s — %s" % (rec.name or rec.uuid, rec.version, status),
                    font_size=13, color=theme.TEXT, halign="left", valign="middle")
                info.bind(size=lambda w, v: setattr(w, "text_size", v))
                row.add_widget(info)

                toggle = theme.RoundButton(
                    text=("Desativar" if rec.enabled else "Ativar"),
                    size_hint_x=None, width=100, font_size=12,
                    bg_color=(theme.WARN if rec.enabled else theme.PLAY), radius=10)

                def do_toggle(_b, u=rec.uuid):
                    try:
                        if self.plugin_manager.get_state(u) == pluginsys.STATE_ENABLED:
                            self.plugin_manager.disable(u)
                            self.log("[plugins] desativado: %s" % u)
                        else:
                            self.plugin_manager.enable(u)
                            self.log("[plugins] ativado: %s" % u)
                    except pluginsys.PluginError as exc:
                        self.log("[plugins] %s" % exc)
                    refresh_list()
                toggle.bind(on_release=do_toggle)
                row.add_widget(toggle)

                remove = theme.IconButton(icon="delete", text="", size_hint_x=None, width=48,
                                           bg_color=theme.STOP, radius=10)

                def do_remove(_b, u=rec.uuid, name=rec.name):
                    try:
                        self.plugin_manager.uninstall(u)
                        self.log("[plugins] removido: %s" % name)
                    except pluginsys.PluginError as exc:
                        self.log("[plugins] %s" % exc)
                    refresh_list()
                remove.bind(on_release=do_remove)
                row.add_widget(remove)

                listing.add_widget(row)

        def do_install_confirmed(path, manifest):
            try:
                self.plugin_manager.install(path)
                self.log("[plugins] instalado: %s v%s" % (manifest.name, manifest.version))
            except pluginsys.PluginError as exc:
                self.log("[plugins] falha ao instalar: %s" % exc)
            refresh_list()

        def show_confirm(path, manifest):
            cbox = BoxLayout(orientation="vertical", spacing=8, padding=10)
            cpopup = _popup("Confirmar instalação", cbox, size_hint=(0.9, 0.55))
            objs = ", ".join(o.object_type for o in manifest.objects) or "nenhum"
            text = (
                "%s\nversão %s\nautor: %s\n\n%s\n\n"
                "Modifica: %s\n\n"
                "Este plugin poderá executar código Python/Lua e, se "
                "necessário, alterar arquivos internos da engine "
                "(de forma reversível). Instalar mesmo assim?"
            ) % (manifest.name, manifest.version, manifest.author or "?",
                 manifest.description or "", objs)
            lbl = Label(text=text, font_size=13, color=theme.TEXT, halign="left",
                       valign="top")
            lbl.bind(size=lambda w, v: setattr(w, "text_size", (v[0], None)))
            cbox.add_widget(lbl)
            actions = BoxLayout(size_hint_y=None, height=48, spacing=8)
            ok_btn = theme.RoundButton(text="OK Instalar", bg_color=theme.PLAY, radius=12)
            cancel_btn = theme.RoundButton(text="Cancelar", bg_color=theme.SURFACE_2, radius=12)

            def confirm(_b):
                cpopup.dismiss()
                do_install_confirmed(path, manifest)
            def cancel(_b):
                cpopup.dismiss()
                self.log("[plugins] instalação cancelada")
            ok_btn.bind(on_release=confirm)
            cancel_btn.bind(on_release=cancel)
            actions.add_widget(ok_btn)
            actions.add_widget(cancel_btn)
            cbox.add_widget(actions)
            cpopup.open()

        def do_pick_package(path):
            try:
                manifest = self.plugin_manager.inspect(path)
            except pluginsys.PluginError as exc:
                self.log("[plugins] pacote inválido: %s" % exc)
                return
            show_confirm(path, manifest)

        def do_install(_b):
            filebrowser.open_picker(
                title="Escolher plugin (.lpkg / .zip)", mode="file",
                start=perms.storage_dir(),
                extensions=[".lpkg", ".zip"],
                shortcuts=filebrowser.default_shortcuts(project=self.project),
                on_select=do_pick_package)
        install_btn.bind(on_release=do_install)

        refresh_list()
        return box

    # ------------------------------------------------------------ scripts
    def open_script_manager(self):
        if not self.project:
            return
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
            label = "%s" % name if name == self.project.entry else name
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
            eb = theme.IconButton(icon="star", text="", font_size=14, size_hint_x=None, width=44,
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
                rb = theme.IconButton(icon="delete", text="", font_size=14, size_hint_x=None, width=44,
                                       bg_color=theme.STOP, radius=10)
                rb.bind(on_release=do_remove)
                row.add_widget(rb)
            listing.add_widget(row)

        bottom = BoxLayout(size_hint_y=None, height=50, spacing=6, padding=(0, 6, 0, 0))
        name_in = theme.make_input(hint_text="nome_do_script.lua")
        bottom.add_widget(name_in)

        def do_add(*_a):
            name = name_in.text.strip() or "script.lua"
            real = self.project.add_script(name, "-- %s\n" % name)
            popup.dismiss()
            self._select_script(real)
        add_btn = theme.IconButton(icon="add", text="Novo", size_hint_x=None, width=90,
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

    def _settings_tab_exemplos(self, popup):
        box = BoxLayout(orientation="vertical", spacing=6, padding=(4, 6))
        box.add_widget(self._note_label(
            "Carrega o exemplo no script aberto (substitui o código atual)."))
        scroll = ScrollView(do_scroll_x=False, bar_width=4)
        listing = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None,
                            padding=(0, 4))
        listing.bind(minimum_height=listing.setter("height"))
        scroll.add_widget(listing)
        box.add_widget(scroll)
        names = sorted(os.listdir(EXAMPLES)) if os.path.isdir(EXAMPLES) else []

        def load(n):
            with open(os.path.join(EXAMPLES, n), encoding="utf-8") as fh:
                code = fh.read()
            self.project.scripts[self.current_script] = code
            self.editor.text = code
            self.show_editor()
            popup.dismiss()
            self.log("[carregado] %s -> %s" % (n, self.current_script))

        for name in names:
            b = theme.RoundButton(text=name, size_hint_y=None, height=50,
                                  font_size=14, bg_color=theme.SURFACE_2, radius=12)
            b.bind(on_release=lambda _b, n=name: self._safe(load, n))
            listing.add_widget(b)
        if not names:
            listing.add_widget(self._note_label("Nenhum exemplo encontrado."))
        return box

    def _tick(self, dt):
        if self.runtime.running:
            try:
                self.runtime.update(dt)
            except Exception as ex:  # noqa - nunca deixa o Clock morrer
                import traceback
                self.log("[erro no update] %s: %s" % (type(ex).__name__, ex))
                self.log(traceback.format_exc())
            if self.view == "stage" or self.playing:
                try:
                    self.stage.redraw()
                except Exception as ex:  # noqa
                    import traceback
                    self.log("[erro no desenho] %s: %s" % (type(ex).__name__, ex))
                    self.log(traceback.format_exc())

    def on_resume(self):
        try:
            uiguard.lock_android_pan()
            self._ui_guard.snap()
        except Exception:
            pass
        # o Android limpa o modo imersivo ao voltar do segundo plano:
        # reaplica se tem jogo rodando em tela cheia.
        if self.playing and self.project and self.project.screen.get("fullscreen", True):
            perms.hide_system_bars()
        return True


def main():
    if Window is None:
        print("[LuaStudio] Kivy nao conseguiu abrir uma janela.\n"
              "No Pydroid 3: use 'Play' neste main.py, nao importe pygame antes\n"
              "do Kivy e verifique se o Kivy foi instalado pelo Pip do Pydroid.")
        return
    LuaStudioApp().run()

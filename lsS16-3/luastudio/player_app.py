# -*- coding: utf-8 -*-
"""LuaStudio Player - abre um pacote `.Lsp` (gerado pelo LuaStudio) e roda
o jogo em tela cheia. Nao tem editor, nao tem palco de edicao: e so o
runtime + a tela do jogo, do jeito que o jogador final vai usar.
"""

import os
import shutil
import tempfile

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

from .runtime import Runtime
from .stage import Stage
from . import permissions as perms
from . import project as luaproject
from . import theme
from . import screenfit
from . import filebrowser
from . import uiguard
from . import splash as splashmod

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RoundButton(theme.RoundButton):
    pass


def _write_crash_log(text):
    candidates = []
    try:
        candidates.append(os.path.join(perms.storage_dir(), "LuaStudioPlayer_erro.txt"))
    except Exception:
        pass
    candidates.append(os.path.join(BASE, "LuaStudioPlayer_erro.txt"))
    for path in candidates:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return path
        except Exception:
            continue
    return None


class PlayerSession(FloatLayout):
    """Tela completa do Player (seletor de .Lsp + jogo rodando). E um widget
    comum: o PlayerApp (player_main.py) o usa como raiz, e o editor o
    coloca no lugar da propria interface quando voce da Play."""

    def __init__(self, autoload=None, on_exit=None, use_splash=True, **kw):
        FloatLayout.__init__(self, **kw)
        self.autoload = autoload
        self.on_exit = on_exit
        # False quando quem criou a sessao ja mostra a splash (o editor, no
        # Android) - evita duas splashes uma em cima da outra.
        self.use_splash = use_splash
        self._opening = False
        self._log_lines = []
        self._tick_ev = None
        self._attached = False
        self.root_box = BoxLayout(orientation="vertical", size_hint=(1, 1))
        self.add_widget(self.root_box)
        self.back_btn = RoundButton(text="Sair", size_hint=(None, None), size=(88, 40),
                                    pos_hint={"right": 0.99, "top": 0.985},
                                    bg_color=(0, 0, 0, 0.6), radius=12, opacity=0)
        self.back_btn.disabled = True
        self.back_btn.bind(on_release=lambda *a: self._safe(self._back_to_picker))
        self.add_widget(self.back_btn)
        self.runtime = None
        self.stage = None
        self.stage_fit = None
        self._tmpdir = None
        self.status = Label(text="")

    def attach(self):
        if self._attached:
            return
        self._attached = True
        self._tick_ev = Clock.schedule_interval(self._tick, 1.0 / 45.0)
        if Window is not None:
            try:
                Window.bind(on_keyboard=self._on_keyboard)
            except Exception:
                pass
        try:
            if self.autoload:
                self.open_lsp(self.autoload)
                # com splash, o jogo abre alguns frames depois (dentro dela);
                # a checagem de falha acontece la, em _finish_autoload.
                if not self._opening and self.runtime is None:
                    raise RuntimeError(self.status.text or "falha ao abrir o jogo")
            else:
                self._show_picker()
        except Exception:
            import traceback
            tb = traceback.format_exc()
            print("[LuaStudio Player] ERRO AO ABRIR:\n%s" % tb)
            saved_at = _write_crash_log(tb)
            self.root_box.clear_widgets()
            self.root_box.add_widget(self._crash_widget(tb, saved_at))

    def detach(self):
        if not self._attached:
            return
        self._attached = False
        if self._tick_ev is not None:
            self._tick_ev.cancel()
            self._tick_ev = None
        if Window is not None:
            try:
                Window.unbind(on_keyboard=self._on_keyboard)
            except Exception:
                pass
        self._teardown_game()

    def _exit(self):
        if self.on_exit is not None:
            self.on_exit()
            return
        app = App.get_running_app()
        if app is not None:
            app.stop()

    def _crash_widget(self, tb, saved_at):
        box = BoxLayout(orientation="vertical", padding=14, spacing=8)
        box.add_widget(Label(text="[erro] O LuaStudio Player nao conseguiu abrir",
                             font_size=16, color=(1, 0.4, 0.4, 1), size_hint_y=None,
                             height=40))
        if saved_at:
            box.add_widget(Label(text="Erro salvo em:\n%s" % saved_at, font_size=13,
                                 color=theme.TEXT_DIM, size_hint_y=None, height=48))
        err_label = Label(text=tb, font_size=12, color=theme.TEXT, halign="left",
                          valign="top")
        err_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        box.add_widget(err_label)
        return box

    def _safe(self, fn, *args):
        try:
            fn(*args)
        except Exception:
            import traceback
            tb = traceback.format_exc()
            print("[LuaStudio Player] erro: %s" % tb)
            saved_at = _write_crash_log(tb)
            self.root_box.clear_widgets()
            self.root_box.add_widget(self._crash_widget(tb, saved_at))

    # ------------------------------------------------------------ tela 1
    def _show_picker(self):
        """Tela de abertura: escolher qual .Lsp rodar."""
        self.root_box.clear_widgets()
        box = BoxLayout(orientation="vertical", spacing=10, padding=20)
        box.add_widget(Label(text="LuaStudio Player", font_size=26,
                             color=theme.TEXT, size_hint_y=None, height=50))
        box.add_widget(Label(text="Toque num jogo .Lsp pra abrir em tela cheia:",
                             font_size=14, color=theme.TEXT_DIM, size_hint_y=None,
                             height=30))

        scroll = ScrollView()
        listing = BoxLayout(orientation="vertical", spacing=8, size_hint_y=None,
                            padding=(0, 6))
        listing.bind(minimum_height=lambda w, v: setattr(w, "height", v))
        scroll.add_widget(listing)
        box.add_widget(scroll)

        files = luaproject.find_lsp_files()
        if not files:
            listing.add_widget(Label(
                text="Nenhum .Lsp encontrado em\n%s\n\n"
                     "Exporte um projeto no LuaStudio (botao Exportar .Lsp) e ele\n"
                     "vai aparecer aqui." % perms.storage_dir(),
                color=theme.TEXT_DIM, size_hint_y=None, height=140))
        for full in files:
            b = RoundButton(text=os.path.basename(full), size_hint_y=None, height=56,
                            font_size=15, bg_color=theme.SURFACE_2, radius=12)
            b.bind(on_release=lambda _b, f=full: self._safe(self.open_lsp, f))
            listing.add_widget(b)

        row = BoxLayout(size_hint_y=None, height=48, spacing=8)
        refresh = theme.IconButton(icon="refresh", text="Atualizar lista", bg_color=theme.SURFACE_2,
                              radius=12)
        refresh.bind(on_release=lambda *a: self._safe(self._show_picker))
        row.add_widget(refresh)

        browse = theme.IconButton(icon="folder", text="Procurar .Lsp...", bg_color=theme.ACCENT,
                             radius=12)
        browse.bind(on_release=lambda *a: self._safe(self._browse_lsp))
        row.add_widget(browse)
        box.add_widget(row)

        perm_btn = theme.IconButton(icon="lock", text="Permissão de armazenamento", size_hint_y=None,
                               height=44, bg_color=theme.WARN, radius=12)
        perm_btn.bind(on_release=lambda *a: self._safe(
            lambda: (perms.request(["storage"]), self._show_picker())))
        box.add_widget(perm_btn)

        self.status = Label(text="", color=theme.STOP, size_hint_y=None, height=30,
                            font_size=13)
        box.add_widget(self.status)
        self.root_box.add_widget(box)

    def _browse_lsp(self):
        """Navegador de arquivos livre pra achar um .Lsp em qualquer
        pasta do aparelho (nao so nas pastas padrao que _show_picker ja
        lista sozinho)."""
        filebrowser.open_picker(
            title="Escolher jogo (.Lsp)",
            mode="file",
            extensions=[luaproject.LSP_EXT],
            shortcuts=filebrowser.default_shortcuts(),
            on_select=lambda path: self._safe(self.open_lsp, path),
        )

    # ------------------------------------------------------------ tela 2
    def _teardown_game(self):
        if self.runtime is not None:
            try:
                self.runtime.stop()
            except Exception:
                pass
        if self.stage is not None:
            try:
                self.stage.release_input()
            except Exception:
                pass
        self.stage = None
        self.stage_fit = None
        self.runtime = None
        self.root_box.clear_widgets()
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
        self._set_back_visible(False)

    def _set_back_visible(self, on):
        self.back_btn.disabled = not on
        self.back_btn.opacity = 0.5 if on else 0

    def _on_keyboard(self, _window, key, *_args):
        if key != 27:
            return False
        if self.runtime is not None:
            try:
                if self.runtime.input.pad_recent():
                    return True
            except Exception:
                pass
            self._safe(self._back_to_picker)
            return True
        return False

    def open_lsp(self, lsp_path):
        try:
            manifest, scripts = luaproject.read_lsp(lsp_path)
        except Exception as ex:
            self.status.text = "[erro ao ler .Lsp] %s" % ex
            return
        if not scripts:
            self.status.text = "[erro] esse .Lsp nao tem nenhum script"
            return

        screen_cfg = manifest.get("screen") or screenfit.default_screen_config()
        # splash do jogo: some se o projeto desligou ("Splash" nas configuracoes
        # de Tela do LuaStudio) ou se quem abriu a sessao ja mostra uma.
        if self.use_splash and screen_cfg.get("splash", True):
            if self._opening:
                return
            self._opening = True

            def work():
                try:
                    self._start_game(lsp_path, manifest, scripts, screen_cfg)
                    if self.runtime is None and self.autoload:
                        self._show_crash(RuntimeError(
                            self.status.text or "falha ao abrir o jogo"))
                except Exception as ex:
                    self._show_crash(ex)

            def finished():
                self._opening = False

            splashmod.show(work=work, bg=(0, 0, 0, 1), on_done=finished,
                           fallback_text="LuaStudio")
            return
        self._start_game(lsp_path, manifest, scripts, screen_cfg)

    def _show_crash(self, ex):
        import traceback
        tb = "".join(traceback.format_exception(type(ex), ex, ex.__traceback__))
        print("[LuaStudio Player] ERRO AO ABRIR:\n%s" % tb)
        saved_at = _write_crash_log(tb)
        self.root_box.clear_widgets()
        self.root_box.add_widget(self._crash_widget(tb, saved_at))

    def _start_game(self, lsp_path, manifest, scripts, screen_cfg):
        self._teardown_game()

        # extrai o conteudo do .Lsp (Assets/, Sound/, pastas extras...) pra
        # uma pasta temporaria: ela e o Source do jogo, entao
        # Source = "Assets/hero.png" acha o arquivo de dentro do pacote.
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        self._tmpdir = tempfile.mkdtemp(prefix="luastudio_play_")
        try:
            luaproject.extract_lsp(lsp_path, self._tmpdir)
        except Exception:
            pass

        self.runtime = Runtime(log=self._log, base_dir=self._tmpdir)
        self.stage = Stage(self.runtime)

        # tela: fullscreen de verdade + orientacao travada (configurados
        # no LuaStudio, botao "Tela") + proporcao fixa sem esticar.
        screenfit.apply_screen_mode(screen_cfg)
        vw, vh = screenfit.resolve_virtual_size(
            screen_cfg.get("aspect"), screen_cfg.get("orientation"), base=720.0)
        self.stage_fit = screenfit.FitContainer(
            self.stage, virtual_w=vw, virtual_h=vh, bars_color=(0, 0, 0, 1),
            pixel_perfect=(screen_cfg.get("fit") == "pixel_perfect"))

        self.root_box.clear_widgets()
        self.root_box.add_widget(self.stage_fit)
        self._set_back_visible(True)

        entry = manifest.get("entry") or sorted(scripts.keys())[0]
        ok = self.runtime.run_project(scripts, entry)
        self.stage.redraw()
        if not ok:
            self._show_error_overlay(manifest.get("name") or os.path.basename(lsp_path))

    def _show_error_overlay(self, name):
        box = BoxLayout(orientation="vertical", spacing=8, padding=16)
        box.add_widget(Label(text="'%s' falhou ao iniciar." % name,
                             color=theme.STOP, font_size=16, size_hint_y=None, height=36))
        lines = [l for l in self._log_lines if l.strip()][-14:]
        scroll = ScrollView()
        log = Label(text="\n".join(lines) or "(sem detalhes no log)", font_size=12,
                    color=theme.TEXT, halign="left", valign="top", size_hint_y=None,
                    markup=False)
        log.bind(texture_size=lambda w, v: setattr(w, "height", v[1]))
        log.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        scroll.add_widget(log)
        box.add_widget(scroll)
        back = RoundButton(text="Voltar", size_hint_y=None, height=48,
                           bg_color=theme.SURFACE_2, radius=12)
        back.bind(on_release=lambda *a: self._back_to_picker())
        box.add_widget(back)
        self.root_box.clear_widgets()
        self.root_box.add_widget(box)
        self._set_back_visible(False)

    def _back_to_picker(self):
        if self.autoload or self.on_exit is not None:
            self._exit()
            return
        self._teardown_game()
        try:
            perms.set_orientation("sensor")
        except Exception:
            pass
        self._show_picker()

    def _log(self, msg):
        print("[LuaStudio Player] %s" % msg)
        self._log_lines.append(str(msg))
        if len(self._log_lines) > 200:
            del self._log_lines[:100]

    def _tick(self, dt):
        if self.runtime is not None and self.runtime.running:
            try:
                self.runtime.update(dt)
            except Exception as ex:  # noqa - nunca deixa o Clock morrer
                import traceback
                self._log("[erro no update] %s: %s" % (type(ex).__name__, ex))
                self._log(traceback.format_exc())
            if self.stage is not None:
                try:
                    self.stage.redraw()
                except Exception as ex:  # noqa
                    import traceback
                    self._log("[erro no desenho] %s: %s" % (type(ex).__name__, ex))
                    self._log(traceback.format_exc())

class PlayerApp(App):
    title = "LuaStudio Player"

    def __init__(self, autoload=None, **kw):
        App.__init__(self, **kw)
        self.autoload = autoload
        self.session = None

    def build(self):
        if Window is not None:
            try:
                Window.clearcolor = (0, 0, 0, 1)
            except Exception:
                pass
            try:
                Window.fullscreen = "auto"
            except Exception:
                pass
        perms.hide_system_bars()
        self.session = PlayerSession(autoload=self.autoload)
        self.session.attach()
        self._ui_guard = uiguard.UIGuard(self).install()
        return self.session

    def on_stop(self):
        if self.session is not None:
            self.session.detach()

    def on_resume(self):
        uiguard.lock_android_pan()
        perms.hide_system_bars()
        return True


def main(autoload=None):
    if Window is None:
        print("[LuaStudio Player] Kivy nao conseguiu abrir uma janela.\n"
              "No Pydroid 3: use 'Play' neste main.py.")
        return
    PlayerApp(autoload=autoload).run()

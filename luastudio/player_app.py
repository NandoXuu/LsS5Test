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
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from .runtime import Runtime
from .stage import Stage
from . import permissions as perms
from . import project as luaproject
from . import theme

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


class PlayerApp(App):
    title = "LuaStudio Player"

    def build(self):
        if Window is not None:
            try:
                Window.clearcolor = (0, 0, 0, 1)
            except Exception:
                pass
            try:
                # tela cheia de verdade: sem chrome de janela (desktop) e
                # sem status bar / barra de navegacao (Android, modo
                # imersivo). So o jogo, nada de UI por cima.
                Window.fullscreen = "auto"
            except Exception:
                pass
        perms.hide_system_bars()
        self.root_box = BoxLayout(orientation="vertical")
        self.runtime = None
        self.stage = None
        self._tmpdir = None
        Clock.schedule_interval(self._tick, 1.0 / 45.0)
        try:
            self._show_picker()
        except Exception:
            import traceback
            tb = traceback.format_exc()
            print("[LuaStudio Player] ERRO AO ABRIR:\n%s" % tb)
            saved_at = _write_crash_log(tb)
            self.root_box.clear_widgets()
            self.root_box.add_widget(self._crash_widget(tb, saved_at))
        return self.root_box

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

        refresh = RoundButton(text="🔄  Atualizar lista", size_hint_y=None, height=48,
                              bg_color=theme.ACCENT, radius=12)
        refresh.bind(on_release=lambda *a: self._safe(self._show_picker))
        box.add_widget(refresh)

        perm_btn = RoundButton(text="🔐  Permissao de armazenamento", size_hint_y=None,
                               height=44, bg_color=theme.WARN, radius=12)
        perm_btn.bind(on_release=lambda *a: self._safe(
            lambda: (perms.request(["storage"]), self._show_picker())))
        box.add_widget(perm_btn)

        self.status = Label(text="", color=theme.STOP, size_hint_y=None, height=30,
                            font_size=13)
        box.add_widget(self.status)
        self.root_box.add_widget(box)

    # ------------------------------------------------------------ tela 2
    def open_lsp(self, lsp_path):
        try:
            manifest, scripts = luaproject.read_lsp(lsp_path)
        except Exception as ex:
            self.status.text = "[erro ao ler .Lsp] %s" % ex
            return
        if not scripts:
            self.status.text = "[erro] esse .Lsp nao tem nenhum script"
            return

        # extrai os assets (imagens/sons) pra uma pasta temporaria, pra
        # scripts que usam fs.read/create.image Source="arquivo.png" etc
        # acharem os arquivos relativos ao projeto.
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        self._tmpdir = tempfile.mkdtemp(prefix="luastudio_play_")
        try:
            luaproject.extract_lsp_assets(lsp_path, self._tmpdir)
        except Exception:
            pass

        self.runtime = Runtime(log=self._log, base_dir=self._tmpdir)
        self.stage = Stage(self.runtime)
        self.root_box.clear_widgets()
        self.root_box.add_widget(self.stage)

        entry = manifest.get("entry") or sorted(scripts.keys())[0]
        ok = self.runtime.run_project(scripts, entry)
        self.stage.redraw()
        if not ok:
            self._show_error_overlay(manifest.get("name") or os.path.basename(lsp_path))

    def _show_error_overlay(self, name):
        box = BoxLayout(orientation="vertical", spacing=8, padding=16,
                        size_hint=(1, None), height=120)
        box.add_widget(Label(text="[LuaStudio Player] '%s' falhou ao iniciar.\n"
                                   "Veja o log abaixo. Toque em Voltar." % name,
                             color=theme.STOP, font_size=14))
        back = RoundButton(text="↩  Voltar pra lista", size_hint_y=None, height=44,
                           bg_color=theme.SURFACE_2, radius=12)
        back.bind(on_release=lambda *a: self._back_to_picker())
        box.add_widget(back)
        self.root_box.add_widget(box)

    def _back_to_picker(self):
        if self.runtime is not None:
            self.runtime.stop()
        self.stage = None
        self.runtime = None
        self._show_picker()

    def _log(self, msg):
        print("[LuaStudio Player] %s" % msg)

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

    def on_stop(self):
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    def on_resume(self):
        # o Android limpa as flags de imersivo quando o app volta do
        # segundo plano - reaplica pra continuar em tela cheia.
        perms.hide_system_bars()
        return True


def main():
    if Window is None:
        print("[LuaStudio Player] Kivy nao conseguiu abrir uma janela.\n"
              "No Pydroid 3: use 'Play' neste main.py.")
        return
    PlayerApp().run()

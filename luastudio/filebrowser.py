# -*- coding: utf-8 -*-
"""Navegador de arquivos/pastas livre (estilo gerenciador de arquivos
basico), pra escolher qualquer pasta ou arquivo do dispositivo -
Android (Pydroid 3) ou desktop - sem ficar preso a uma pasta fixa tipo
`assets/`.

Uso basico:

    from . import filebrowser

    filebrowser.open_picker(
        title="Importar imagem",
        mode="file",                 # "file" ou "folder"
        start=alguma_pasta,          # onde abre (opcional)
        extensions=[".png", ".jpg"], # filtro de arquivos (opcional)
        shortcuts=filebrowser.default_shortcuts(project=meu_projeto),
        on_select=lambda caminho: ...,
    )

`start=None` abre no armazenamento do Android (ou pasta do usuario no
desktop). Dentro do navegador da pra subir/descer pasta por pasta,
pular pros atalhos (Armazenamento, Download, Raiz, pasta do projeto -
"Source" - e "Source/Assets") ou digitar um caminho direto (ex:
`/storage/emulated/0/assets` ou so `/` pra raiz do Android)."""

import os

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from . import permissions as perms
from . import theme


# ------------------------------------------------------------- atalhos
def default_shortcuts(project=None):
    """Lista padrao de atalhos (nome, caminho) pro topo do navegador.
    `project` (opcional) e um objeto Project com `.path`, pra incluir os
    atalhos "Source" (pasta do projeto) e "Source/Assets"."""
    out = []
    storage = perms.storage_dir()
    android_root = "/storage/emulated/0"
    if project is not None and getattr(project, "path", None):
        out.append(("📦 Source", project.path))
        out.append(("🖼 Source/Assets", os.path.join(project.path, "assets")))
    if os.path.isdir(android_root):
        out.append(("📱 Armazenamento", android_root))
        download = os.path.join(android_root, "Download")
        if os.path.isdir(download):
            out.append(("⬇️ Download", download))
    out.append(("🗂 LuaStudio", storage))
    out.append(("/ Raiz", "/"))
    # remove duplicados mantendo ordem (ex: Source == Armazenamento)
    seen, dedup = set(), []
    for label, path in out:
        key = os.path.normpath(path)
        if key not in seen:
            seen.add(key)
            dedup.append((label, path))
    return dedup


def _start_dir(start):
    if start and os.path.isdir(start):
        return os.path.normpath(start)
    android_root = "/storage/emulated/0"
    if os.path.isdir(android_root):
        return android_root
    return os.path.normpath(perms.storage_dir())


def _list_dir(path, mode, extensions):
    """Devolve (pastas, arquivos, erro). `erro` e uma string se a pasta
    nao pode ser lida (permissao negada etc.), senao None."""
    dirs, files = [], []
    try:
        entries = sorted(os.listdir(path), key=lambda n: n.lower())
    except PermissionError:
        return [], [], "Sem permissão pra abrir esta pasta"
    except FileNotFoundError:
        return [], [], "Essa pasta não existe mais"
    except OSError as ex:
        return [], [], "Não foi possível abrir: %s" % ex
    exts = None
    if extensions:
        exts = tuple(e.lower() if e.startswith(".") else ("." + e.lower())
                    for e in extensions)
    for name in entries:
        if name.startswith("."):
            continue  # esconde ocultos (.thumbnails, .trash etc.)
        full = os.path.join(path, name)
        try:
            is_dir = os.path.isdir(full)
        except OSError:
            continue
        if is_dir:
            dirs.append(name)
        elif mode == "file":
            if exts is None or name.lower().endswith(exts):
                files.append(name)
    return dirs, files, None


class _Row(Button):
    """Linha da listagem (pasta ou arquivo), largura total, alinhada a
    esquerda."""

    def __init__(self, text, on_release, dim=False, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", 46)
        kw.setdefault("background_normal", "")
        kw.setdefault("background_down", "")
        kw.setdefault("background_color", (0, 0, 0, 0))
        kw.setdefault("color", theme.TEXT_DIM if dim else theme.TEXT)
        kw.setdefault("font_size", 14)
        kw.setdefault("halign", "left")
        kw.setdefault("valign", "middle")
        kw.setdefault("padding", (12, 0))
        Button.__init__(self, text=text, **kw)
        self.bind(size=lambda w, v: setattr(w, "text_size", (v[0] - 24, v[1])))
        if on_release:
            self.bind(on_release=on_release)
        from kivy.graphics import Color, RoundedRectangle
        with self.canvas.before:
            self._c = Color(*theme.SURFACE)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[8])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_a):
        self._rect.pos = self.pos
        self._rect.size = self.size


def open_picker(title, mode="folder", start=None, extensions=None,
                shortcuts=None, on_select=None, on_cancel=None,
                select_label=None):
    """Abre o popup do navegador de arquivos.

    mode="folder": navega livremente e confirma com um botão
    "Selecionar esta pasta" (útil pra apontar uma pasta de
    assets/projeto/export).
    mode="file": navega livremente e toca num arquivo pra escolher na
    hora (filtra por `extensions`, ex: [".png", ".jpg", ".Lsp"])."""
    state = {"path": _start_dir(start)}
    shortcuts = shortcuts or default_shortcuts()

    root = BoxLayout(orientation="vertical", spacing=8, padding=10)
    popup = Popup(title=title, content=root, size_hint=(0.95, 0.9),
                  title_color=theme.TEXT, title_size=17,
                  separator_color=theme.ACCENT, background_color=theme.BG)

    # ---- atalhos (chips horizontais) ----
    shortcuts_scroll = ScrollView(size_hint_y=None, height=46,
                                  do_scroll_y=False, bar_width=0)
    shortcuts_row = BoxLayout(size_hint_x=None, spacing=6, padding=(0, 0))
    shortcuts_row.bind(minimum_width=lambda w, v: setattr(w, "width", v))
    shortcuts_scroll.add_widget(shortcuts_row)
    root.add_widget(shortcuts_scroll)

    # ---- caminho atual: subir + caminho digitável + Ir ----
    path_bar = BoxLayout(size_hint_y=None, height=46, spacing=6)
    up_btn = theme.RoundButton(text="⬆️", size_hint_x=None, width=48,
                               bg_color=theme.SURFACE_2, radius=10)
    path_in = TextInput(multiline=False, font_size=13,
                        background_color=theme.EDITOR_BG,
                        foreground_color=theme.TEXT, cursor_color=theme.CURSOR,
                        padding=(10, 12))
    go_btn = theme.RoundButton(text="Ir", size_hint_x=None, width=56,
                               bg_color=theme.ACCENT, radius=10)
    path_bar.add_widget(up_btn)
    path_bar.add_widget(path_in)
    path_bar.add_widget(go_btn)
    root.add_widget(path_bar)

    # ---- listagem ----
    scroll = ScrollView()
    listing = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None,
                        padding=(0, 4))
    listing.bind(minimum_height=lambda w, v: setattr(w, "height", v))
    scroll.add_widget(listing)
    root.add_widget(scroll)

    # ---- rodape ----
    bottom = BoxLayout(size_hint_y=None, height=50, spacing=6)
    select_btn = theme.RoundButton(
        text=select_label or "✅  Selecionar esta pasta",
        bg_color=theme.PLAY, radius=12)
    cancel_btn = theme.RoundButton(text="Cancelar", size_hint_x=None, width=110,
                                   bg_color=theme.SURFACE_2, radius=12)
    if mode == "folder":
        bottom.add_widget(select_btn)
    bottom.add_widget(cancel_btn)
    root.add_widget(bottom)

    def refresh(*_a):
        path = state["path"]
        path_in.text = path
        up_btn.disabled = (os.path.normpath(path) == os.path.normpath(
            os.path.abspath(os.sep)))
        listing.clear_widgets()
        dirs, files, err = _list_dir(path, mode, extensions)
        if err:
            listing.add_widget(Label(text=err, color=theme.STOP,
                                     size_hint_y=None, height=44))
            return
        if not dirs and not files:
            listing.add_widget(Label(text="(pasta vazia)", color=theme.TEXT_DIM,
                                     size_hint_y=None, height=40))
        for name in dirs:
            full = os.path.join(path, name)

            def enter_dir(_b, p=full):
                state["path"] = p
                refresh()
            listing.add_widget(_Row("📁  %s" % name, enter_dir))
        for name in files:
            full = os.path.join(path, name)

            def pick_file(_b, p=full):
                popup.dismiss()
                if on_select:
                    on_select(p)
            listing.add_widget(_Row("📄  %s" % name, pick_file, dim=True))

    def go_up(*_a):
        parent = os.path.dirname(state["path"].rstrip(os.sep))
        if not parent:
            parent = os.sep
        state["path"] = parent
        refresh()

    def go_typed(*_a):
        typed = path_in.text.strip()
        if typed and os.path.isdir(typed):
            state["path"] = os.path.normpath(typed)
            refresh()
        else:
            path_in.text = state["path"]

    def do_select_folder(*_a):
        popup.dismiss()
        if on_select:
            on_select(state["path"])

    def do_cancel(*_a):
        popup.dismiss()
        if on_cancel:
            on_cancel()

    up_btn.bind(on_release=go_up)
    go_btn.bind(on_release=go_typed)
    path_in.bind(on_text_validate=go_typed)
    select_btn.bind(on_release=do_select_folder)
    cancel_btn.bind(on_release=do_cancel)

    for label, target in shortcuts:
        def jump(_b, p=target):
            if os.path.isdir(p):
                state["path"] = os.path.normpath(p)
                refresh()
        chip = theme.RoundButton(text=label, size_hint_x=None, width=150,
                                 font_size=13, bg_color=theme.SURFACE_2,
                                 radius=16)
        chip.bind(on_release=jump)
        shortcuts_row.add_widget(chip)

    refresh()
    popup.open()
    return popup

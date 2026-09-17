# -*- coding: utf-8 -*-
"""Editor de codigo Kivy: realce de sintaxe Lua, indent automatico,
numeros de linha e barra de simbolos (util no teclado do Android)."""

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line

from . import theme

try:
    from kivy.uix.codeinput import CodeInput
    from pygments.lexers import LuaLexer
    HAS_CODEINPUT = True
except Exception:
    from kivy.uix.textinput import TextInput as CodeInput
    LuaLexer = None
    HAS_CODEINPUT = False

INDENT = "  "
OPEN_WORDS = ("function", "if", "for", "while", "do", "else", "elseif", "repeat")
GUTTER_WIDTH = 46


class LuaEditor(CodeInput):
    def __init__(self, **kw):
        kw.setdefault("font_size", 15)
        kw.setdefault("background_color", theme.EDITOR_BG)
        kw.setdefault("foreground_color", theme.TEXT)
        kw.setdefault("cursor_color", theme.CURSOR)
        kw.setdefault("selection_color", theme.ACCENT[:3] + (0.35,))
        kw.setdefault("padding", (12, 10))
        kw.setdefault("auto_indent", False)
        if HAS_CODEINPUT:
            kw.setdefault("lexer", LuaLexer())
            kw.setdefault("style_name", "monokai")
            kw.pop("foreground_color", None)
        CodeInput.__init__(self, **kw)

    # ---- indent automatico ----
    def insert_text(self, substring, from_undo=False):
        if substring == "\n" and not from_undo:
            line = self.text[:self.cursor_index()].split("\n")[-1]
            indent = line[:len(line) - len(line.lstrip())]
            stripped = line.strip()
            opens = (stripped.endswith("then") or stripped.endswith("do")
                     or stripped.endswith("{") or stripped.endswith("(")
                     or stripped.startswith("function") or " function" in stripped
                     or stripped.endswith("else"))
            if opens:
                indent += INDENT
            return CodeInput.insert_text(self, "\n" + indent, from_undo)
        if substring == "\t":
            return CodeInput.insert_text(self, INDENT, from_undo)
        return CodeInput.insert_text(self, substring, from_undo)

    def dedent_current_line(self):
        idx = self.cursor_index()
        start = self.text.rfind("\n", 0, idx) + 1
        if self.text[start:start + len(INDENT)] == INDENT:
            self.text = self.text[:start] + self.text[start + len(INDENT):]
            self.cursor = self.get_cursor_from_index(max(start, idx - len(INDENT)))

    def toggle_comment(self):
        idx = self.cursor_index()
        start = self.text.rfind("\n", 0, idx) + 1
        end = self.text.find("\n", idx)
        end = len(self.text) if end == -1 else end
        line = self.text[start:end]
        stripped = line.lstrip()
        pad = line[:len(line) - len(stripped)]
        new = pad + (stripped[2:].lstrip() if stripped.startswith("--") else "-- " + stripped)
        self.text = self.text[:start] + new + self.text[end:]


class Gutter(BoxLayout):
    """Coluna de numeros de linha feita de um Label POR LINHA (em vez de
    um unico Label multi-linha). Cada linha tem a MESMA altura da linha
    correspondente no editor (`editor.line_height`), entao a coluna toda
    fica com a mesma altura total do texto - por isso da pra colocar os
    dois dentro do MESMO ScrollView e eles rolam juntos, sem desgrudar
    (esse era o bug: antes o gutter ficava fora do ScrollView e nao se
    mexia quando o texto rolava)."""

    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("width", GUTTER_WIDTH)
        BoxLayout.__init__(self, **kw)
        with self.canvas.before:
            Color(*theme.SURFACE)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *a: setattr(self._bg, "pos", self.pos),
                 size=lambda *a: setattr(self._bg, "size", self.size))
        self._rows = []
        self.error_row = None

    def _make_row(self, row_height):
        lbl = Label(size_hint=(1, None), height=row_height, halign="right",
                   valign="middle", color=theme.TEXT_DIM, font_size=13)
        lbl.bind(size=lambda w, v: setattr(w, "text_size", v))
        # retangulo de destaque JA fica anexado (transparente) desde a
        # criacao - assim marcar/desmarcar erro so muda o alpha da cor,
        # sem precisar limpar/reanexar o canvas (e sem acumular binds
        # novos a cada tecla digitada).
        with lbl.canvas.before:
            hl_color = Color(*theme.STOP[:3], 0.0)
            hl_rect = Rectangle(pos=lbl.pos, size=lbl.size)
        lbl.bind(pos=lambda w, v: setattr(hl_rect, "pos", v),
                size=lambda w, v: setattr(hl_rect, "size", v))
        lbl._hl_color = hl_color
        return lbl

    def set_count(self, n, row_height):
        n = max(int(n), 1)
        row_height = max(row_height or 0, 14)
        while len(self._rows) < n:
            lbl = self._make_row(row_height)
            self._rows.append(lbl)
            self.add_widget(lbl)
        while len(self._rows) > n:
            self.remove_widget(self._rows.pop())
        for i, lbl in enumerate(self._rows):
            lbl.text = str(i + 1)
            if lbl.height != row_height:
                lbl.height = row_height
            self._paint_row(lbl, self.error_row == i + 1)
        # padding[1]/[3] (topo/baixo) precisam bater com o padding vertical
        # do editor (ver EditorPane.__init__) - senao os numeros vao
        # aparecer "descolados" das linhas de codigo depois de algumas
        # linhas, mesmo com a rolagem sincronizada.
        pad = self.padding
        self.height = row_height * n + pad[1] + pad[3]

    def _paint_row(self, lbl, is_error):
        lbl.color = theme.STOP if is_error else theme.TEXT_DIM
        lbl._hl_color.a = 0.28 if is_error else 0.0

    def set_error_row(self, row):
        self.error_row = row
        for i, lbl in enumerate(self._rows):
            self._paint_row(lbl, row == i + 1)


class EditorPane(BoxLayout):
    """Editor + numeros de linha (sincronizados) + barra de simbolos +
    outline vermelho na linha de um erro de execucao."""

    def __init__(self, **kw):
        BoxLayout.__init__(self, orientation="vertical", **kw)
        with self.canvas.before:
            Color(*theme.EDITOR_BG)
            bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *a: setattr(bg, "pos", self.pos),
                 size=lambda *a: setattr(bg, "size", self.size))

        self._error_line = None
        self._hl_rect = None
        self._hl_border = None

        self.gutter = Gutter()
        self.editor = LuaEditor(size_hint=(1, None))
        # o padding vertical do gutter tem que ser IGUAL ao padding
        # vertical do editor (top/bottom) - e o que garante que a linha 1
        # do numero bata exatamente com a linha 1 do codigo, e que isso
        # continue valendo conforme o arquivo cresce.
        pad_v = self.editor.padding[1] if len(self.editor.padding) > 1 else 10
        self.gutter.padding = (0, pad_v, 0, pad_v)
        self.editor.bind(minimum_height=self._sync_height, text=self._on_text,
                         pos=self._update_highlight, size=self._update_highlight)

        # gutter + editor moram no MESMO BoxLayout, que por sua vez e o
        # UNICO filho do ScrollView - assim uma unica rolagem move os
        # dois juntos.
        self._row = BoxLayout(orientation="horizontal", size_hint=(1, None))
        self._row.add_widget(self.gutter)
        self._row.add_widget(self.editor)

        self._scroll = ScrollView(do_scroll_x=False, bar_width=6,
                                  scroll_type=["bars", "content"])
        self._scroll.add_widget(self._row)

        self.add_widget(self._scroll)
        self.add_widget(self._symbol_bar())
        Clock.schedule_once(lambda *a: self._on_text(), 0)

    def _sync_height(self, *_a):
        h = max(self.editor.minimum_height, 400)
        self.editor.height = h
        self._row.height = h

    def _on_text(self, *_a):
        lines = self.editor.text.count("\n") + 1
        row_h = self.editor.line_height or 20
        self.gutter.set_count(lines, row_h)

    def _symbol_bar(self):
        bar = BoxLayout(size_hint_y=None, height=46, spacing=4, padding=(6, 4))
        with bar.canvas.before:
            Color(*theme.SURFACE)
            bg = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(pos=lambda *a: setattr(bg, "pos", bar.pos),
                size=lambda *a: setattr(bg, "size", bar.size))
        items = [("Tab", INDENT), ("←", None), ("--", "-- "), ("=", " = "),
                 ("{}", "{}"), ("()", "()"), ('""', '""'), (":", ":"),
                 ("end", "end"), ("fn", "function() end")]
        for label, ins in items:
            b = theme.RoundButton(text=label, font_size=14, bg_color=theme.SURFACE_2,
                                  radius=10)
            if ins is None:
                b.bind(on_release=lambda *a: self.editor.dedent_current_line())
            else:
                b.bind(on_release=lambda _b, s=ins: self.editor.insert_text(s))
            bar.add_widget(b)
        return bar

    # ---------------------------------------------------- outline de erro
    def _ensure_highlight(self):
        if self._hl_rect is None:
            with self.editor.canvas.after:
                Color(*theme.STOP[:3], 0.16)
                self._hl_rect = Rectangle(pos=(0, 0), size=(0, 0))
                Color(*theme.STOP[:3], 0.95)
                self._hl_border = Line(rectangle=(0, 0, 0, 0), width=1.3)

    def _update_highlight(self, *_a):
        if self._error_line is None or self._hl_rect is None:
            return
        row_h = self.editor.line_height or 20
        top_pad = self.editor.padding[1]
        row = max(self._error_line - 1, 0)
        top = self.editor.y + self.editor.height - top_pad
        y = top - (row + 1) * row_h
        x, w = self.editor.x, self.editor.width
        self._hl_rect.pos = (x, y)
        self._hl_rect.size = (w, row_h)
        self._hl_border.rectangle = (x, y, w, row_h)

    def mark_error_line(self, line_no):
        """Poe um outline vermelho na linha `line_no` (1-based) - fica ali
        ate a proxima vez que o Play rodar (com sucesso ou nao)."""
        if not line_no:
            return
        self._error_line = line_no
        self._ensure_highlight()
        self.gutter.set_error_row(line_no)
        self._update_highlight()
        # garante que a linha marcada fique visivel na tela
        Clock.schedule_once(lambda *a: self._scroll_to_line(line_no), 0)

    def clear_error_line(self):
        self._error_line = None
        self.gutter.set_error_row(None)
        if self._hl_rect is not None:
            self._hl_rect.size = (0, 0)
            self._hl_border.rectangle = (0, 0, 0, 0)

    def _scroll_to_line(self, line_no):
        row_h = self.editor.line_height or 20
        total = max(self._row.height - self._scroll.height, 1)
        target_y = (line_no - 1) * row_h
        frac = 1.0 - min(max(target_y / total, 0.0), 1.0)
        self._scroll.scroll_y = frac

    @property
    def text(self):
        return self.editor.text

    @text.setter
    def text(self, value):
        self.editor.text = value

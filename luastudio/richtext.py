# -*- coding: utf-8 -*-
import re

from .api import DEFAULT_COLORS, to_color

_TAG_RE = re.compile(r'<(/?)([A-Za-z_][A-Za-z0-9_]*)(?:=([^>]*?))?\s*(/?)>')

CUSTOM_STYLES = {}


def define_style(tag, spec):
    CUSTOM_STYLES[str(tag).lower()] = dict(spec or {})


def clear_style(tag=None):
    if tag is None:
        CUSTOM_STYLES.clear()
    else:
        CUSTOM_STYLES.pop(str(tag).lower(), None)


class Run(object):
    __slots__ = ("text", "color", "bold", "italic", "underline", "size", "link", "image")

    def __init__(self, text="", color=None, bold=False, italic=False,
                 underline=False, size=None, link=None, image=None):
        self.text = text
        self.color = color
        self.bold = bold
        self.italic = italic
        self.underline = underline
        self.size = size
        self.link = link
        self.image = image


def _strip_quotes(v):
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def _apply_named_style(top, tag_l, value):
    if tag_l == "b":
        top["bold"] = True
    elif tag_l == "i":
        top["italic"] = True
    elif tag_l == "u":
        top["underline"] = True
    elif tag_l == "color":
        top["color"] = to_color(_strip_quotes(value))
    elif tag_l == "size":
        try:
            top["size"] = float(_strip_quotes(value))
        except Exception:
            pass
    elif tag_l == "link":
        top["link"] = _strip_quotes(value)
        if top.get("color") is None:
            top["color"] = (0.40, 0.70, 1.0, 1.0)
        top["underline"] = True
    elif tag_l in DEFAULT_COLORS:
        top["color"] = DEFAULT_COLORS[tag_l]
    elif tag_l in CUSTOM_STYLES:
        st = CUSTOM_STYLES[tag_l]
        if st.get("Color") is not None:
            top["color"] = to_color(st.get("Color"))
        if st.get("Bold") is not None:
            top["bold"] = bool(st.get("Bold"))
        if st.get("Italic") is not None:
            top["italic"] = bool(st.get("Italic"))
        if st.get("FontSize") is not None:
            top["size"] = float(st.get("FontSize"))


def parse(markup):
    runs = []
    stack = [{"color": None, "bold": False, "italic": False,
              "underline": False, "size": None, "link": None}]
    pos = 0
    for m in _TAG_RE.finditer(markup or ""):
        if m.start() > pos:
            _emit(runs, markup[pos:m.start()], stack[-1])
        closing, tag, value, selfclose = m.groups()
        tag_l = tag.lower()
        if tag_l == "img":
            runs.append(Run(image=_strip_quotes(value)))
        elif closing:
            if len(stack) > 1:
                stack.pop()
        else:
            top = dict(stack[-1])
            _apply_named_style(top, tag_l, value)
            if not selfclose:
                stack.append(top)
        pos = m.end()
    if pos < len(markup or ""):
        _emit(runs, markup[pos:], stack[-1])
    return runs


def _emit(runs, text, style):
    if not text:
        return
    runs.append(Run(text=text, color=style.get("color"), bold=style.get("bold", False),
                     italic=style.get("italic", False), underline=style.get("underline", False),
                     size=style.get("size"), link=style.get("link")))

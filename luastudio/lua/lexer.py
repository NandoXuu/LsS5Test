# -*- coding: utf-8 -*-
"""Lexer Lua 5.x (subconjunto) em Python puro."""

KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return",
    "then", "true", "until", "while",
}

SYMBOLS = [
    "...", "..", "==", "~=", "<=", ">=", "//", "::", "<<", ">>",
    "+", "-", "*", "/", "%", "^", "#", "&", "~", "|", "<", ">", "=",
    "(", ")", "{", "}", "[", "]", ";", ":", ",", ".",
]


class LuaSyntaxError(Exception):
    pass


class Token(object):
    __slots__ = ("type", "value", "line")

    def __init__(self, type_, value, line):
        self.type = type_          # name | number | string | keyword | symbol | eof
        self.value = value
        self.line = line

    def __repr__(self):
        return "<%s %r L%d>" % (self.type, self.value, self.line)


def _long_bracket(src, i, line):
    """Le [[...]] / [=[...]=]. Retorna (texto, novo_i, nova_linha) ou None."""
    if src[i] != "[":
        return None
    j = i + 1
    level = 0
    while j < len(src) and src[j] == "=":
        level += 1
        j += 1
    if j >= len(src) or src[j] != "[":
        return None
    j += 1
    if j < len(src) and src[j] == "\n":
        line += 1
        j += 1
    close = "]" + "=" * level + "]"
    end = src.find(close, j)
    if end == -1:
        raise LuaSyntaxError("string longa nao fechada (linha %d)" % line)
    text = src[j:end]
    line += text.count("\n")
    return text, end + len(close), line


def tokenize(src):
    tokens = []
    i = 0
    line = 1
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        # comentarios
        if src.startswith("--", i):
            i += 2
            lb = None
            if i < n and src[i] == "[":
                try:
                    lb = _long_bracket(src, i, line)
                except LuaSyntaxError:
                    lb = None
            if lb:
                _, i, line = lb
                continue
            while i < n and src[i] != "\n":
                i += 1
            continue
        # numero
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            start = i
            if src.startswith("0x", i) or src.startswith("0X", i):
                i += 2
                while i < n and (src[i] in "0123456789abcdefABCDEF"):
                    i += 1
                tokens.append(Token("number", float(int(src[start:i], 16)), line))
                continue
            seen_dot = False
            while i < n:
                ch = src[i]
                if ch.isdigit():
                    i += 1
                elif ch == "." and not seen_dot:
                    seen_dot = True
                    i += 1
                elif ch in "eE":
                    i += 1
                    if i < n and src[i] in "+-":
                        i += 1
                else:
                    break
            tokens.append(Token("number", float(src[start:i]), line))
            continue
        # nome / palavra-chave
        if c.isalpha() or c == "_":
            start = i
            while i < n and (src[i].isalnum() or src[i] == "_"):
                i += 1
            word = src[start:i]
            tokens.append(Token("keyword" if word in KEYWORDS else "name", word, line))
            continue
        # string curta
        if c in "\"'":
            quote = c
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise LuaSyntaxError("string nao fechada (linha %d)" % line)
                ch = src[i]
                if ch == "\\":
                    i += 1
                    esc = src[i]
                    mapping = {"n": "\n", "t": "\t", "r": "\r", "a": "\a",
                               "b": "\b", "f": "\f", "v": "\v", "\\": "\\",
                               '"': '"', "'": "'", "\n": "\n"}
                    if esc in mapping:
                        buf.append(mapping[esc])
                        i += 1
                    elif esc == "u":
                        i += 1
                        if src[i] == "{":
                            j = src.index("}", i)
                            buf.append(chr(int(src[i + 1:j], 16)))
                            i = j + 1
                    elif esc.isdigit():
                        num = ""
                        while len(num) < 3 and src[i].isdigit():
                            num += src[i]
                            i += 1
                        buf.append(chr(int(num)))
                    else:
                        buf.append(esc)
                        i += 1
                    continue
                if ch == quote:
                    i += 1
                    break
                if ch == "\n":
                    raise LuaSyntaxError("quebra de linha em string (linha %d)" % line)
                buf.append(ch)
                i += 1
            tokens.append(Token("string", "".join(buf), line))
            continue
        # string longa
        if c == "[":
            lb = _long_bracket(src, i, line)
            if lb:
                text, i, newline = lb
                tokens.append(Token("string", text, line))
                line = newline
                continue
        # simbolos
        for sym in SYMBOLS:
            if src.startswith(sym, i):
                tokens.append(Token("symbol", sym, line))
                i += len(sym)
                break
        else:
            raise LuaSyntaxError("caractere inesperado %r (linha %d)" % (c, line))
    tokens.append(Token("eof", None, line))
    return tokens

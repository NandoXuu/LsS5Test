# -*- coding: utf-8 -*-
"""Parser Lua (subconjunto) -> AST de tuplas."""

from .lexer import tokenize, LuaSyntaxError


class Parser(object):
    def __init__(self, src, chunkname="chunk"):
        self.toks = tokenize(src)
        self.pos = 0
        self.chunkname = chunkname

    # -------- utilidades --------
    @property
    def tok(self):
        return self.toks[self.pos]

    def next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def check(self, type_, value=None):
        t = self.tok
        return t.type == type_ and (value is None or t.value == value)

    def accept(self, type_, value=None):
        if self.check(type_, value):
            return self.next()
        return None

    def expect(self, type_, value=None):
        if not self.check(type_, value):
            raise LuaSyntaxError("esperado %r, encontrado %r (linha %d)"
                                 % (value or type_, self.tok.value, self.tok.line))
        return self.next()

    # -------- blocos --------
    def parse_chunk(self):
        block = self.parse_block()
        self.expect("eof")
        return block

    BLOCK_END = {"end", "else", "elseif", "until"}

    def parse_block(self):
        stats = []
        while True:
            t = self.tok
            if t.type == "eof":
                break
            if t.type == "keyword" and t.value in self.BLOCK_END:
                break
            if t.type == "keyword" and t.value == "return":
                line = self.next().line
                exprs = []
                if not (self.tok.type == "eof"
                        or (self.tok.type == "keyword" and self.tok.value in self.BLOCK_END)
                        or self.check("symbol", ";")):
                    exprs = self.parse_exprlist()
                self.accept("symbol", ";")
                stats.append(("return", exprs, line))
                break
            st = self.parse_statement()
            if st is not None:
                stats.append(st)
        return ("block", stats)

    def parse_statement(self):
        t = self.tok
        line = t.line
        if self.accept("symbol", ";"):
            return None
        if t.type == "symbol" and t.value == "::":
            self.next(); self.expect("name"); self.expect("symbol", "::")
            return None
        if t.type == "keyword":
            kw = t.value
            if kw == "break":
                self.next()
                return ("break", line)
            if kw == "do":
                self.next()
                b = self.parse_block()
                self.expect("keyword", "end")
                return ("do", b, line)
            if kw == "while":
                self.next()
                cond = self.parse_expr()
                self.expect("keyword", "do")
                body = self.parse_block()
                self.expect("keyword", "end")
                return ("while", cond, body, line)
            if kw == "repeat":
                self.next()
                body = self.parse_block()
                self.expect("keyword", "until")
                cond = self.parse_expr()
                return ("repeat", body, cond, line)
            if kw == "if":
                self.next()
                clauses = []
                cond = self.parse_expr()
                self.expect("keyword", "then")
                clauses.append((cond, self.parse_block()))
                orelse = None
                while True:
                    if self.accept("keyword", "elseif"):
                        c = self.parse_expr()
                        self.expect("keyword", "then")
                        clauses.append((c, self.parse_block()))
                        continue
                    if self.accept("keyword", "else"):
                        orelse = self.parse_block()
                    self.expect("keyword", "end")
                    break
                return ("if", clauses, orelse, line)
            if kw == "for":
                self.next()
                name = self.expect("name").value
                if self.accept("symbol", "="):
                    start = self.parse_expr()
                    self.expect("symbol", ",")
                    stop = self.parse_expr()
                    step = self.parse_expr() if self.accept("symbol", ",") else None
                    self.expect("keyword", "do")
                    body = self.parse_block()
                    self.expect("keyword", "end")
                    return ("fornum", name, start, stop, step, body, line)
                names = [name]
                while self.accept("symbol", ","):
                    names.append(self.expect("name").value)
                self.expect("keyword", "in")
                exprs = self.parse_exprlist()
                self.expect("keyword", "do")
                body = self.parse_block()
                self.expect("keyword", "end")
                return ("forin", names, exprs, body, line)
            if kw == "function":
                self.next()
                nameparts = [self.expect("name").value]
                is_method = False
                while self.accept("symbol", "."):
                    nameparts.append(self.expect("name").value)
                if self.accept("symbol", ":"):
                    nameparts.append(self.expect("name").value)
                    is_method = True
                func = self.parse_funcbody(is_method, ".".join(nameparts))
                target = ("name", nameparts[0], line)
                for part in nameparts[1:]:
                    target = ("index", target, ("const", part), line)
                return ("assign", [target], [func], line)
            if kw == "local":
                self.next()
                if self.accept("keyword", "function"):
                    name = self.expect("name").value
                    func = self.parse_funcbody(False, name)
                    return ("localfunc", name, func, line)
                names = [self.expect("name").value]
                self.accept_attrib()
                while self.accept("symbol", ","):
                    names.append(self.expect("name").value)
                    self.accept_attrib()
                exprs = self.parse_exprlist() if self.accept("symbol", "=") else []
                return ("local", names, exprs, line)
        # expressao: chamada ou atribuicao
        first = self.parse_suffixed()
        if self.check("symbol", "=") or self.check("symbol", ","):
            targets = [first]
            while self.accept("symbol", ","):
                targets.append(self.parse_suffixed())
            self.expect("symbol", "=")
            exprs = self.parse_exprlist()
            return ("assign", targets, exprs, line)
        if first[0] not in ("call", "methcall"):
            raise LuaSyntaxError("expressao invalida como comando (linha %d)" % line)
        return ("callstat", first, line)

    def accept_attrib(self):
        if self.accept("symbol", "<"):
            self.expect("name")
            self.expect("symbol", ">")

    def parse_funcbody(self, is_method, name="?"):
        line = self.tok.line
        self.expect("symbol", "(")
        params = ["self"] if is_method else []
        vararg = False
        if not self.check("symbol", ")"):
            while True:
                if self.accept("symbol", "..."):
                    vararg = True
                    break
                params.append(self.expect("name").value)
                if not self.accept("symbol", ","):
                    break
        self.expect("symbol", ")")
        body = self.parse_block()
        self.expect("keyword", "end")
        return ("function", params, vararg, body, name, line)

    # -------- expressoes --------
    def parse_exprlist(self):
        exprs = [self.parse_expr()]
        while self.accept("symbol", ","):
            exprs.append(self.parse_expr())
        return exprs

    BINPRI = {
        "or": (1, 1), "and": (2, 2),
        "<": (3, 3), ">": (3, 3), "<=": (3, 3), ">=": (3, 3), "~=": (3, 3), "==": (3, 3),
        "|": (4, 4), "~": (5, 5), "&": (6, 6), "<<": (7, 7), ">>": (7, 7),
        "..": (9, 8),
        "+": (10, 10), "-": (10, 10),
        "*": (11, 11), "/": (11, 11), "//": (11, 11), "%": (11, 11),
        "^": (14, 13),
    }
    UNARY_PRI = 12

    def parse_expr(self, limit=0):
        t = self.tok
        if (t.type == "symbol" and t.value in ("-", "#", "~")) or \
           (t.type == "keyword" and t.value == "not"):
            op = self.next().value
            operand = self.parse_expr(self.UNARY_PRI)
            left = ("unop", op, operand, t.line)
        else:
            left = self.parse_simple()
        while True:
            t = self.tok
            op = t.value
            if t.type == "keyword" and op in ("and", "or"):
                pass
            elif t.type == "symbol" and op in self.BINPRI:
                pass
            else:
                break
            left_pri, right_pri = self.BINPRI[op]
            if left_pri <= limit:
                break
            self.next()
            right = self.parse_expr(right_pri)
            left = ("binop", op, left, right, t.line)
        return left

    def parse_simple(self):
        t = self.tok
        line = t.line
        if t.type == "number" or t.type == "string":
            self.next()
            return ("const", t.value)
        if t.type == "keyword":
            if t.value == "nil":
                self.next(); return ("const", None)
            if t.value == "true":
                self.next(); return ("const", True)
            if t.value == "false":
                self.next(); return ("const", False)
            if t.value == "function":
                self.next()
                return self.parse_funcbody(False)
        if t.type == "symbol":
            if t.value == "...":
                self.next(); return ("vararg", line)
            if t.value == "{":
                return self.parse_table()
        return self.parse_suffixed()

    def parse_primary(self):
        t = self.tok
        if t.type == "name":
            self.next()
            return ("name", t.value, t.line)
        if self.accept("symbol", "("):
            e = self.parse_expr()
            self.expect("symbol", ")")
            return ("paren", e)
        raise LuaSyntaxError("expressao inesperada %r (linha %d)" % (t.value, t.line))

    def parse_suffixed(self):
        exp = self.parse_primary()
        while True:
            t = self.tok
            line = t.line
            if self.accept("symbol", "."):
                name = self.expect("name").value
                exp = ("index", exp, ("const", name), line)
            elif self.accept("symbol", "["):
                idx = self.parse_expr()
                self.expect("symbol", "]")
                exp = ("index", exp, idx, line)
            elif self.check("symbol", ":"):
                self.next()
                name = self.expect("name").value
                args = self.parse_args()
                exp = ("methcall", exp, name, args, line)
            elif self.check("symbol", "(") or self.check("symbol", "{") or self.check("string"):
                args = self.parse_args()
                exp = ("call", exp, args, line)
            else:
                return exp

    def parse_args(self):
        if self.check("string"):
            return [("const", self.next().value)]
        if self.check("symbol", "{"):
            return [self.parse_table()]
        self.expect("symbol", "(")
        args = [] if self.check("symbol", ")") else self.parse_exprlist()
        self.expect("symbol", ")")
        return args

    def parse_table(self):
        line = self.expect("symbol", "{").line
        array = []
        hash_ = []
        while not self.check("symbol", "}"):
            if self.check("symbol", "["):
                self.next()
                k = self.parse_expr()
                self.expect("symbol", "]")
                self.expect("symbol", "=")
                hash_.append((k, self.parse_expr()))
            elif self.tok.type == "name" and self.toks[self.pos + 1].type == "symbol" \
                    and self.toks[self.pos + 1].value == "=":
                k = self.next().value
                self.next()
                hash_.append((("const", k), self.parse_expr()))
            else:
                array.append(self.parse_expr())
            if not (self.accept("symbol", ",") or self.accept("symbol", ";")):
                break
        self.expect("symbol", "}")
        return ("table", array, hash_, line)


def parse(src, chunkname="chunk"):
    return Parser(src, chunkname).parse_chunk()

# -*- coding: utf-8 -*-
"""Interpretador Lua (subconjunto) em Python puro - sem dependencias externas."""

import math
import time
import random

from .parser import parse
from .lexer import LuaSyntaxError


class LuaError(Exception):
    def __init__(self, value):
        Exception.__init__(self, str(value))
        self.value = value


class BreakSignal(Exception):
    pass


class ReturnSignal(Exception):
    def __init__(self, values):
        Exception.__init__(self)
        self.values = values


# ---------------------------------------------------------------- LuaTable
class LuaTable(object):
    __slots__ = ("hash", "metatable")

    def __init__(self, array=None, hash_=None):
        self.hash = {}
        self.metatable = None
        if array:
            for i, v in enumerate(array):
                if v is not None:
                    self.hash[float(i + 1)] = v
        if hash_:
            for k, v in hash_.items():
                self.set(k, v)

    @staticmethod
    def norm(key):
        if isinstance(key, bool):
            return key
        if isinstance(key, int):
            return float(key)
        return key

    def get(self, key):
        key = self.norm(key)
        if key in self.hash:
            return self.hash[key]
        if self.metatable is not None:
            idx = self.metatable.hash.get("__index")
            if isinstance(idx, LuaTable):
                return idx.get(key)
            if callable(idx):
                return first(idx(self, key))
        return None

    def raw_get(self, key):
        return self.hash.get(self.norm(key))

    def set(self, key, value):
        key = self.norm(key)
        if key is None:
            raise LuaError("indice nil na tabela")
        if value is None:
            self.hash.pop(key, None)
        else:
            self.hash[key] = value

    def length(self):
        n = 0
        while float(n + 1) in self.hash:
            n += 1
        return n

    def ipairs_list(self):
        out = []
        i = 1
        while float(i) in self.hash:
            out.append(self.hash[float(i)])
            i += 1
        return out

    def items(self):
        return list(self.hash.items())

    def to_python(self):
        """Converte para dict/list Python (recursivo)."""
        n = self.length()
        if n and n == len(self.hash):
            return [to_py(self.hash[float(i + 1)]) for i in range(n)]
        return dict((to_py(k), to_py(v)) for k, v in self.hash.items())

    def __repr__(self):
        return "table: 0x%x" % (id(self),)


def to_py(v):
    if isinstance(v, LuaTable):
        return v.to_python()
    if isinstance(v, float) and v.is_integer():
        return v
    return v


def from_py(v):
    if isinstance(v, dict):
        t = LuaTable()
        for k, val in v.items():
            t.set(float(k) if isinstance(k, int) else k, from_py(val))
        return t
    if isinstance(v, (list, tuple)):
        return LuaTable([from_py(x) for x in v])
    if isinstance(v, int) and not isinstance(v, bool):
        return float(v)
    return v


def first(values):
    if isinstance(values, (list, tuple)):
        return values[0] if values else None
    return values


def as_list(values):
    if values is None:
        return []
    if isinstance(values, (list, tuple)):
        return list(values)
    return [values]


# --------------------------------------------------------------- Function
class LuaFunction(object):
    __slots__ = ("params", "vararg", "body", "env", "interp", "name")

    def __init__(self, params, vararg, body, env, interp, name):
        self.params = params
        self.vararg = vararg
        self.body = body
        self.env = env
        self.interp = interp
        self.name = name

    def __call__(self, *args):
        return self.interp.call_function(self, list(args))

    def __repr__(self):
        return "function: %s" % self.name


class Env(object):
    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def get(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        return None

    def has(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return True
            env = env.parent
        return False

    def set_existing(self, name, value):
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return True
            env = env.parent
        return False

    def declare(self, name, value):
        self.vars[name] = value


# --------------------------------------------------------- helpers de tipo
def lua_type(v):
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, float) or isinstance(v, int):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, LuaTable):
        return "table"
    if callable(v):
        return "function"
    return "userdata"


def truthy(v):
    return not (v is None or v is False)


def tostring(v):
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        if v != v:
            return "nan"
        if v in (float("inf"), float("-inf")):
            return "inf" if v > 0 else "-inf"
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return ("%.14g" % v)
    if isinstance(v, str):
        return v
    return repr(v)


def tonumber(v, base=None):
    if base is not None:
        try:
            return float(int(str(v).strip(), int(base)))
        except Exception:
            return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            try:
                return float(int(v.strip(), 0))
            except Exception:
                return None
    return None


def arith_num(v, op):
    n = tonumber(v) if not isinstance(v, bool) else None
    if n is None:
        raise LuaError("tentativa de fazer aritmetica ('%s') com %s" % (op, lua_type(v)))
    return n


# ------------------------------------------------------------- Interpreter
class Interpreter(object):
    def __init__(self, print_fn=None):
        self.globals = Env()
        self.print_fn = print_fn or (lambda s: None)
        self.instruction_budget = None
        self._steps = 0
        # Ultima linha do script (chunk atualmente executando) que a gente
        # tocou - usado so pra apontar a linha certa quando um erro estoura
        # sem numero de linha embutido na mensagem (ex.: "tentativa de
        # indexar valor nil"). Nao e 100% preciso (uma linha pode ter varias
        # sub-expressoes), mas cobre a grande maioria dos casos na pratica.
        self.current_line = 0
        self.install_stdlib()

    # ---------- API publica ----------
    def set_global(self, name, value):
        self.globals.declare(name, value)

    def get_global(self, name):
        return self.globals.get(name)

    def execute(self, source, chunkname="chunk"):
        ast = parse(source, chunkname)
        env = Env(self.globals)
        try:
            self.exec_block(ast, env)
        except ReturnSignal as r:
            return r.values
        return []

    def call_function(self, func, args):
        if isinstance(func, LuaFunction):
            env = Env(func.env)
            for i, p in enumerate(func.params):
                env.declare(p, args[i] if i < len(args) else None)
            if func.vararg:
                env.declare("...", args[len(func.params):])
            try:
                self.exec_block(func.body, env)
            except ReturnSignal as r:
                return r.values
            return []
        if callable(func):
            return as_list(func(*args))
        raise LuaError("tentativa de chamar um valor do tipo %s" % lua_type(func))

    def call(self, func, *args):
        return self.call_function(func, list(args))

    # ---------- execucao ----------
    def exec_block(self, block, env):
        for stat in block[1]:
            self.exec_stat(stat, env)

    def exec_stat(self, st, env):
        kind = st[0]
        self.current_line = st[-1]
        if self.instruction_budget is not None:
            self._steps += 1
            if self._steps > self.instruction_budget:
                raise LuaError("limite de execucao atingido (loop infinito?)")
        if kind == "callstat":
            self.eval_multi(st[1], env)
        elif kind == "local":
            values = self.eval_list(st[2], env, len(st[1]))
            for i, name in enumerate(st[1]):
                env.declare(name, values[i])
        elif kind == "assign":
            values = self.eval_list(st[2], env, len(st[1]))
            for i, target in enumerate(st[1]):
                self.assign(target, values[i], env)
        elif kind == "localfunc":
            env.declare(st[1], None)
            env.vars[st[1]] = self.eval(st[2], env)
        elif kind == "if":
            for cond, body in st[1]:
                if truthy(self.eval(cond, env)):
                    self.exec_block(body, Env(env))
                    return
            if st[2] is not None:
                self.exec_block(st[2], Env(env))
        elif kind == "while":
            while truthy(self.eval(st[1], env)):
                try:
                    self.exec_block(st[2], Env(env))
                except BreakSignal:
                    break
                if self.instruction_budget is not None:
                    self._steps += 1
                    if self._steps > self.instruction_budget:
                        raise LuaError("limite de execucao atingido (loop infinito?)")
        elif kind == "repeat":
            while True:
                scope = Env(env)
                try:
                    self.exec_block(st[1], scope)
                except BreakSignal:
                    break
                if truthy(self.eval(st[2], scope)):
                    break
                if self.instruction_budget is not None:
                    self._steps += 1
                    if self._steps > self.instruction_budget:
                        raise LuaError("limite de execucao atingido (loop infinito?)")
        elif kind == "fornum":
            start = arith_num(self.eval(st[2], env), "for")
            stop = arith_num(self.eval(st[3], env), "for")
            step = arith_num(self.eval(st[4], env), "for") if st[4] is not None else 1.0
            if step == 0:
                raise LuaError("'for' step igual a zero")
            i = start
            while (step > 0 and i <= stop) or (step < 0 and i >= stop):
                scope = Env(env)
                scope.declare(st[1], i)
                try:
                    self.exec_block(st[5], scope)
                except BreakSignal:
                    break
                i += step
                if self.instruction_budget is not None:
                    self._steps += 1
                    if self._steps > self.instruction_budget:
                        raise LuaError("limite de execucao atingido (loop infinito?)")
        elif kind == "forin":
            values = self.eval_list(st[2], env, 3)
            func, state, control = values[0], values[1], values[2]
            while True:
                res = as_list(self.call_function(func, [state, control]))
                if not res or res[0] is None:
                    break
                control = res[0]
                scope = Env(env)
                for i, name in enumerate(st[1]):
                    scope.declare(name, res[i] if i < len(res) else None)
                try:
                    self.exec_block(st[3], scope)
                except BreakSignal:
                    break
                if self.instruction_budget is not None:
                    self._steps += 1
                    if self._steps > self.instruction_budget:
                        raise LuaError("limite de execucao atingido (loop infinito?)")
        elif kind == "do":
            self.exec_block(st[1], Env(env))
        elif kind == "break":
            raise BreakSignal()
        elif kind == "return":
            raise ReturnSignal(self.eval_list_open(st[1], env))
        else:
            raise LuaError("comando desconhecido: %s" % kind)

    def assign(self, target, value, env):
        if target[0] == "name":
            name = target[1]
            if not env.set_existing(name, value):
                self.globals.declare(name, value)
            return
        if target[0] == "index":
            obj = self.eval(target[1], env)
            key = self.eval(target[2], env)
            if isinstance(obj, LuaTable):
                if obj.metatable is not None and obj.raw_get(key) is None:
                    ni = obj.metatable.hash.get("__newindex")
                    if callable(ni):
                        ni(obj, key, value)
                        return
                obj.set(key, value)
                return
            if hasattr(obj, "lua_newindex"):
                obj.lua_newindex(key, value)
                return
            if obj is None:
                raise LuaError("tentativa de indexar valor nil")
            setattr(obj, str(key), value)
            return
        raise LuaError("alvo de atribuicao invalido")

    # ---------- expressoes ----------
    def eval_list(self, exprs, env, want):
        values = self.eval_list_open(exprs, env)
        while len(values) < want:
            values.append(None)
        return values

    def eval_list_open(self, exprs, env):
        values = []
        for i, e in enumerate(exprs):
            if i == len(exprs) - 1:
                values.extend(as_list(self.eval_multi(e, env)))
            else:
                values.append(self.eval(e, env))
        return values

    def eval_multi(self, e, env):
        if e[0] in ("call", "methcall"):
            return self.do_call(e, env)
        if e[0] == "vararg":
            return list(env.get("...") or [])
        return [self.eval(e, env)]

    def eval(self, e, env):
        kind = e[0]
        if kind == "const":
            return e[1]
        if kind == "name":
            return env.get(e[1])
        if kind == "paren":
            return self.eval(e[1], env)
        if kind == "index":
            obj = self.eval(e[1], env)
            key = self.eval(e[2], env)
            self.current_line = e[-1]
            return self.index(obj, key, e)
        if kind in ("call", "methcall"):
            self.current_line = e[-1]
            return first(self.do_call(e, env))
        if kind == "function":
            return LuaFunction(e[1], e[2], e[3], env, self, e[4])
        if kind == "table":
            arr = []
            exprs = e[1]
            for i, item in enumerate(exprs):
                if i == len(exprs) - 1:
                    arr.extend(as_list(self.eval_multi(item, env)))
                else:
                    arr.append(self.eval(item, env))
            t = LuaTable(arr)
            for kexp, vexp in e[2]:
                t.set(self.eval(kexp, env), self.eval(vexp, env))
            return t
        if kind == "binop":
            self.current_line = e[-1]
            return self.binop(e[1], e[2], e[3], env)
        if kind == "unop":
            self.current_line = e[-1]
            return self.unop(e[1], self.eval(e[2], env))
        if kind == "vararg":
            va = env.get("...") or []
            return va[0] if va else None
        raise LuaError("expressao desconhecida: %s" % kind)

    def index(self, obj, key, e=None):
        if isinstance(obj, LuaTable):
            return obj.get(key)
        if isinstance(obj, str):
            slib = self.globals.get("string")
            return slib.get(key) if isinstance(slib, LuaTable) else None
        if obj is None:
            name = ""
            if e is not None and e[1][0] == "name":
                name = " ('%s')" % e[1][1]
            elif e is not None and e[1][0] == "index" and e[1][2][0] == "const":
                name = " ('%s')" % e[1][2][1]
            raise LuaError("tentativa de indexar valor nil%s" % name)
        if hasattr(obj, "lua_index"):
            return obj.lua_index(key)
        try:
            return getattr(obj, str(key))
        except AttributeError:
            return None

    def do_call(self, e, env):
        if e[0] == "methcall":
            obj = self.eval(e[1], env)
            func = self.index(obj, e[2])
            args = [obj] + self.eval_list_open(e[3], env)
        else:
            func = self.eval(e[1], env)
            args = self.eval_list_open(e[2], env)
        if func is None:
            raise LuaError("tentativa de chamar valor nil (linha %d)" % e[-1])
        if isinstance(func, LuaTable):
            mt = func.metatable
            call = mt.hash.get("__call") if mt else None
            if call is not None:
                return as_list(self.call_function(call, [func] + args))
        if hasattr(func, "lua_call"):
            return as_list(func.lua_call(args))
        return as_list(self.call_function(func, args))

    def binop(self, op, lexp, rexp, env):
        if op == "and":
            left = self.eval(lexp, env)
            return self.eval(rexp, env) if truthy(left) else left
        if op == "or":
            left = self.eval(lexp, env)
            return left if truthy(left) else self.eval(rexp, env)
        a = self.eval(lexp, env)
        b = self.eval(rexp, env)
        if op == "..":
            if isinstance(a, (str, float, int)) and isinstance(b, (str, float, int)) \
                    and not isinstance(a, bool) and not isinstance(b, bool):
                return tostring(a) + tostring(b)
            raise LuaError("tentativa de concatenar valor %s" % lua_type(a if not isinstance(a, str) else b))
        if op == "==":
            return self.eq(a, b)
        if op == "~=":
            return not self.eq(a, b)
        if op in ("<", ">", "<=", ">="):
            if isinstance(a, str) and isinstance(b, str):
                pass
            else:
                a, b = arith_num(a, op), arith_num(b, op)
            if op == "<":
                return a < b
            if op == ">":
                return a > b
            if op == "<=":
                return a <= b
            return a >= b
        x, y = arith_num(a, op), arith_num(b, op)
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            if y == 0:
                raise LuaError("tentativa de dividir por zero")
            return x / y
        if op == "%":
            if y == 0:
                raise LuaError("tentativa de calcular '%%' com zero")
            return x - math.floor(x / y) * y
        if op == "//":
            if y == 0:
                raise LuaError("tentativa de dividir por zero")
            return float(math.floor(x / y))
        if op == "^":
            try:
                r = x ** y
            except Exception:
                raise LuaError("resultado invalido em '^'")
            if isinstance(r, complex):
                raise LuaError("resultado invalido em '^'")
            return float(r)
        if op == "&":
            return float(int(x) & int(y))
        if op == "|":
            return float(int(x) | int(y))
        if op == "~":
            return float(int(x) ^ int(y))
        if op == "<<":
            return float(int(x) << int(y))
        if op == ">>":
            return float(int(x) >> int(y))
        raise LuaError("operador desconhecido: %s" % op)

    @staticmethod
    def eq(a, b):
        if isinstance(a, bool) or isinstance(b, bool):
            return a is b
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) == float(b)
        return a is b if isinstance(a, LuaTable) else a == b

    def unop(self, op, v):
        if op == "-":
            return -arith_num(v, "-")
        if op == "not":
            return not truthy(v)
        if op == "#":
            if isinstance(v, str):
                return float(len(v))
            if isinstance(v, LuaTable):
                return float(v.length())
            raise LuaError("tentativa de obter tamanho de %s" % lua_type(v))
        if op == "~":
            return float(~int(arith_num(v, "~")))
        raise LuaError("operador unario desconhecido: %s" % op)

    # ---------- biblioteca padrao ----------
    def install_stdlib(self):
        interp = self
        g = self.globals

        def _print(*args):
            interp.print_fn(" ".join(tostring(a) for a in args))

        g.declare("print", _print)
        g.declare("type", lambda v=None: lua_type(v))
        g.declare("tostring", lambda v=None: tostring(v))
        g.declare("tonumber", lambda v=None, base=None: tonumber(v, base))

        def _error(msg=None, level=None):
            raise LuaError(msg if msg is not None else "erro")
        g.declare("error", _error)

        def _assert(v=None, msg=None, *rest):
            if not truthy(v):
                raise LuaError(msg or "assertion failed!")
            return [v, msg] + list(rest)
        g.declare("assert", _assert)

        def _pcall(f=None, *args):
            try:
                res = as_list(interp.call_function(f, list(args)))
                return [True] + res
            except LuaError as ex:
                return [False, ex.value]
            except Exception as ex:  # noqa
                return [False, str(ex)]
        g.declare("pcall", _pcall)

        def _ipairs(t=None):
            if not isinstance(t, LuaTable):
                raise LuaError("ipairs espera uma tabela")

            def it(tbl, i):
                i = (i or 0) + 1
                v = tbl.raw_get(float(i))
                if v is None:
                    return [None]
                return [float(i), v]
            return [it, t, 0.0]
        g.declare("ipairs", _ipairs)

        def _next(t=None, key=None):
            keys = list(t.hash.keys())
            if key is None:
                if not keys:
                    return [None]
                k = keys[0]
                return [k, t.hash[k]]
            try:
                i = keys.index(LuaTable.norm(key))
            except ValueError:
                return [None]
            if i + 1 >= len(keys):
                return [None]
            k = keys[i + 1]
            return [k, t.hash[k]]
        g.declare("next", _next)
        g.declare("pairs", lambda t=None: [_next, t, None])
        g.declare("rawget", lambda t=None, k=None: t.raw_get(k))
        g.declare("rawset", lambda t=None, k=None, v=None: (t.set(k, v), t)[1])
        g.declare("rawequal", lambda a=None, b=None: a is b)
        g.declare("unpack", lambda t=None, *a: t.ipairs_list())
        g.declare("select", lambda n=None, *args:
                  float(len(args)) if n == "#" else list(args[int(n) - 1:]))

        def _setmetatable(t=None, mt=None):
            t.metatable = mt
            return t
        g.declare("setmetatable", _setmetatable)
        g.declare("getmetatable", lambda t=None: t.metatable if isinstance(t, LuaTable) else None)

        # math
        m = LuaTable()
        m.set("pi", math.pi)
        m.set("huge", float("inf"))
        for name, fn in [
            ("sqrt", math.sqrt), ("sin", math.sin), ("cos", math.cos), ("tan", math.tan),
            ("asin", math.asin), ("acos", math.acos), ("exp", math.exp),
            ("floor", lambda x: float(math.floor(x))), ("ceil", lambda x: float(math.ceil(x))),
            ("abs", abs), ("rad", math.radians), ("deg", math.degrees),
        ]:
            m.set(name, (lambda f: lambda x=0: float(f(arith_num(x, "math"))))(fn))
        m.set("atan", lambda y=0, x=None: float(math.atan2(y, x) if x is not None else math.atan(y)))
        m.set("log", lambda x=1, b=None: float(math.log(x, b) if b else math.log(x)))
        m.set("pow", lambda x=0, y=0: float(x ** y))
        m.set("fmod", lambda x=0, y=1: float(math.fmod(x, y)))
        m.set("max", lambda *a: float(max(a)))
        m.set("min", lambda *a: float(min(a)))
        m.set("random", lambda a=None, b=None: (
            float(random.random()) if a is None else
            float(random.randint(1, int(a))) if b is None else
            float(random.randint(int(a), int(b)))))
        m.set("randomseed", lambda s=0: random.seed(s))
        g.declare("math", m)

        # string
        s = LuaTable()
        s.set("len", lambda v="": float(len(tostring(v))))
        s.set("upper", lambda v="": tostring(v).upper())
        s.set("lower", lambda v="": tostring(v).lower())
        s.set("rep", lambda v="", n=0, sep="": (sep or "").join([tostring(v)] * int(n or 0)))
        s.set("reverse", lambda v="": tostring(v)[::-1])
        s.set("byte", lambda v="", i=1: float(ord(tostring(v)[int(i) - 1])))
        s.set("char", lambda *a: "".join(chr(int(x)) for x in a))

        def _sub(v="", i=1, j=-1):
            v = tostring(v)
            i = int(i or 1)
            j = int(j if j is not None else -1)
            n = len(v)
            if i < 0:
                i = max(n + i + 1, 1)
            elif i == 0:
                i = 1
            if j < 0:
                j = n + j + 1
            return v[i - 1:j]
        s.set("sub", _sub)

        def _format(fmt="", *args):
            vals = []
            for a in args:
                if isinstance(a, float) and a.is_integer():
                    vals.append(int(a))
                elif isinstance(a, (float, int)) and not isinstance(a, bool):
                    vals.append(a)
                else:
                    vals.append(tostring(a))
            try:
                return tostring(fmt) % tuple(vals)
            except Exception as ex:
                raise LuaError("string.format: %s" % ex)
        s.set("format", _format)

        def _find(v="", pat="", init=1, plain=None):
            v = tostring(v)
            idx = v.find(tostring(pat), max(int(init) - 1, 0))
            if idx < 0:
                return [None]
            return [float(idx + 1), float(idx + len(tostring(pat)))]
        s.set("find", _find)
        s.set("gsub", lambda v="", pat="", rep="", n=None:
              [tostring(v).replace(tostring(pat), tostring(rep)), 0.0])

        def _split(v="", sep=","):
            return LuaTable([p for p in tostring(v).split(tostring(sep))])
        s.set("split", _split)
        g.declare("string", s)

        # table
        t = LuaTable()

        def _insert(tbl=None, a=None, b=None):
            if b is None:
                tbl.set(float(tbl.length() + 1), a)
            else:
                pos = int(a)
                n = tbl.length()
                for i in range(n, pos - 1, -1):
                    tbl.set(float(i + 1), tbl.raw_get(float(i)))
                tbl.set(float(pos), b)
        t.set("insert", _insert)

        def _remove(tbl=None, pos=None):
            n = tbl.length()
            if n == 0:
                return None
            pos = n if pos is None else int(pos)
            val = tbl.raw_get(float(pos))
            for i in range(pos, n):
                tbl.set(float(i), tbl.raw_get(float(i + 1)))
            tbl.set(float(n), None)
            return val
        t.set("remove", _remove)
        t.set("concat", lambda tbl=None, sep="", *a:
              tostring(sep).join(tostring(x) for x in tbl.ipairs_list()))
        t.set("unpack", lambda tbl=None, *a: tbl.ipairs_list())

        def _sort(tbl=None, comp=None):
            items = tbl.ipairs_list()
            if comp is None:
                items.sort(key=lambda x: (isinstance(x, str), x))
            else:
                import functools
                items.sort(key=functools.cmp_to_key(
                    lambda a, b: -1 if truthy(first(interp.call_function(comp, [a, b]))) else 1))
            for i, v in enumerate(items):
                tbl.set(float(i + 1), v)
        t.set("sort", _sort)
        g.declare("table", t)

        # os
        o = LuaTable()
        o.set("time", lambda *a: float(time.time()))
        o.set("clock", lambda *a: float(time.time()))
        o.set("date", lambda fmt="%c", *a: time.strftime(tostring(fmt).replace("*t", "%c")))
        g.declare("os", o)

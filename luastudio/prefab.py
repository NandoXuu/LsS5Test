# -*- coding: utf-8 -*-
"""Instanciar cenas (prefabs) a partir de outras cenas.

Uma "cena" aqui e um arquivo .lua que devolve uma tabela:

    -- Enemy.lua
    return {
        Objects = {
            { Class = "image", Name = "Body", Source = "Assets/enemy.png",
              Position = {0, 0}, Size = {64, 64} },
            { Class = "label", Name = "Name", Text = "Enemy" },
        },
        Script = "Scripts/Enemy.lua",   -- opcional
    }

Uso em qualquer outro script:

    local e = scene.instantiate("Enemy", { Position = {400, 300}, Scale = {2, 2} })
    local e = Instance.Enemy{ Position = {400, 300} }       -- mesma coisa
    local corpo = Instance.Enemy.Body{ Position = {50, 50} } -- so UM objeto da cena

O que volta de `scene.instantiate` e uma SceneInstance (um "grupo"):
    e.Position / e.Scale / e.Visible    mexem em todos os objetos de uma vez
    e.Body, e.Name ...                   acessam cada objeto pelo Name
                                         (e.GroupName = nome do grupo em si)
    e:Find("Body"), e:Move(dx, dy), e:MoveTo(x, y), e:Destroy()
    e.Alive                              false depois do Destroy
    qualquer outro campo (e.Health = 3)  fica guardado no grupo

As posicoes dentro do Objects sao LOCAIS (relativas ao Position do grupo).
"""

import os

from .lua import LuaTable, LuaError, tostring, truthy
from .api import Instance, to_vec, vec_table, CreateRoot

# chaves que o `scene.instantiate(nome, {...})` entende como do GRUPO
_GROUP_KEYS = ("Position", "Scale", "Visible", "Name")


def _ci_get(table, key):
    """table.get(key) ignorando maiusculas/minusculas."""
    v = table.get(key)
    if v is not None:
        return v
    low = key.lower()
    for k, val in table.items():
        if isinstance(k, str) and k.lower() == low:
            return val
    return None


class SceneInstance(object):
    """Grupo de objetos criado por scene.instantiate."""

    def __init__(self, manager, scene_name, uid, display_name):
        self.manager = manager
        self.scene_name = scene_name
        self.uid = uid
        self.name = display_name
        self.alive = True
        self.children = []          # [(nome_curto, Instance, local_pos, local_scale)]
        self.by_short = {}          # nome_curto (minusculo) -> Instance
        self.pos = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)
        self.visible = True
        self.fields = {}

    # ---- layout ----
    def _add(self, short, inst, local_pos, local_scale):
        self.children.append((short, inst, local_pos, local_scale))
        self.by_short[short.lower()] = inst

    def _relayout(self):
        px, py, pz = self.pos
        sx, sy, sz = self.scale
        for _short, inst, lp, ls in self.children:
            if not inst.alive:
                continue
            inst.set_prop("Position", vec_table(px + lp[0] * sx, py + lp[1] * sy, pz + lp[2] * sz))
            inst.set_prop("Scale", vec_table(ls[0] * sx, ls[1] * sy, ls[2] * sz))

    def _apply_visible(self):
        for _short, inst, _lp, _ls in self.children:
            if inst.alive:
                inst.set_prop("Visible", self.visible)

    # ---- Lua ----
    def lua_index(self, key):
        key = str(key)
        if key == "Position":
            return vec_table(*self.pos)
        if key == "Scale":
            return vec_table(*self.scale)
        if key == "Visible":
            return self.visible
        if key == "Name":
            # um filho chamado "Name" (ex.: label) tem prioridade; o nome do
            # grupo fica sempre disponivel em `GroupName`
            return self.by_short.get("name", self.name)
        if key == "GroupName":
            return self.name
        if key == "Alive":
            return self.alive
        if key == "SceneName":
            return self.scene_name
        if key == "Children":
            t = LuaTable()
            for i, (_s, inst, _lp, _ls) in enumerate(self.children):
                t.set(float(i + 1), inst)
            return t
        method = getattr(self, "m_" + key, None)
        if method is not None:
            return method
        if key in self.fields:
            return self.fields[key]
        child = self.by_short.get(key.lower())
        if child is not None:
            return child
        return None

    def lua_newindex(self, key, value):
        key = str(key)
        if key == "Position":
            self.pos = to_vec(value, self.pos)
            self._relayout()
        elif key == "Scale":
            self.scale = to_vec(value, (1.0, 1.0, 1.0))
            self._relayout()
        elif key == "Visible":
            self.visible = truthy(value)
            self._apply_visible()
        elif key == "Name":
            self.name = tostring(value)
        elif key in ("Alive", "SceneName", "Children", "GroupName"):
            raise LuaError("'%s' e somente leitura" % key)
        else:
            if value is None:
                self.fields.pop(key, None)
            else:
                self.fields[key] = value

    def m_Find(self, _self=None, name=None):
        return self.by_short.get(tostring(name).lower())

    def m_Move(self, _self=None, dx=0, dy=0, dz=0):
        x, y, z = self.pos
        self.pos = (x + float(dx or 0), y + float(dy or 0), z + float(dz or 0))
        self._relayout()

    def m_MoveTo(self, _self=None, x=0, y=0, z=0):
        self.pos = (float(x or 0), float(y or 0), float(z or 0))
        self._relayout()

    def m_Destroy(self, *_a):
        if not self.alive:
            return
        self.alive = False
        for _short, inst, _lp, _ls in self.children:
            if inst.alive:
                inst.m_Destroy()
        self.children = []
        self.by_short = {}
        self.manager.forget(self)

    def __repr__(self):
        return "<SceneInstance %s>" % self.name


class _SceneProxy(object):
    """`Instance.Enemy` -> chamavel (cena inteira) e indexavel (um objeto so)."""

    def __init__(self, manager, scene_name):
        self.manager = manager
        self.scene_name = scene_name

    def lua_call(self, args):
        spec = args[0] if args else None
        return [self.manager.instantiate(self.scene_name, spec)]

    def lua_index(self, key):
        return _ObjectFactory(self.manager, self.scene_name, tostring(key))


class _ObjectFactory(object):
    """`Instance.Enemy.Body` -> chamavel: cria so esse objeto da cena."""

    def __init__(self, manager, scene_name, obj_name):
        self.manager = manager
        self.scene_name = scene_name
        self.obj_name = obj_name

    def lua_call(self, args):
        spec = args[0] if args else None
        return [self.manager.instantiate_object(self.scene_name, self.obj_name, spec)]

    def lua_index(self, key):
        raise LuaError("Instance.%s.%s e uma fabrica: chame com Instance.%s.%s{ ... }"
                       % (self.scene_name, self.obj_name, self.scene_name, self.obj_name))


class InstanceRoot(object):
    """Global `Instance`: `Instance.<Cena>` ou `Instance.<Cena>.<Objeto>`."""

    def __init__(self, manager):
        self.manager = manager

    def lua_index(self, key):
        return _SceneProxy(self.manager, tostring(key))

    def lua_newindex(self, key, value):
        raise LuaError("Instance e somente leitura: use Instance.<Cena>{ ... }")

    def lua_call(self, args):
        raise LuaError("use Instance.<Cena>{ ... } ou scene.instantiate(\"Cena\", { ... })")


class PrefabManager(object):
    def __init__(self, runtime):
        self.runtime = runtime
        self.definitions = {}       # chave -> tabela Lua devolvida pelo .lua da cena
        self.counters = {}          # nome da cena -> proximo numero
        self.live = []              # SceneInstance vivas
        self._stack = []            # protecao contra cena que instancia a si mesma

    def reset(self):
        self.definitions = {}
        self.counters = {}
        self.live = []
        self._stack = []

    def forget(self, group):
        if group in self.live:
            self.live.remove(group)

    # ---------------------------------------------------------- definicao
    def _candidates(self, name):
        base = name[:-4] if name.lower().endswith(".lua") else name
        base = base.replace("\\", "/")
        return base, [base + ".lua", base + ".scene.lua"]

    def _read_disk(self, rel):
        p = self.runtime.resolve(rel)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    return fh.read()
            except Exception:
                return None
        return None

    def _find_source(self, name):
        base, names = self._candidates(name)
        scripts = self.runtime.project_scripts
        lowered = dict((k.lower(), k) for k in scripts)
        for cand in names:
            if cand in scripts:
                return cand, scripts[cand]
            k = lowered.get(cand.lower())
            if k is not None:
                return k, scripts[k]
        # pastas de cenas no disco (Source do projeto / .Lsp)
        for folder in ("Scenes", "scenes", "Cenas", "cenas", ""):
            for cand in names:
                rel = os.path.join(folder, cand) if folder else cand
                src = self._read_disk(rel)
                if src is not None:
                    return rel, src
        return None, None

    def definition(self, name):
        name = tostring(name)
        key = name.lower()
        if key in self.definitions:
            return self.definitions[key]
        chunk, src = self._find_source(name)
        if src is None:
            raise LuaError("scene.instantiate: cena '%s' nao encontrada "
                           "(procurei %s.lua em Scripts/ e em Scenes/)" % (name, name))
        if key in self._stack:
            raise LuaError("scene.instantiate: a cena '%s' se instancia a si mesma" % name)
        self._stack.append(key)
        try:
            result = self.runtime.interp.execute(src, chunk)
        finally:
            self._stack.pop()
        d = result[0] if result else None
        if not isinstance(d, LuaTable):
            raise LuaError("scene.instantiate: '%s' precisa fazer `return { Objects = {...} }`" % chunk)
        objs = _ci_get(d, "Objects")
        if objs is not None and not isinstance(objs, LuaTable):
            raise LuaError("scene.instantiate: Objects de '%s' precisa ser uma lista" % name)
        self.definitions[key] = d
        return d

    @staticmethod
    def _entries(d):
        objs = _ci_get(d, "Objects")
        return objs.ipairs_list() if isinstance(objs, LuaTable) else []

    # ---------------------------------------------------------- instanciar
    def _unique_name(self, scene_name):
        n = self.counters.get(scene_name, 0) + 1
        self.counters[scene_name] = n
        return n

    def _make_child(self, entry, prefix, cls_default="frame"):
        if not isinstance(entry, LuaTable):
            raise LuaError("scene.instantiate: cada item de Objects precisa ser uma tabela")
        cls = _ci_get(entry, "Class")
        cls = tostring(cls).lower() if cls is not None else cls_default
        if cls not in CreateRoot.ALL:
            raise LuaError("scene.instantiate: Class '%s' desconhecida (validas: %s)"
                           % (cls, ", ".join(CreateRoot.ALL)))
        short = _ci_get(entry, "Name")
        short = tostring(short) if short is not None else "%s_%d" % (cls, len(prefix))
        spec = LuaTable()
        local_pos = (0.0, 0.0, 0.0)
        local_scale = (1.0, 1.0, 1.0)
        for k, v in entry.items():
            if not isinstance(k, str) or k in ("Class", "Name"):
                continue
            if k == "Position":
                local_pos = to_vec(v, (0.0, 0.0, 0.0))
            elif k == "Scale":
                local_scale = to_vec(v, (1.0, 1.0, 1.0))
            else:
                spec.set(k, v)
        return cls, short, spec, local_pos, local_scale

    def _spawn(self, group, entry):
        sc = self.runtime.scene
        cls, short, spec, lp, ls = self._make_child(entry, group.children)
        full = "%s.%s" % (group.name, short)
        inst = sc.create(cls, full, spec)
        inst.set_prop("Name", full)
        group._add(short, inst, lp, ls)
        return inst

    def _split_overrides(self, group, overrides):
        if overrides is None:
            return
        if not isinstance(overrides, LuaTable):
            raise LuaError("scene.instantiate: o 2o argumento precisa ser uma tabela { ... }")
        for k, v in overrides.items():
            if not isinstance(k, str):
                continue
            if k in _GROUP_KEYS:
                group.lua_newindex(k, v)
            else:
                group.fields[k] = v

    def instantiate(self, name, overrides=None):
        name = tostring(name)
        d = self.definition(name)
        n = self._unique_name(name)
        display = None
        if isinstance(overrides, LuaTable) and overrides.get("Name") is not None:
            display = tostring(overrides.get("Name"))
        group = SceneInstance(self, name, n, display or "%s_%d" % (name, n))
        # evita colisao de nome no by_name da cena
        while group.name in self.runtime.scene.by_name or any(
                o.startswith(group.name + ".") for o in self.runtime.scene.by_name):
            n = self._unique_name(name)
            group.name = "%s_%d" % (name, n)
        # valores iniciais do grupo ANTES de criar os filhos (layout calculado 1x)
        self._split_overrides(group, overrides)
        for entry in self._entries(d):
            self._spawn(group, entry)
        group._relayout()
        group._apply_visible()
        self.live.append(group)
        self._run_script(d, group)
        return group

    def instantiate_object(self, scene_name, obj_name, overrides=None):
        """`Instance.Enemy.Body{...}`: cria so um objeto da cena."""
        d = self.definition(scene_name)
        wanted = obj_name.lower()
        for entry in self._entries(d):
            if isinstance(entry, LuaTable):
                nm = _ci_get(entry, "Name")
                if nm is not None and tostring(nm).lower() == wanted:
                    break
        else:
            raise LuaError("Instance.%s.%s: a cena '%s' nao tem um objeto chamado '%s'"
                           % (scene_name, obj_name, scene_name, obj_name))
        n = self._unique_name("%s.%s" % (scene_name, obj_name))
        cls, short, spec, lp, ls = self._make_child(entry, [])
        pos, scale = lp, ls
        if isinstance(overrides, LuaTable):
            for k, v in overrides.items():
                if not isinstance(k, str):
                    continue
                if k == "Position":
                    pos = to_vec(v, lp)
                elif k == "Scale":
                    scale = to_vec(v, ls)
                elif k != "Name":
                    spec.set(k, v)
        nm = overrides.get("Name") if isinstance(overrides, LuaTable) else None
        full = tostring(nm) if nm is not None else "%s.%s_%d" % (scene_name, short, n)
        inst = self.runtime.scene.create(cls, full, spec)
        inst.set_prop("Position", vec_table(*pos))
        inst.set_prop("Scale", vec_table(*scale))
        return inst

    # ---------------------------------------------------------- script
    def _script_source(self, path):
        path = tostring(path).replace("\\", "/")
        scripts = self.runtime.project_scripts
        base = os.path.basename(path)
        # 1) caminho exato no disco (Scripts/Enemy.lua, Scenes/Enemy.lua ...)
        src = self._read_disk(path)
        if src is not None:
            return path, src
        # 2) script do projeto pelo nome do arquivo
        lowered = dict((k.lower(), k) for k in scripts)
        k = lowered.get(base.lower())
        if k is not None:
            return k, scripts[k]
        return None, None

    def _run_script(self, d, group):
        path = _ci_get(d, "Script")
        if path is None:
            return
        chunk, src = self._script_source(path)
        if src is None:
            self.runtime.log("[scene] script '%s' da cena '%s' nao encontrado"
                             % (tostring(path), group.scene_name))
            return
        interp = self.runtime.interp
        # `self` vira local do script (mesma linha -> numeracao de linhas intacta)
        interp.set_global("__scene_instance__", group)
        try:
            result = interp.execute("local self = __scene_instance__ " + src, chunk)
        finally:
            interp.set_global("__scene_instance__", None)
        # o script pode devolver uma funcao: return function(self) ... end
        fn = result[0] if result else None
        if fn is not None and not isinstance(fn, (LuaTable, str, bool, float, int)):
            interp.call_function(fn, [group])

# -*- coding: utf-8 -*-
"""
luastudio.plugins.manifest
============================

Parsing, validação e utilitários de versão para o ``manifest.json`` de um
plugin da LuaStudio.

Um manifest válido é convertido num objeto :class:`Manifest`, que expõe os
dados já normalizados (uuid em minúsculas, versões, listas de dependências
e conflitos etc.) e uma lista de :class:`PluginObject` (as entradas dentro
de ``"objects"``, ex.: ``Ui-lp3``, ``Scripting-v1``, ``Motor-lsx-1``...).

Este módulo não sabe nada sobre ZIP/instalação/hooks - só entende o
manifest em si, para poder ser testado isoladamente.
"""

import json
import re
import uuid as uuid_mod

from .errors import ManifestError

MANIFEST_FILENAME = "manifest.json"
CURRENT_MANIFEST_VERSION = 1

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# operadores de compatibilidade suportados em "engine_version": ">=7.0.0"
_VERSION_OP_RE = re.compile(r"^\s*(>=|<=|==|!=|>|<|~=)?\s*([0-9][0-9A-Za-z.\-+]*)\s*$")


# ---------------------------------------------------------------------------
# Versão (semver simplificado, sem dependências externas)
# ---------------------------------------------------------------------------

def parse_version(text):
    """Converte "1.2.3" (ou "1.2.3-beta") numa tupla comparável.

    Partes não numéricas do "patch" são ignoradas na comparação, mas a
    tupla sempre tem tamanho 3 (major, minor, patch) para permitir
    comparações estáveis.
    """
    if text is None:
        return (0, 0, 0)
    core = str(text).strip().split("+")[0].split("-")[0]
    parts = core.split(".")
    nums = []
    for p in parts[:3]:
        m = re.match(r"\d+", p)
        nums.append(int(m.group(0)) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _cmp(a, b):
    return (a > b) - (a < b)


def version_satisfies(version, constraint):
    """Verifica se ``version`` ("7.2.0") satisfaz ``constraint`` (">=7.0.0").

    Constraints suportadas: ``>=``, ``<=``, ``>``, ``<``, ``==``, ``!=``,
    ``~=`` (compatível: mesmo major.minor, >= no patch), ou sem operador
    (equivale a ``==``). ``"*"``/``"x"``/vazio sempre satisfaz.
    """
    if constraint is None:
        return True
    constraint = str(constraint).strip()
    if constraint in ("", "*", "x", "any"):
        return True

    m = _VERSION_OP_RE.match(constraint)
    if not m:
        # constraint em formato desconhecido - não bloqueia a instalação,
        # mas também não finge que validou algo.
        return True
    op, target_text = m.group(1) or "==", m.group(2)

    v = parse_version(version)
    t = parse_version(target_text)
    c = _cmp(v, t)

    if op == ">=":
        return c >= 0
    if op == "<=":
        return c <= 0
    if op == ">":
        return c > 0
    if op == "<":
        return c < 0
    if op == "==":
        return c == 0
    if op == "!=":
        return c != 0
    if op == "~=":
        return v[0] == t[0] and v[1] == t[1] and v[2] >= t[2]
    return True


def is_valid_uuid(value):
    if not value or not isinstance(value, str):
        return False
    return bool(_UUID_RE.match(value.strip()))


def normalize_uuid(value):
    return str(value).strip().lower()


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class PluginObject(object):
    """Um objeto de modificação dentro do manifest (ex.: "Ui-lp3").

    ``object_type`` é a chave usada no manifest (ex.: ``"Ui-lp3"``,
    ``"Scripting-v1"``, ``"Motor-lsx-1"``, ou qualquer tipo futuro). O
    Plugin Manager não faz nada específico de cada tipo: ele repassa cada
    ``PluginObject`` para o handler registrado daquele tipo (veja
    ``handlers.py``). Isso é o que permite adicionar ``Audio-lp1``,
    ``Renderer-lsx1`` etc. no futuro sem tocar no manager.
    """

    __slots__ = (
        "object_type", "uuid", "version", "enabled",
        "modifies", "features", "files", "raw",
    )

    def __init__(self, object_type, data):
        self.object_type = object_type
        self.raw = data or {}
        self.uuid = normalize_uuid(self.raw.get("uuid")) if self.raw.get("uuid") else None
        self.version = str(self.raw.get("version", "1.0"))
        self.enabled = bool(self.raw.get("enabled", True))
        self.modifies = list(self.raw.get("modifies") or [])
        self.features = list(self.raw.get("features") or [])
        self.files = list(self.raw.get("files") or [])

    def to_dict(self):
        return {
            "object_type": self.object_type,
            "uuid": self.uuid,
            "version": self.version,
            "enabled": self.enabled,
            "modifies": self.modifies,
            "features": self.features,
            "files": self.files,
        }


class Manifest(object):
    """Representação normalizada e validada de um ``manifest.json``."""

    def __init__(self, data, source_name=None):
        self.raw = data
        self.source_name = source_name

        self.manifest_version = data.get("manifest_version", CURRENT_MANIFEST_VERSION)

        pkg = data.get("package") or {}
        self.uuid = normalize_uuid(pkg.get("uuid", ""))
        self.name = str(pkg.get("name") or "").strip()
        self.version = str(pkg.get("version") or "0.0.0").strip()
        self.author = pkg.get("author")
        self.description = pkg.get("description", "")
        self.icon = pkg.get("icon")

        compat = data.get("compatibility") or {}
        self.engine = compat.get("engine", "LuaStudio")
        self.engine_version = compat.get("engine_version", "*")
        self.python_constraint = compat.get("python", "*")
        self.kivy_constraint = compat.get("kivy", "*")

        self.dependencies = list(data.get("dependencies") or [])
        self.conflicts = [normalize_uuid(c) for c in (data.get("conflicts") or []) if c]

        # "load_order" é documentado como {"priority": N}, mas pacotes já
        # em uso no mundo real (e o exemplo mais simples de escrever à
        # mão) também usam só um número solto. Aceita os dois formatos.
        load_order = data.get("load_order", 50)
        if isinstance(load_order, dict):
            priority_value = load_order.get("priority", 50)
        else:
            priority_value = load_order
        try:
            self.priority = int(priority_value)
        except (TypeError, ValueError):
            self.priority = 50

        objects_data = data.get("objects") or {}
        self.objects = [
            PluginObject(obj_type, obj_data)
            for obj_type, obj_data in objects_data.items()
        ]

    # -- validação ----------------------------------------------------

    def validate(self):
        """Levanta :class:`ManifestError` se o manifest for inválido.

        Regras obrigatórias (ver especificação do plugin system):
        UUID v4 válido, nome, versão do pacote, e cada objeto declarado
        com um "modifies"/"features" consistentes (listas, mesmo vazias).
        """
        errors = []

        if not is_valid_uuid(self.uuid):
            errors.append("package.uuid ausente ou não é um UUID v4 válido")
        if not self.name:
            errors.append("package.name é obrigatório")
        if not self.version:
            errors.append("package.version é obrigatório")

        seen_obj_uuids = set()
        for obj in self.objects:
            if obj.uuid and not is_valid_uuid(obj.uuid):
                errors.append("objects.%s.uuid não é um UUID v4 válido" % obj.object_type)
            if obj.uuid:
                if obj.uuid in seen_obj_uuids:
                    errors.append("objects.%s possui uuid duplicado dentro do mesmo manifest" % obj.object_type)
                seen_obj_uuids.add(obj.uuid)

        if errors:
            raise ManifestError(
                "Manifest inválido: " + "; ".join(errors),
                uuid=self.uuid or None,
                details={"errors": errors},
            )

    def to_dict(self):
        return {
            "manifest_version": self.manifest_version,
            "package": {
                "uuid": self.uuid,
                "name": self.name,
                "version": self.version,
                "author": self.author,
                "description": self.description,
                "icon": self.icon,
            },
            "compatibility": {
                "engine": self.engine,
                "engine_version": self.engine_version,
                "python": self.python_constraint,
                "kivy": self.kivy_constraint,
            },
            "dependencies": self.dependencies,
            "conflicts": self.conflicts,
            "load_order": {"priority": self.priority},
            "objects": {o.object_type: o.to_dict() for o in self.objects},
        }


def parse_manifest(raw_bytes, source_name=None):
    """Faz o parse de bytes JSON crus em um :class:`Manifest` validado.

    Levanta :class:`ManifestError` em qualquer problema (JSON malformado
    ou dados obrigatórios ausentes/errados).
    """
    try:
        text = raw_bytes.decode("utf-8") if isinstance(raw_bytes, bytes) else raw_bytes
        data = json.loads(text)
    except Exception as exc:
        raise ManifestError("Não foi possível ler manifest.json como JSON: %s" % exc)

    if not isinstance(data, dict):
        raise ManifestError("manifest.json deve conter um objeto JSON na raiz")

    manifest = Manifest(data, source_name=source_name)
    manifest.validate()
    return manifest


def new_uuid():
    """Gera um novo UUID v4 (útil para scaffolding de plugins novos)."""
    return str(uuid_mod.uuid4())

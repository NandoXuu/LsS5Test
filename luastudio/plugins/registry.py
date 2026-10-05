# -*- coding: utf-8 -*-
"""
luastudio.plugins.registry
=============================

Registro local persistente dos plugins instalados (``registry.json``),
dentro de ``LuaStudio/plugins/``.

Layout em disco criado/gerenciado por este módulo::

    plugins/
    ├── installed/<uuid>/      # conteúdo extraído de cada plugin
    ├── cache/                 # pacotes .lpkg/.zip originais (para reinstalar/atualizar)
    ├── backups/<uuid>/        # snapshots de arquivos da engine modificados
    └── registry.json

O registro guarda apenas metadados leves (uuid, nome, versão, estado,
formato, prioridade, caminho). O estado detalhado de cada plugin em tempo
de execução (instância carregada etc.) vive em memória, no
:class:`~luastudio.plugins.manager.PluginManager`.
"""

import json
import os
import tempfile

REGISTRY_FILENAME = "registry.json"
REGISTRY_SCHEMA_VERSION = 1


class PluginRecord(object):
    """Uma entrada do registry.json - metadados persistidos de um plugin."""

    def __init__(self, uuid, name, version, fmt, enabled=True, state="INSTALLED",
                 priority=50, install_dir=None, package_source=None,
                 objects=None, modified_files=None, dependencies=None,
                 conflicts=None, installed_at=None, updated_at=None):
        self.uuid = uuid
        self.name = name
        self.version = version
        self.format = fmt
        self.enabled = enabled
        self.state = state
        self.priority = priority
        self.install_dir = install_dir
        self.package_source = package_source
        self.objects = objects or {}
        # arquivos da engine que este plugin alterou (para reversão)
        self.modified_files = modified_files or []
        self.dependencies = dependencies or []
        self.conflicts = conflicts or []
        self.installed_at = installed_at
        self.updated_at = updated_at

    def to_dict(self):
        return {
            "uuid": self.uuid,
            "name": self.name,
            "version": self.version,
            "format": self.format,
            "enabled": self.enabled,
            "state": self.state,
            "priority": self.priority,
            "install_dir": self.install_dir,
            "package_source": self.package_source,
            "objects": self.objects,
            "modified_files": self.modified_files,
            "dependencies": self.dependencies,
            "conflicts": self.conflicts,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            uuid=data.get("uuid"),
            name=data.get("name"),
            version=data.get("version"),
            fmt=data.get("format"),
            enabled=data.get("enabled", True),
            state=data.get("state", "INSTALLED"),
            priority=data.get("priority", 50),
            install_dir=data.get("install_dir"),
            package_source=data.get("package_source"),
            objects=data.get("objects") or {},
            modified_files=data.get("modified_files") or [],
            dependencies=data.get("dependencies") or [],
            conflicts=data.get("conflicts") or [],
            installed_at=data.get("installed_at"),
            updated_at=data.get("updated_at"),
        )


class PluginRegistry(object):
    """Gerencia o layout de diretórios de plugins e o ``registry.json``."""

    def __init__(self, plugins_dir):
        self.plugins_dir = plugins_dir
        self.installed_dir = os.path.join(plugins_dir, "installed")
        self.cache_dir = os.path.join(plugins_dir, "cache")
        self.backups_dir = os.path.join(plugins_dir, "backups")
        self.registry_path = os.path.join(plugins_dir, REGISTRY_FILENAME)
        self._records = {}  # uuid -> PluginRecord
        self._ensure_dirs()
        self.load()

    def _ensure_dirs(self):
        for d in (self.plugins_dir, self.installed_dir, self.cache_dir, self.backups_dir):
            os.makedirs(d, exist_ok=True)

    # -- persistência -----------------------------------------------------

    def load(self):
        self._records = {}
        if not os.path.isfile(self.registry_path):
            return
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            # registry corrompido não deve travar a engine - fica vazio,
            # e o próximo save() reescreve um registry válido.
            return
        for entry in data.get("plugins", []):
            rec = PluginRecord.from_dict(entry)
            if rec.uuid:
                self._records[rec.uuid] = rec

    def save(self):
        data = {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "plugins": [r.to_dict() for r in self._records.values()],
        }
        # escrita atômica: grava em arquivo temporário e faz replace, para
        # nunca deixar um registry.json corrompido pela metade em caso de
        # falha/crash no meio da escrita.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".registry-", suffix=".json.tmp", dir=self.plugins_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.registry_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # -- consulta -----------------------------------------------------

    def get(self, plugin_uuid):
        return self._records.get(plugin_uuid)

    def all(self):
        return list(self._records.values())

    def find_by_name(self, name):
        return [r for r in self._records.values() if r.name == name]

    def __contains__(self, plugin_uuid):
        return plugin_uuid in self._records

    # -- mutação --------------------------------------------------------

    def put(self, record):
        self._records[record.uuid] = record
        self.save()

    def remove(self, plugin_uuid):
        if plugin_uuid in self._records:
            del self._records[plugin_uuid]
            self.save()

    def install_dir_for(self, plugin_uuid):
        return os.path.join(self.installed_dir, plugin_uuid)

    def backup_dir_for(self, plugin_uuid):
        return os.path.join(self.backups_dir, plugin_uuid)

    def cache_path_for(self, plugin_uuid, fmt):
        return os.path.join(self.cache_dir, "%s.%s" % (plugin_uuid, fmt))

# -*- coding: utf-8 -*-
"""
luastudio.plugins
====================

Sistema de plugins da LuaStudio.

Ponto de entrada público do subsistema descrito em
``PLUGIN_SYSTEM.md`` (na raiz do projeto). Uso típico, a partir da app
host (``app.py``)::

    from luastudio.plugins import PluginManager

    manager = PluginManager(
        plugins_dir=os.path.join(BASE, "plugins"),
        engine_base_dir=BASE,
        engine_version="7.2.0",
        kivy_version=kivy.__version__,
        engine_context=self,            # ex.: a própria LuaStudioApp
        confirm_callback=self._confirm_plugin_action,  # popup de confirmação
    )
    failures = manager.load_all_enabled()   # no boot
    manager.events.emit("engine_start")

    # instalar um novo plugin escolhido pelo usuário no file browser:
    manager.install("/caminho/MeuPlugin.lpkg")

Todas as classes/erros relevantes também são reexportados aqui para
facilitar o import a partir de fora do pacote.
"""

from .errors import (
    DuplicatePackageError,
    IncompatibleEngineError,
    ManifestError,
    ManifestError as InvalidManifestError,  # alias descritivo
    MissingDependencyError,
    PackageError,
    PermissionDeniedError,
    PluginConflictError,
    PluginError,
    PluginInstallError,
    PluginLoadError,
    PluginNotFoundError,
    PluginRuntimeError,
    PluginStateError,
)
from .handlers import HandlerRegistry, ObjectContext, ObjectHandler
from .hooks import EventBus, ExtensionRegistry, PluginAPI
from .manager import (
    PluginManager,
    PluginRuntime,
    STATE_DISABLED,
    STATE_ENABLED,
    STATE_ERROR,
    STATE_INSTALLED,
    STATE_LOADED,
)
from .manifest import Manifest, PluginObject, new_uuid, parse_manifest, version_satisfies
from .package import PluginPackage
from .registry import PluginRecord, PluginRegistry

__all__ = [
    "PluginManager", "PluginRuntime",
    "STATE_INSTALLED", "STATE_LOADED", "STATE_ENABLED", "STATE_DISABLED", "STATE_ERROR",
    "PluginPackage",
    "PluginRegistry", "PluginRecord",
    "Manifest", "PluginObject", "parse_manifest", "version_satisfies", "new_uuid",
    "EventBus", "ExtensionRegistry", "PluginAPI",
    "HandlerRegistry", "ObjectHandler", "ObjectContext",
    "PluginError", "ManifestError", "InvalidManifestError", "PackageError",
    "DuplicatePackageError", "IncompatibleEngineError", "MissingDependencyError",
    "PluginConflictError", "PluginNotFoundError", "PluginLoadError",
    "PluginRuntimeError", "PluginInstallError", "PluginStateError",
    "PermissionDeniedError",
]

# -*- coding: utf-8 -*-
"""
luastudio.plugins.errors
=========================

Códigos e exceções de erro do sistema de plugins da LuaStudio.

Todo erro relevante do Plugin Manager é levantado como uma subclasse de
``PluginError``, sempre com um ``code`` (uma das constantes abaixo) para que
a UI e os logs possam reagir de forma programática, sem precisar fazer
parsing de mensagens de texto.
"""


# ---------------------------------------------------------------------------
# Códigos de erro (strings estáveis - podem ser salvas em logs/registry)
# ---------------------------------------------------------------------------

DUPLICATE_PACKAGE = "DUPLICATE_PACKAGE"
INVALID_MANIFEST = "INVALID_MANIFEST"
INVALID_PACKAGE = "INVALID_PACKAGE"
MISSING_MANIFEST = "MISSING_MANIFEST"
INCOMPATIBLE_ENGINE = "INCOMPATIBLE_ENGINE"
MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
VERSION_MISMATCH = "VERSION_MISMATCH"
PLUGIN_CONFLICT = "PLUGIN_CONFLICT"
PLUGIN_NOT_FOUND = "PLUGIN_NOT_FOUND"
PLUGIN_LOAD_ERROR = "PLUGIN_LOAD_ERROR"
PLUGIN_RUNTIME_ERROR = "PLUGIN_RUNTIME_ERROR"
PLUGIN_INSTALL_ERROR = "PLUGIN_INSTALL_ERROR"
PLUGIN_DEPENDENCY_ERROR = "PLUGIN_DEPENDENCY_ERROR"
PLUGIN_STATE_ERROR = "PLUGIN_STATE_ERROR"
PERMISSION_DENIED = "PERMISSION_DENIED"
UNKNOWN_OBJECT_TYPE = "UNKNOWN_OBJECT_TYPE"


class PluginError(Exception):
    """Base de todos os erros do sistema de plugins.

    Attributes:
        code: uma das constantes deste módulo (ex.: ``DUPLICATE_PACKAGE``).
        uuid: UUID do pacote/objeto relacionado ao erro, quando aplicável.
        details: dicionário livre com informações extras para debug/log.
    """

    code = "PLUGIN_ERROR"

    def __init__(self, message, code=None, uuid=None, details=None):
        super(PluginError, self).__init__(message)
        self.message = message
        self.code = code or self.code
        self.uuid = uuid
        self.details = details or {}

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "uuid": self.uuid,
            "details": self.details,
        }

    def __str__(self):
        base = "[%s] %s" % (self.code, self.message)
        if self.uuid:
            base += " (uuid=%s)" % self.uuid
        return base


class ManifestError(PluginError):
    code = INVALID_MANIFEST


class PackageError(PluginError):
    code = INVALID_PACKAGE


class DuplicatePackageError(PluginError):
    code = DUPLICATE_PACKAGE


class IncompatibleEngineError(PluginError):
    code = INCOMPATIBLE_ENGINE


class MissingDependencyError(PluginError):
    code = MISSING_DEPENDENCY


class PluginConflictError(PluginError):
    code = PLUGIN_CONFLICT


class PluginNotFoundError(PluginError):
    code = PLUGIN_NOT_FOUND


class PluginLoadError(PluginError):
    code = PLUGIN_LOAD_ERROR


class PluginRuntimeError(PluginError):
    code = PLUGIN_RUNTIME_ERROR


class PluginInstallError(PluginError):
    code = PLUGIN_INSTALL_ERROR


class PluginStateError(PluginError):
    code = PLUGIN_STATE_ERROR


class PermissionDeniedError(PluginError):
    code = PERMISSION_DENIED

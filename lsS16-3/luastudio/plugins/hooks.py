# -*- coding: utf-8 -*-
"""
luastudio.plugins.hooks
==========================

Sistema de hooks/eventos e API de extensão oferecida a cada plugin.

Em vez de plugins substituírem arquivos inteiros da engine, eles devem
preferencialmente:

  * escutar eventos do ciclo de vida do editor/engine (``plugin.on(...)``)
  * registrar extensões específicas (menus, painéis, features do editor,
    APIs Lua, shaders, renderers, etc.) através de métodos
    ``plugin.register_*(...)``

Isso reduz conflito entre plugins, já que múltiplos plugins podem se
registrar no mesmo ponto de extensão sem precisar editar o mesmo arquivo.

Este módulo define:

* :class:`EventBus` - pub/sub genérico usado pela engine (``emit``) e
  pelos plugins (``on``/``off``).
* :class:`ExtensionRegistry` - guarda registros nomeados (menus, painéis,
  features de editor, APIs lua, shaders...) por tipo, cada um sabendo a
  qual plugin pertence (para poder remover tudo na hora de desativar/
  desinstalar um plugin).
* :class:`PluginAPI` - fachada única (``plugin`` dentro do ``main.py`` do
  plugin) combinando EventBus + ExtensionRegistry, escopada por plugin.
"""

import logging

logger = logging.getLogger("luastudio.plugins")

# Eventos padrão do ciclo de vida do editor/engine. Plugins podem escutar
# qualquer nome de evento (inclusive customizados por outros plugins) -
# esta lista é só documentação/autocomplete, não uma trava.
STANDARD_EVENTS = (
    "engine_start",
    "engine_stop",
    "project_open",
    "project_close",
    "project_save",
    "editor_ready",
    "before_run",
    "after_run",
    "script_changed",
)

# Tipos de extensão padrão. Assim como os eventos, isso é apenas uma lista
# conhecida - register_extension aceita qualquer chave, o que permite a
# plugins (ou versões futuras da engine) introduzirem novos tipos de
# extensão sem alterar este módulo.
STANDARD_EXTENSION_KINDS = (
    "menu",
    "panel",
    "editor_feature",
    "lua_api",
    "shader",
    "renderer_hook",
    "asset_importer",
)


class EventBus(object):
    """Barramento de eventos simples (pub/sub), usado tanto internamente
    pela engine quanto pelos plugins."""

    def __init__(self):
        self._listeners = {}  # event_name -> list[(plugin_uuid, callback)]

    def on(self, event_name, callback, plugin_uuid=None):
        self._listeners.setdefault(event_name, []).append((plugin_uuid, callback))

    def off(self, event_name, callback=None, plugin_uuid=None):
        if event_name not in self._listeners:
            return
        if callback is None and plugin_uuid is None:
            self._listeners[event_name] = []
            return
        self._listeners[event_name] = [
            (owner, cb) for (owner, cb) in self._listeners[event_name]
            if not ((callback is None or cb == callback) and
                     (plugin_uuid is None or owner == plugin_uuid))
        ]

    def remove_all_for(self, plugin_uuid):
        """Remove todos os listeners registrados por um plugin específico -
        usado ao desativar/desinstalar o plugin."""
        for event_name in list(self._listeners.keys()):
            self._listeners[event_name] = [
                (owner, cb) for (owner, cb) in self._listeners[event_name]
                if owner != plugin_uuid
            ]

    def emit(self, event_name, *args, **kwargs):
        """Dispara um evento para todos os listeners registrados.

        Erros de um listener são isolados (logados, não propagados) para
        que um plugin com bug não derrube o engine_start/before_run/etc.
        de todo o resto da engine.
        """
        results = []
        for owner, cb in list(self._listeners.get(event_name, [])):
            try:
                results.append(cb(*args, **kwargs))
            except Exception:
                logger.exception(
                    "Erro no listener do evento %r (plugin=%s)", event_name, owner
                )
        return results


class ExtensionRegistry(object):
    """Guarda pontos de extensão registrados por plugins (menus, painéis,
    features de editor, APIs Lua, shaders, hooks de renderer...), com
    identificação de qual plugin registrou cada item."""

    def __init__(self):
        # kind -> list of {"plugin_uuid", "name", "value"}
        self._items = {}

    def register(self, kind, name, value, plugin_uuid=None):
        self._items.setdefault(kind, []).append({
            "plugin_uuid": plugin_uuid,
            "name": name,
            "value": value,
        })

    def unregister(self, kind, name=None, plugin_uuid=None):
        if kind not in self._items:
            return
        self._items[kind] = [
            item for item in self._items[kind]
            if not ((name is None or item["name"] == name) and
                     (plugin_uuid is None or item["plugin_uuid"] == plugin_uuid))
        ]

    def remove_all_for(self, plugin_uuid):
        for kind in list(self._items.keys()):
            self._items[kind] = [
                item for item in self._items[kind] if item["plugin_uuid"] != plugin_uuid
            ]

    def get(self, kind):
        return [item["value"] for item in self._items.get(kind, [])]

    def get_with_owners(self, kind):
        return list(self._items.get(kind, []))

    def kinds(self):
        return list(self._items.keys())


class PluginAPI(object):
    """Fachada exposta a cada plugin Python (``main.py``) como ``plugin``.

    Cada plugin recebe uma instância *escopada* (associada ao seu próprio
    ``uuid``), então ``plugin.on(...)``/``plugin.register_*(...)`` marcam
    automaticamente o dono de cada registro - o que permite ao
    PluginManager desfazer tudo de um plugin (``disable``/``uninstall``)
    sem afetar os demais.
    """

    def __init__(self, plugin_uuid, event_bus, extensions, engine=None):
        self.uuid = plugin_uuid
        self._events = event_bus
        self._extensions = extensions
        # `engine` é um objeto de contexto livre (ex.: a LuaStudioApp, o
        # Runtime, etc.) que a engine host injeta, dando ao plugin acesso
        # controlado a APIs internas sem precisar importar módulos internos
        # diretamente.
        self.engine = engine

    # -- eventos ---------------------------------------------------------

    def on(self, event_name, callback):
        """Escuta um evento do ciclo de vida (ex.: "engine_start",
        "project_open", "before_run", "after_run", ou eventos custom)."""
        self._events.on(event_name, callback, plugin_uuid=self.uuid)

    def off(self, event_name, callback=None):
        self._events.off(event_name, callback=callback, plugin_uuid=self.uuid)

    def emit(self, event_name, *args, **kwargs):
        """Permite que um plugin dispare seus próprios eventos custom,
        que outros plugins podem escutar."""
        return self._events.emit(event_name, *args, **kwargs)

    # -- extensões ---------------------------------------------------------

    def register_menu(self, name, value):
        self._extensions.register("menu", name, value, plugin_uuid=self.uuid)

    def register_panel(self, name, value):
        self._extensions.register("panel", name, value, plugin_uuid=self.uuid)

    def register_editor_feature(self, name, value):
        self._extensions.register("editor_feature", name, value, plugin_uuid=self.uuid)

    def register_lua_api(self, name, value):
        self._extensions.register("lua_api", name, value, plugin_uuid=self.uuid)

    def register_shader(self, name, value):
        self._extensions.register("shader", name, value, plugin_uuid=self.uuid)

    def register_renderer_hook(self, name, value):
        self._extensions.register("renderer_hook", name, value, plugin_uuid=self.uuid)

    def register_event(self, event_name, callback):
        """Alias de ``on`` - presente por compatibilidade com a nomenclatura
        pedida na especificação (``plugin.register_event(...)``)."""
        self.on(event_name, callback)

    def register_extension(self, kind, name, value):
        """Ponto de extensão genérico, para tipos de extensão além dos
        atalhos acima (inclusive tipos criados por versões futuras da
        engine ou por convenção entre plugins)."""
        self._extensions.register(kind, name, value, plugin_uuid=self.uuid)

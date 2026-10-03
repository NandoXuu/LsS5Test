# -*- coding: utf-8 -*-
"""
luastudio.plugins.loader
===========================

Carregamento do código de um plugin já instalado em disco (Python e/ou
Lua), conforme ``plugin/python/main.py`` e ``plugin/lua/main.lua``.

* O lado Python interage com a infraestrutura interna da LuaStudio através
  da :class:`~luastudio.plugins.hooks.PluginAPI` (recebida como ``plugin``
  no módulo carregado, e também retornada por ``main(plugin)`` caso o
  ``main.py`` prefira o estilo funcional).
* O lado Lua é apenas *localizado* aqui - quem efetivamente injeta o
  código Lua no runtime da engine (``luastudio.runtime.Runtime``) é a
  engine host, através de ``PluginObject``/``register_lua_api`` ou do
  hook ``project_open``, já que ela é quem possui a VM Lua ativa por
  projeto (isolamento por projeto/sandbox fica a cargo do Runtime).
"""

import importlib.util
import os

from .errors import PluginLoadError

PYTHON_MAIN_REL = os.path.join("plugin", "python", "main.py")
LUA_MAIN_REL = os.path.join("plugin", "lua", "main.lua")


class LoadedPlugin(object):
    """Resultado de carregar o código de um plugin instalado."""

    def __init__(self, python_module=None, lua_source=None, lua_path=None):
        self.python_module = python_module
        self.lua_source = lua_source
        self.lua_path = lua_path


def _load_python_module(install_dir, plugin_uuid, api):
    main_path = os.path.join(install_dir, PYTHON_MAIN_REL)
    if not os.path.isfile(main_path):
        return None

    module_name = "luastudio_plugin_%s" % plugin_uuid.replace("-", "")
    try:
        spec = importlib.util.spec_from_file_location(module_name, main_path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(
                "Não foi possível criar o módulo Python do plugin: %s" % main_path,
                uuid=plugin_uuid,
            )
        module = importlib.util.module_from_spec(spec)
        # expõe a PluginAPI como variável de módulo `plugin`, para que o
        # main.py do plugin possa simplesmente fazer:
        #     plugin.on("engine_start", ...)
        # no nível superior do arquivo.
        module.plugin = api
        spec.loader.exec_module(module)
    except PluginLoadError:
        raise
    except Exception as exc:
        raise PluginLoadError(
            "Erro ao carregar plugin/python/main.py: %s" % exc,
            uuid=plugin_uuid,
            details={"path": main_path},
        )

    # estilo funcional opcional: um main(plugin) explícito, chamado depois
    # que o módulo terminou de ser executado (permite plugins que só
    # querem definir main() sem rodar nada em import-time).
    main_fn = getattr(module, "main", None)
    if callable(main_fn):
        try:
            main_fn(api)
        except Exception as exc:
            raise PluginLoadError(
                "Erro ao executar main(plugin) do plugin: %s" % exc,
                uuid=plugin_uuid,
                details={"path": main_path},
            )
    return module


def _load_lua_source(install_dir, plugin_uuid):
    lua_path = os.path.join(install_dir, LUA_MAIN_REL)
    if not os.path.isfile(lua_path):
        return None, None
    try:
        with open(lua_path, "r", encoding="utf-8") as f:
            return f.read(), lua_path
    except OSError as exc:
        raise PluginLoadError(
            "Erro ao ler plugin/lua/main.lua: %s" % exc,
            uuid=plugin_uuid,
            details={"path": lua_path},
        )


def load_plugin_code(install_dir, plugin_uuid, api):
    """Carrega o código Python e localiza/lê o código Lua de um plugin já
    extraído em ``install_dir``. Ambos são opcionais - um plugin pode ter
    só Python, só Lua, ou os dois juntos.

    Retorna um :class:`LoadedPlugin`. Levanta :class:`PluginLoadError` se
    algum dos dois falhar ao carregar/ler.
    """
    module = _load_python_module(install_dir, plugin_uuid, api)
    lua_source, lua_path = _load_lua_source(install_dir, plugin_uuid)
    return LoadedPlugin(python_module=module, lua_source=lua_source, lua_path=lua_path)


def unload_python_module(module):
    """Tenta dar ao módulo Python de um plugin uma chance de limpar
    recursos próprios ao ser descarregado (ex.: fechar arquivos, threads).
    Convém opcional: só é chamado se o módulo definir ``unload()``."""
    if module is None:
        return
    unload_fn = getattr(module, "unload", None)
    if callable(unload_fn):
        try:
            unload_fn()
        except Exception:
            import logging
            logging.getLogger("luastudio.plugins").exception(
                "Erro em unload() do plugin %s", getattr(module, "__name__", "?")
            )

# -*- coding: utf-8 -*-
"""
luastudio.plugins.handlers
=============================

Arquitetura de registradores/handlers para os "objects" declarados no
manifest (ex.: ``Ui-lp3``, ``Scripting-v1``, ``Motor-lsx-1``).

O Plugin Manager NUNCA deve ter código hardcoded por tipo de objeto: em
vez disso, cada tipo tem um :class:`ObjectHandler` registrado aqui, e o
manager apenas despacha cada :class:`~luastudio.plugins.manifest.PluginObject`
para o handler do seu ``object_type`` (usando um handler genérico de
fallback quando o tipo não é reconhecido). Isso é o que permite adicionar
``Audio-lp1``, ``Network-ls1``, ``Editor-lp1``, ``Asset-ls1``,
``Physics-lsx1``, ``Renderer-lsx1`` etc. no futuro sem alterar
``manager.py``.

Um handler é responsável por, para o seu tipo de objeto:

* ``activate(context)``  - aplicar a modificação/feature na engine quando o
  plugin é ativado (tipicamente registrando hooks/extensões via
  ``context.api``, nunca sobrescrevendo arquivos diretamente).
* ``deactivate(context)`` - desfazer o que ``activate`` fez.

``context`` é uma instância de :class:`ObjectContext`, com acesso ao
próprio ``PluginObject``, à ``PluginAPI`` escopada do plugin dono, ao
diretório onde o plugin foi instalado e ao manifest completo.
"""

import logging

logger = logging.getLogger("luastudio.plugins")


class ObjectContext(object):
    """Contexto passado a um handler ao (des)ativar um objeto de plugin."""

    def __init__(self, obj, api, install_dir, manifest, engine=None):
        self.object = obj          # PluginObject
        self.api = api             # PluginAPI escopada do plugin dono
        self.install_dir = install_dir
        self.manifest = manifest
        self.engine = engine


class ObjectHandler(object):
    """Interface base de um handler de tipo de objeto.

    Handlers concretos devem sobrescrever ``activate``/``deactivate``.
    A implementação padrão apenas loga - suficiente como comportamento
    neutro para tipos de objeto puramente informativos/futuros que ainda
    não tenham lógica própria de ativação.
    """

    #: nome do tipo tratado por este handler, ex. "Ui-lp3". Definido pelas
    #: subclasses ou passado dinamicamente para ``register_handler``.
    object_type = None

    def activate(self, context):
        logger.debug(
            "activate() padrão para objeto %s (plugin=%s) - nenhuma ação definida",
            context.object.object_type, context.manifest.uuid,
        )

    def deactivate(self, context):
        logger.debug(
            "deactivate() padrão para objeto %s (plugin=%s) - nenhuma ação definida",
            context.object.object_type, context.manifest.uuid,
        )


class _GenericHookHandler(ObjectHandler):
    """Handler de fallback: apenas emite eventos "object_activated" e
    "object_deactivated" no barramento de eventos, para que a própria
    engine (ou outros plugins) possa reagir a tipos de objeto que não
    tenham handler dedicado ainda."""

    def activate(self, context):
        context.api.emit(
            "object_activated",
            object_type=context.object.object_type,
            plugin_uuid=context.manifest.uuid,
            obj=context.object,
        )

    def deactivate(self, context):
        context.api.emit(
            "object_deactivated",
            object_type=context.object.object_type,
            plugin_uuid=context.manifest.uuid,
            obj=context.object,
        )


class HandlerRegistry(object):
    """Registro global (por instância de PluginManager) de handlers por
    tipo de objeto, com fallback genérico para tipos desconhecidos."""

    def __init__(self):
        self._handlers = {}
        self._fallback = _GenericHookHandler()
        self._register_builtin_handlers()

    def register_handler(self, object_type, handler):
        """Registra (ou substitui) o handler para ``object_type``.

        ``handler`` pode ser uma instância de :class:`ObjectHandler` ou
        qualquer objeto com métodos ``activate(context)``/
        ``deactivate(context)`` compatíveis (duck typing) - isso permite
        que a própria engine, addons internos, ou plugins "de
        infraestrutura" registrem handlers para novos tipos de objeto em
        tempo de execução.
        """
        self._handlers[object_type] = handler

    def unregister_handler(self, object_type):
        self._handlers.pop(object_type, None)

    def get_handler(self, object_type):
        return self._handlers.get(object_type, self._fallback)

    def known_types(self):
        return list(self._handlers.keys())

    def _register_builtin_handlers(self):
        # Os três tipos iniciais da especificação usam o handler genérico
        # por padrão (eles funcionam via hooks/eventos, não via lógica
        # hardcoded). A engine host (app.py) pode chamar
        # `register_handler("Ui-lp3", MeuHandlerDeUI())` etc. para dar
        # tratamento mais rico a um tipo específico, sem precisar mexer
        # aqui - este método só garante que os três tipos "existem" desde
        # o início para fins de introspecção (known_types()).
        for object_type in ("Ui-lp3", "Scripting-v1", "Motor-lsx-1"):
            self._handlers[object_type] = self._fallback

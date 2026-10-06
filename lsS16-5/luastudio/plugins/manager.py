# -*- coding: utf-8 -*-
"""
luastudio.plugins.manager
============================

``PluginManager`` - orquestrador central do sistema de plugins da
LuaStudio. Reúne os demais módulos do pacote (``package``, ``manifest``,
``registry``, ``hooks``, ``handlers``, ``backup``, ``loader``) para
implementar o fluxo completo descrito na especificação:

    .lpkg / .zip
         -> abrir pacote -> localizar manifest.json -> validar JSON
         -> validar UUID -> verificar compatibilidade
         -> verificar dependências -> verificar conflitos
         -> verificar arquivos -> instalar -> registrar -> carregar

com suporte a instalar, identificar, carregar, ativar, desativar,
atualizar e remover plugins de forma seguro e reversível.

Este módulo não depende de Kivy nem de nada específico da UI da LuaStudio:
a integração com a engine (App, Runtime, etc.) é feita de fora, passando
um ``engine_context`` opcional e, quando necessário, registrando handlers
de objeto (`handler_registry.register_handler(...)`).
"""

import datetime
import logging
import os

from . import errors as E
from .backup import EngineFileLayer
from .handlers import HandlerRegistry, ObjectContext
from .hooks import EventBus, ExtensionRegistry, PluginAPI
from .loader import load_plugin_code, unload_python_module
from .manifest import version_satisfies
from .package import PluginPackage
from .registry import PluginRecord, PluginRegistry

logger = logging.getLogger("luastudio.plugins")

# ---------------------------------------------------------------------------
# Estados do ciclo de vida de um plugin (ver especificação, seção 10)
# ---------------------------------------------------------------------------

STATE_INSTALLED = "INSTALLED"
STATE_LOADED = "LOADED"
STATE_ENABLED = "ENABLED"
STATE_DISABLED = "DISABLED"
STATE_ERROR = "ERROR"


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


class PluginRuntime(object):
    """Estado em memória (não persistido) de um plugin carregado: módulo
    Python, código Lua, PluginAPI escopada e contextos de objeto ativos."""

    def __init__(self, manifest, install_dir, api):
        self.manifest = manifest
        self.install_dir = install_dir
        self.api = api
        self.loaded = None          # LoadedPlugin (python_module/lua_source)
        self.object_contexts = []   # list[ObjectContext] atualmente ativos


class PluginManager(object):
    """Instala, identifica, carrega, ativa, desativa, atualiza e remove
    plugins da LuaStudio.

    Args:
        plugins_dir: diretório base de plugins (``LuaStudio/plugins``).
        engine_base_dir: diretório raiz da engine, usado como base para
            modificações diretas de arquivo (ver ``backup.py``).
        engine_version: versão atual da engine (ex.: "7.2.0"), usada para
            checar ``compatibility.engine_version`` do manifest.
        python_version / kivy_version: usados para checar
            ``compatibility.python`` / ``compatibility.kivy``.
        engine_context: objeto livre repassado a cada ``PluginAPI`` como
            ``api.engine`` (ex.: a instância da App) - permite que
            plugins Python acessem a engine host de forma controlada.
        confirm_callback: ``callable(action, manifest) -> bool``, chamado
            antes de instalar ou ativar um plugin, para exigir confirmação
            explícita do usuário (ver especificação, seção 13 - Segurança).
            Se ``None``, instala/ativa direto (uso em testes/CI); a UI da
            LuaStudio deve sempre passar um callback real.
    """

    def __init__(self, plugins_dir, engine_base_dir=None, engine_version="0.0.0",
                 python_version="3.x", kivy_version="0.0.0",
                 engine_context=None, confirm_callback=None):
        self.plugins_dir = plugins_dir
        self.engine_base_dir = engine_base_dir or plugins_dir
        self.engine_version = engine_version
        self.python_version = python_version
        self.kivy_version = kivy_version
        self.engine_context = engine_context
        self.confirm_callback = confirm_callback

        self.registry = PluginRegistry(plugins_dir)
        self.events = EventBus()
        self.extensions = ExtensionRegistry()
        self.handlers = HandlerRegistry()

        self._runtimes = {}  # uuid -> PluginRuntime (só para plugins LOADED/ENABLED)

    # ------------------------------------------------------------------
    # identificação / introspecção
    # ------------------------------------------------------------------

    def inspect(self, path):
        """Abre um pacote e retorna o :class:`Manifest`, sem instalar nada.
        Usado pela UI para mostrar nome/versão/permissões antes de pedir
        confirmação de instalação."""
        with PluginPackage.open(path) as pkg:
            return pkg.read_manifest()

    def is_installed(self, plugin_uuid):
        return plugin_uuid in self.registry

    def list_installed(self):
        return sorted(self.registry.all(), key=lambda r: (r.priority, r.name or ""))

    def get_state(self, plugin_uuid):
        record = self.registry.get(plugin_uuid)
        return record.state if record else None

    # ------------------------------------------------------------------
    # confirmação de segurança (seção 13)
    # ------------------------------------------------------------------

    def _confirm(self, action, manifest):
        if self.confirm_callback is None:
            return True
        try:
            return bool(self.confirm_callback(action, manifest))
        except Exception:
            logger.exception("Erro no confirm_callback - negando por segurança")
            return False

    # ------------------------------------------------------------------
    # verificações (compatibilidade / dependências / conflitos)
    # ------------------------------------------------------------------

    def _check_compatibility(self, manifest):
        if not version_satisfies(self.engine_version, manifest.engine_version):
            raise E.IncompatibleEngineError(
                "%s requer engine %s (atual: %s)" % (
                    manifest.name, manifest.engine_version, self.engine_version),
                uuid=manifest.uuid,
                code=E.INCOMPATIBLE_ENGINE,
            )
        if manifest.kivy_constraint and manifest.kivy_constraint != "*":
            if not version_satisfies(self.kivy_version, manifest.kivy_constraint):
                raise E.IncompatibleEngineError(
                    "%s requer Kivy %s (atual: %s)" % (
                        manifest.name, manifest.kivy_constraint, self.kivy_version),
                    uuid=manifest.uuid,
                    code=E.INCOMPATIBLE_ENGINE,
                )

    def _check_dependencies(self, manifest):
        missing = []
        for dep in manifest.dependencies:
            dep_uuid = dep.get("uuid") if isinstance(dep, dict) else dep
            dep_version = dep.get("version") if isinstance(dep, dict) else None
            if not dep_uuid:
                continue
            dep_uuid = dep_uuid.strip().lower()
            record = self.registry.get(dep_uuid)
            if record is None or not record.enabled:
                missing.append(dep_uuid)
                continue
            if dep_version and not version_satisfies(record.version, dep_version):
                missing.append("%s (%s)" % (dep_uuid, dep_version))
        if missing:
            raise E.MissingDependencyError(
                "%s depende de plugin(s) ausente(s) ou desativado(s): %s" % (
                    manifest.name, ", ".join(missing)),
                uuid=manifest.uuid,
                code=E.MISSING_DEPENDENCY,
                details={"missing": missing},
            )

    def _check_conflicts(self, manifest, enabling_only=False):
        """Detecta conflitos declarados explicitamente (seção 11).

        Ter o mesmo tipo de objeto (ex.: dois plugins com "Scripting-v1")
        NÃO é conflito por si só - só é bloqueado quando um plugin lista o
        outro em ``conflicts`` (por UUID)."""
        installed = self.registry.all()
        for other in installed:
            if other.uuid == manifest.uuid:
                continue
            if enabling_only and not other.enabled:
                continue
            if other.uuid in manifest.conflicts:
                raise E.PluginConflictError(
                    "%s está marcado como incompatível com o plugin já instalado %s" % (
                        manifest.name, other.name),
                    uuid=manifest.uuid,
                    code=E.PLUGIN_CONFLICT,
                    details={"conflicts_with": other.uuid},
                )
            if manifest.uuid in (other.conflicts or []):
                raise E.PluginConflictError(
                    "O plugin já instalado %s declara conflito com %s" % (
                        other.name, manifest.name),
                    uuid=manifest.uuid,
                    code=E.PLUGIN_CONFLICT,
                    details={"conflicts_with": other.uuid},
                )

    # ------------------------------------------------------------------
    # instalação
    # ------------------------------------------------------------------

    def install(self, path, allow_update=False, auto_enable=True):
        """Instala um pacote ``.lpkg``/``.zip``.

        Fluxo: abrir pacote -> localizar manifest -> validar JSON/UUID ->
        checar compatibilidade -> checar dependências -> checar conflitos
        -> checar arquivos -> extrair -> registrar -> (opcional) carregar
        e ativar.

        Se já existir um plugin com o mesmo UUID instalado e
        ``allow_update`` for ``False``, levanta ``DuplicatePackageError``
        (código ``DUPLICATE_PACKAGE``) - a especificação exige que isso só
        seja permitido quando a operação é explicitamente uma atualização
        (veja :meth:`update`).

        Retorna o :class:`~luastudio.plugins.registry.PluginRecord`
        resultante.
        """
        fmt = os.path.splitext(path)[1].lower().lstrip(".")
        with PluginPackage.open(path) as pkg:
            manifest = pkg.read_manifest()  # já validado (UUID, campos obrigatórios)

            existing = self.registry.get(manifest.uuid)
            if existing is not None and not allow_update:
                raise E.DuplicatePackageError(
                    "Já existe um plugin instalado com este UUID (%s): %s" % (
                        manifest.uuid, existing.name),
                    uuid=manifest.uuid,
                    code=E.DUPLICATE_PACKAGE,
                )

            self._check_compatibility(manifest)
            self._check_dependencies(manifest)
            self._check_conflicts(manifest)

            if not self._confirm("install", manifest):
                raise E.PermissionDeniedError(
                    "Instalação cancelada: usuário não confirmou.",
                    uuid=manifest.uuid,
                    code=E.PERMISSION_DENIED,
                )

            # "verificar arquivos": garante que os arquivos citados pelos
            # objetos do manifest realmente existem dentro do pacote antes
            # de extrair qualquer coisa.
            missing_files = [
                f for obj in manifest.objects for f in obj.files
                if not pkg.has_file(f)
            ]
            if missing_files:
                raise E.PackageError(
                    "Pacote declara arquivos que não existem dentro dele: %s" % (
                        ", ".join(missing_files)),
                    code=E.INVALID_PACKAGE,
                    uuid=manifest.uuid,
                )

            install_dir = self.registry.install_dir_for(manifest.uuid)
            if existing is not None:
                # atualização: remove instalação anterior antes de extrair a
                # nova, mas preserva o estado enabled/disabled do usuário.
                self._wipe_install_dir(install_dir)

            try:
                pkg.extract_all(install_dir)
            except OSError as exc:
                raise E.PluginInstallError(
                    "Falha ao extrair pacote: %s" % exc,
                    uuid=manifest.uuid,
                    code=E.PLUGIN_INSTALL_ERROR,
                )

            # cacheia o pacote original (permite reinstalar/depurar depois)
            cache_path = self.registry.cache_path_for(manifest.uuid, fmt)
            self._copy_original_package(path, cache_path)

        now = _now_iso()
        record = PluginRecord(
            uuid=manifest.uuid,
            name=manifest.name,
            version=manifest.version,
            fmt=fmt,
            enabled=existing.enabled if existing else False,
            state=STATE_INSTALLED,
            priority=manifest.priority,
            install_dir=install_dir,
            package_source=cache_path,
            objects={o.object_type: o.to_dict() for o in manifest.objects},
            modified_files=existing.modified_files if existing else [],
            dependencies=manifest.dependencies,
            conflicts=manifest.conflicts,
            installed_at=existing.installed_at if existing else now,
            updated_at=now,
        )
        self.registry.put(record)
        logger.info("Plugin instalado: %s (%s) v%s", manifest.name, manifest.uuid, manifest.version)

        if auto_enable:
            self.load(manifest.uuid)
            self.enable(manifest.uuid)
        return record

    def update(self, path):
        """Atalho para ``install(path, allow_update=True)`` - trata
        explicitamente como atualização de um pacote já instalado."""
        fmt_manifest = self.inspect(path)
        was_enabled = False
        existing = self.registry.get(fmt_manifest.uuid)
        if existing is None:
            raise E.PluginNotFoundError(
                "Nenhum plugin instalado com UUID %s para atualizar" % fmt_manifest.uuid,
                uuid=fmt_manifest.uuid, code=E.PLUGIN_NOT_FOUND,
            )
        was_enabled = existing.enabled
        if was_enabled:
            self.disable(fmt_manifest.uuid)
        self.unload(fmt_manifest.uuid)
        record = self.install(path, allow_update=True, auto_enable=False)
        self.load(record.uuid)
        if was_enabled:
            self.enable(record.uuid)
        return record

    def _wipe_install_dir(self, install_dir):
        import shutil
        if os.path.isdir(install_dir):
            shutil.rmtree(install_dir)

    def _copy_original_package(self, src, dest):
        import shutil
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)

    # ------------------------------------------------------------------
    # carregar / descarregar
    # ------------------------------------------------------------------

    def load(self, plugin_uuid):
        """Carrega o código (Python/Lua) de um plugin já instalado, sem
        ativá-lo (sem aplicar objetos/hooks na engine ainda)."""
        record = self._require_record(plugin_uuid)
        if plugin_uuid in self._runtimes:
            return self._runtimes[plugin_uuid]

        manifest = self._read_installed_manifest(record)
        api = PluginAPI(plugin_uuid, self.events, self.extensions, engine=self.engine_context)
        runtime = PluginRuntime(manifest, record.install_dir, api)

        try:
            runtime.loaded = load_plugin_code(record.install_dir, plugin_uuid, api)
        except E.PluginError as exc:
            record.state = STATE_ERROR
            self.registry.put(record)
            logger.error(str(exc))
            raise

        self._runtimes[plugin_uuid] = runtime
        record.state = STATE_LOADED
        self.registry.put(record)
        return runtime

    def unload(self, plugin_uuid):
        """Descarrega o código de um plugin (implica desativá-lo antes,
        se estiver ativo)."""
        record = self._require_record(plugin_uuid)
        if record.state == STATE_ENABLED:
            self.disable(plugin_uuid)

        runtime = self._runtimes.pop(plugin_uuid, None)
        if runtime is not None and runtime.loaded is not None:
            unload_python_module(runtime.loaded.python_module)

        self.events.remove_all_for(plugin_uuid)
        self.extensions.remove_all_for(plugin_uuid)

        record.state = STATE_INSTALLED
        self.registry.put(record)

    # ------------------------------------------------------------------
    # ativar / desativar
    # ------------------------------------------------------------------

    def enable(self, plugin_uuid):
        """Ativa um plugin: aplica cada objeto do manifest através do
        handler registrado para seu tipo (``handlers.py``), e dispara
        listeners que o plugin tenha registrado para eventos já ocorridos
        que façam sentido reemitir (a engine host decide isso)."""
        record = self._require_record(plugin_uuid)
        runtime = self._runtimes.get(plugin_uuid) or self.load(plugin_uuid)

        if not self._confirm("enable", runtime.manifest):
            raise E.PermissionDeniedError(
                "Ativação cancelada: usuário não confirmou.",
                uuid=plugin_uuid, code=E.PERMISSION_DENIED,
            )

        self._check_conflicts(runtime.manifest, enabling_only=True)
        self._check_dependencies(runtime.manifest)

        try:
            for obj in runtime.manifest.objects:
                if not obj.enabled:
                    continue
                handler = self.handlers.get_handler(obj.object_type)
                context = ObjectContext(
                    obj=obj, api=runtime.api, install_dir=runtime.install_dir,
                    manifest=runtime.manifest, engine=self.engine_context,
                )
                handler.activate(context)
                runtime.object_contexts.append(context)
        except Exception as exc:
            record.state = STATE_ERROR
            self.registry.put(record)
            if isinstance(exc, E.PluginError):
                raise
            raise E.PluginRuntimeError(
                "Erro ao ativar plugin: %s" % exc, uuid=plugin_uuid,
                code=E.PLUGIN_RUNTIME_ERROR,
            )

        record.enabled = True
        record.state = STATE_ENABLED
        self.registry.put(record)
        self.events.emit("plugin_enabled", plugin_uuid=plugin_uuid)
        logger.info("Plugin ativado: %s (%s)", runtime.manifest.name, plugin_uuid)

    def disable(self, plugin_uuid):
        """Desativa um plugin: reverte cada objeto ativo via
        ``handler.deactivate`` e remove seus hooks/extensões registrados,
        sem descarregar o código nem desinstalar."""
        record = self._require_record(plugin_uuid)
        runtime = self._runtimes.get(plugin_uuid)
        if runtime is not None:
            for context in reversed(runtime.object_contexts):
                handler = self.handlers.get_handler(context.object.object_type)
                try:
                    handler.deactivate(context)
                except Exception:
                    logger.exception(
                        "Erro ao desativar objeto %s do plugin %s",
                        context.object.object_type, plugin_uuid,
                    )
            runtime.object_contexts = []
            self.events.remove_all_for(plugin_uuid)
            self.extensions.remove_all_for(plugin_uuid)

        record.enabled = False
        record.state = STATE_DISABLED
        self.registry.put(record)
        self.events.emit("plugin_disabled", plugin_uuid=plugin_uuid)
        logger.info("Plugin desativado: %s", plugin_uuid)

    # ------------------------------------------------------------------
    # modificação direta de arquivos da engine (último recurso)
    # ------------------------------------------------------------------

    def apply_engine_file(self, plugin_uuid, package_relative_path, engine_relative_path):
        """Aplica a substituição/adição de um arquivo da engine a partir
        de um arquivo já extraído do plugin, com backup automático
        (seção 6/7 - só deve ser usado quando hooks não bastam)."""
        record = self._require_record(plugin_uuid)
        runtime = self._runtimes.get(plugin_uuid) or self.load(plugin_uuid)
        source_abs = os.path.join(runtime.install_dir, package_relative_path)
        if not os.path.isfile(source_abs):
            raise E.PackageError(
                "Arquivo do plugin não encontrado: %s" % package_relative_path,
                uuid=plugin_uuid,
            )
        layer = EngineFileLayer(self.engine_base_dir, self.registry.backup_dir_for(plugin_uuid))
        layer.copy_file(source_abs, engine_relative_path)
        if engine_relative_path not in record.modified_files:
            record.modified_files.append(engine_relative_path)
            self.registry.put(record)
        return engine_relative_path

    # ------------------------------------------------------------------
    # remoção
    # ------------------------------------------------------------------

    def uninstall(self, plugin_uuid):
        """Remove um plugin por completo: desativa, descarrega, restaura
        quaisquer arquivos da engine que ele tenha modificado diretamente,
        apaga os arquivos instalados e o backup, e remove do registro."""
        record = self._require_record(plugin_uuid)

        if record.state == STATE_ENABLED:
            self.disable(plugin_uuid)
        if plugin_uuid in self._runtimes:
            self.unload(plugin_uuid)

        if record.modified_files:
            layer = EngineFileLayer(
                self.engine_base_dir, self.registry.backup_dir_for(plugin_uuid)
            )
            layer.restore_all(record.modified_files)

        import shutil
        for d in (record.install_dir, self.registry.backup_dir_for(plugin_uuid)):
            if d and os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
        if record.package_source and os.path.isfile(record.package_source):
            try:
                os.remove(record.package_source)
            except OSError:
                pass

        self.registry.remove(plugin_uuid)
        logger.info("Plugin removido: %s", plugin_uuid)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _require_record(self, plugin_uuid):
        record = self.registry.get(plugin_uuid)
        if record is None:
            raise E.PluginNotFoundError(
                "Plugin não encontrado: %s" % plugin_uuid,
                uuid=plugin_uuid, code=E.PLUGIN_NOT_FOUND,
            )
        return record

    def _read_installed_manifest(self, record):
        from .manifest import parse_manifest, MANIFEST_FILENAME
        manifest_path = os.path.join(record.install_dir, MANIFEST_FILENAME)
        if not os.path.isfile(manifest_path):
            raise E.PluginLoadError(
                "manifest.json ausente na instalação de %s" % record.name,
                uuid=record.uuid, code=E.PLUGIN_LOAD_ERROR,
            )
        with open(manifest_path, "rb") as f:
            return parse_manifest(f.read(), source_name=manifest_path)

    # ------------------------------------------------------------------
    # ciclo de vida da engine - conveniências para a app host
    # ------------------------------------------------------------------

    def load_all_enabled(self):
        """Carrega e ativa todos os plugins marcados como ``enabled`` no
        registro, em ordem de ``priority`` (menor primeiro). Chamado
        tipicamente no boot da engine (evento ``engine_start``).

        Erros em um plugin individual não impedem os demais de carregar -
        ficam marcados com estado ``ERROR`` e são reportados no final.
        """
        failures = []
        candidates = sorted(
            [r for r in self.registry.all() if r.enabled],
            key=lambda r: r.priority,
        )
        for record in candidates:
            try:
                self.load(record.uuid)
                self.enable(record.uuid)
            except E.PluginError as exc:
                failures.append(exc)
                logger.error("Falha ao carregar plugin %s: %s", record.uuid, exc)
        return failures

# -*- coding: utf-8 -*-
"""
luastudio.plugins.backup
===========================

Camada de alterações/backup que torna reversível qualquer modificação
direta que um plugin faça em arquivos internos da engine (o caminho de
"substituição de arquivo" citado na especificação como último recurso,
quando hooks/extensões não são suficientes).

Regra de ouro: **nunca sobrescrever um arquivo original sem antes guardar
uma cópia dele**. Isso garante:

    Instalar plugin -> Modificar engine -> Desinstalar plugin -> Restaurar

Cada plugin tem sua própria pasta de backup (``plugins/backups/<uuid>/``),
espelhando os caminhos relativos ao diretório base da engine dos arquivos
que ele alterou. Um arquivo só é copiado para lá na *primeira* vez que é
tocado (para não sobrescrever o backup com o estado já modificado, caso o
plugin seja atualizado/reaplique a alteração).
"""

import os
import shutil

from .errors import PluginInstallError


class EngineFileLayer(object):
    """Aplica e reverte modificações em arquivos da engine para um
    plugin específico, mantendo backups reversíveis.

    Args:
        engine_base_dir: diretório raiz da instalação da engine (onde
            ficam os arquivos que podem ser modificados, ex.: a pasta
            que contém ``luastudio/``).
        backup_dir: diretório onde este plugin guarda backups dos
            arquivos que alterou (``registry.backup_dir_for(uuid)``).
    """

    def __init__(self, engine_base_dir, backup_dir):
        self.engine_base_dir = engine_base_dir
        self.backup_dir = backup_dir

    def _resolve(self, relative_path):
        norm = os.path.normpath(relative_path)
        if norm.startswith("..") or os.path.isabs(norm):
            raise PluginInstallError(
                "Caminho de arquivo da engine inseguro: %s" % relative_path
            )
        return os.path.join(self.engine_base_dir, norm)

    def _backup_path(self, relative_path):
        return os.path.join(self.backup_dir, os.path.normpath(relative_path))

    def _ensure_backup(self, relative_path):
        """Garante que existe um backup do estado *atual* do arquivo,
        antes de qualquer modificação. Não sobrescreve um backup já
        existente (é o estado "original" que precisamos preservar)."""
        target = self._resolve(relative_path)
        backup_path = self._backup_path(relative_path)
        if os.path.exists(backup_path):
            return
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        if os.path.exists(target):
            shutil.copy2(target, backup_path)
        else:
            # arquivo não existia antes - marca isso com um sentinel vazio
            # + um marker, para que restore() saiba que deve *remover* o
            # arquivo (e não deixar um arquivo vazio) ao reverter.
            open(backup_path, "wb").close()
            open(backup_path + ".created", "wb").close()

    def write_file(self, relative_path, content_bytes):
        """Escreve (substitui) um arquivo da engine, com backup automático
        do estado anterior na primeira modificação."""
        self._ensure_backup(relative_path)
        target = self._resolve(relative_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(content_bytes)
        return relative_path

    def copy_file(self, source_abs_path, relative_path):
        """Copia um arquivo (ex.: extraído do pacote do plugin) para dentro
        da engine em ``relative_path``, com backup automático."""
        with open(source_abs_path, "rb") as f:
            data = f.read()
        return self.write_file(relative_path, data)

    def restore_file(self, relative_path):
        """Restaura um único arquivo ao estado anterior à modificação."""
        backup_path = self._backup_path(relative_path)
        target = self._resolve(relative_path)
        created_marker = backup_path + ".created"
        if os.path.exists(created_marker):
            # o arquivo não existia antes do plugin - remove
            if os.path.exists(target):
                os.remove(target)
            os.remove(created_marker)
            if os.path.exists(backup_path):
                os.remove(backup_path)
            return
        if os.path.exists(backup_path):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(backup_path, target)
            os.remove(backup_path)

    def restore_all(self, relative_paths):
        """Restaura uma lista de arquivos (tipicamente
        ``record.modified_files``) e limpa a pasta de backup do plugin."""
        for rel in relative_paths:
            try:
                self.restore_file(rel)
            except OSError:
                # não deixa um arquivo com problema impedir a reversão dos
                # demais - o desinstalador ainda reporta o resultado.
                pass
        # remove a pasta de backup do plugin se ficou vazia
        try:
            if os.path.isdir(self.backup_dir) and not os.listdir(self.backup_dir):
                os.rmdir(self.backup_dir)
        except OSError:
            pass

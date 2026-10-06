# -*- coding: utf-8 -*-
"""
luastudio.plugins.package
============================

Abstração para abrir um pacote de plugin, seja ``.lpkg`` (formato nativo)
ou ``.zip`` (formato alternativo). Internamente os dois usam exatamente a
mesma infraestrutura de leitura (``zipfile``) - um ``.lpkg`` é, na prática,
um ZIP com outra extensão, como descrito na especificação.

Este módulo só lida com E/S de arquivo e estrutura do pacote; validação de
manifest fica em ``manifest.py`` e política de instalação fica em
``manager.py``.
"""

import io
import os
import zipfile

from .errors import PackageError
from .manifest import MANIFEST_FILENAME, parse_manifest

SUPPORTED_EXTENSIONS = (".lpkg", ".zip")


class PluginPackage(object):
    """Um pacote de plugin aberto (ainda não instalado).

    Uso típico::

        pkg = PluginPackage.open("MeuPlugin.lpkg")
        manifest = pkg.read_manifest()
        pkg.extract_all(destino)
        pkg.close()

    Também funciona como context manager.
    """

    def __init__(self, path, zip_file):
        self.path = path
        self._zip = zip_file
        self._manifest = None

    # -- abertura -------------------------------------------------------

    @classmethod
    def open(cls, path):
        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise PackageError(
                "Formato de pacote não suportado: %r (esperado .lpkg ou .zip)" % ext
            )
        if not os.path.isfile(path):
            raise PackageError("Arquivo de pacote não encontrado: %s" % path)
        try:
            zf = zipfile.ZipFile(path, "r")
        except zipfile.BadZipFile as exc:
            raise PackageError("Pacote corrompido ou não é um ZIP/LPKG válido: %s" % exc)
        return cls(path, zf)

    @classmethod
    def open_bytes(cls, data, name="<memoria>"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data), "r")
        except zipfile.BadZipFile as exc:
            raise PackageError("Pacote corrompido ou não é um ZIP/LPKG válido: %s" % exc)
        return cls(name, zf)

    def close(self):
        try:
            self._zip.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # -- estrutura --------------------------------------------------------

    def namelist(self):
        return self._zip.namelist()

    def _find_manifest_path(self):
        """Localiza manifest.json, tolerando estar dentro de uma única
        pasta-raiz (comum quando o usuário zipa a pasta do plugin inteira
        em vez do conteúdo dela)."""
        names = self.namelist()
        if MANIFEST_FILENAME in names:
            return MANIFEST_FILENAME
        candidates = [n for n in names if n.endswith("/" + MANIFEST_FILENAME)]
        if not candidates:
            return None
        # prefere o manifest mais próximo da raiz (menor profundidade)
        candidates.sort(key=lambda n: n.count("/"))
        return candidates[0]

    @property
    def root_prefix(self):
        """Prefixo de diretório onde o manifest foi encontrado, para que
        o resto do pacote seja lido relativo a ele (ex.: "MeuPlugin/")."""
        manifest_path = self._find_manifest_path()
        if not manifest_path or "/" not in manifest_path:
            return ""
        return manifest_path.rsplit("/", 1)[0] + "/"

    def read_manifest(self):
        if self._manifest is not None:
            return self._manifest
        manifest_path = self._find_manifest_path()
        if not manifest_path:
            from .errors import MISSING_MANIFEST, PluginError
            raise PluginError(
                "Pacote não contém manifest.json: %s" % self.path,
                code=MISSING_MANIFEST,
            )
        raw = self._zip.read(manifest_path)
        self._manifest = parse_manifest(raw, source_name=self.path)
        return self._manifest

    def read_file(self, relative_path):
        """Lê um arquivo do pacote, relativo à raiz do plugin (onde está
        o manifest.json), independente de haver uma pasta-raiz extra."""
        full = self.root_prefix + relative_path
        try:
            return self._zip.read(full)
        except KeyError:
            raise PackageError("Arquivo não encontrado no pacote: %s" % relative_path)

    def has_file(self, relative_path):
        return (self.root_prefix + relative_path) in self.namelist()

    def list_relative(self):
        """Lista todos os arquivos do pacote com caminhos relativos à raiz
        do plugin (sem o prefixo de pasta extra, se houver)."""
        prefix = self.root_prefix
        out = []
        for n in self.namelist():
            if n.endswith("/"):
                continue
            if prefix and not n.startswith(prefix):
                continue
            out.append(n[len(prefix):] if prefix else n)
        return out

    def extract_all(self, destination_dir):
        """Extrai o conteúdo do plugin (relativo à raiz do manifest) para
        ``destination_dir``, preservando a árvore de diretórios."""
        os.makedirs(destination_dir, exist_ok=True)
        prefix = self.root_prefix
        for info in self._zip.infolist():
            name = info.filename
            if prefix and not name.startswith(prefix):
                continue
            rel = name[len(prefix):] if prefix else name
            if not rel or rel.endswith("/"):
                continue
            # protege contra path traversal ("../../etc/passwd") em pacotes
            # maliciosos ou corrompidos.
            norm = os.path.normpath(rel)
            if norm.startswith("..") or os.path.isabs(norm):
                raise PackageError("Pacote contém caminho inseguro: %s" % rel)
            dest_path = os.path.join(destination_dir, norm)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with self._zip.open(info, "r") as src, open(dest_path, "wb") as dst:
                dst.write(src.read())
        return destination_dir

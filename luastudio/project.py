# -*- coding: utf-8 -*-
"""Sistema de projetos do LuaStudio.

Um projeto e uma pasta dentro de `LuaStudio/Projects/<nome>/` contendo:

  - project.json   manifesto (nome, script de entrada, lista de scripts)
  - scripts/*.lua  um ou mais arquivos de script/modulo do projeto
  - assets/*       opcional: imagens, sons etc. usados pelo projeto

Todos os scripts de um projeto rodam no MESMO runtime Lua (mesmas
variaveis globais, mesma cena), entao podem se comunicar entre si e
editar os mesmos objetos, por exemplo:

  - um script cria `create.part.Player = {...}` e outro faz
    `app.find("Player")` pra mexer nele;
  - ou, no estilo Lua padrao, um script vira "modulo" e devolve uma
    tabela com `return M`; qualquer outro script do projeto pode pegar
    essa tabela com `local m = require("nome_do_arquivo")`.

Um projeto pode ser exportado como um pacote `.Lsp` (um .zip por baixo)
com o manifesto + todos os scripts + assets, pra ser aberto tanto pelo
proprio editor (LuaStudio) quanto pelo LuaStudio Player (o app separado
que so executa jogos, em tela cheia).
"""

import os
import json
import time
import shutil
import zipfile

from . import permissions as perms

PROJECT_FILE = "project.json"
SCRIPTS_DIR = "scripts"
ASSETS_DIR = "assets"
LSP_EXT = ".Lsp"
ENGINE_VERSION = 1

DEFAULT_MAIN = """-- main.lua (script de entrada do projeto)
-- Um projeto pode ter varios scripts que se comunicam entre si.
-- Aqui a gente pega o modulo "ajudante" (outro arquivo do projeto) e
-- deixa ele editar o MESMO objeto "Titulo" que a gente acabou de criar.

local ajudante = require("ajudante")

create.label.Titulo = {
  Text = "Novo projeto!", Position = {20, 20}, Size = {280, 46},
  FontSize = 24, TextColor = "cyan"
}

create.button.Toque = {
  Text = "Chamar ajudante", Position = {20, 90}, Size = {220, 56},
  Color = "#2b6cf6", Radius = 14,
  OnClick = function(self)
    ajudante.ligar("Titulo")
    android.vibrate(30)
  end
}

ajudante.ligar("Titulo")
"""

DEFAULT_MODULE = """-- ajudante.lua (modulo: outro script do mesmo projeto)
-- require("ajudante") devolve esta tabela pra quem chamar.
-- Repare que esta funcao edita um objeto que foi CRIADO no main.lua.
local M = {}

function M.ligar(nomeDoObjeto)
  local obj = app.find(nomeDoObjeto)
  if obj then
    obj.TextColor = "lime"
    app.log("[ajudante] liguei em " .. nomeDoObjeto)
  end
end

return M
"""


# --------------------------------------------------------------- helpers
def _safe_name(name):
    name = (name or "").strip()
    keep = [c if (c.isalnum() or c in " _-") else "_" for c in name]
    out = "".join(keep).strip() or "Projeto"
    return out[:60]


def _safe_script_name(name):
    name = (name or "").strip()
    if not name:
        name = "script"
    if not name.lower().endswith(".lua"):
        name += ".lua"
    keep = [c if (c.isalnum() or c in "._-") else "_" for c in name]
    out = "".join(keep)
    while out.startswith("."):
        out = out[1:]
    return out or "script.lua"


def projects_root():
    """Pasta onde ficam todos os projetos: LuaStudio/Projects."""
    root = os.path.join(perms.storage_dir(), "Projects")
    try:
        if not os.path.isdir(root):
            os.makedirs(root)
    except Exception:
        pass
    return root


# ------------------------------------------------------------------ Project
class Project(object):
    """Projeto em memoria: nome, scripts {arquivo.lua: codigo}, entrada."""

    def __init__(self, name="Novo Projeto", path=None):
        self.name = name
        self.path = path              # None = ainda nao tem pasta em disco
        self.scripts = {}             # nome_do_arquivo.lua -> codigo fonte
        self.entry = "main.lua"
        self.created = time.time()

    def order(self):
        """Nomes dos scripts, com o de entrada sempre primeiro."""
        names = sorted(self.scripts.keys())
        if self.entry in names:
            names.remove(self.entry)
            names.insert(0, self.entry)
        return names

    def add_script(self, name, code=""):
        name = _safe_script_name(name)
        if name not in self.scripts:
            self.scripts[name] = code
            return name
        stem = name[:-4] if name.lower().endswith(".lua") else name
        i = 2
        while ("%s_%d.lua" % (stem, i)) in self.scripts:
            i += 1
        new_name = "%s_%d.lua" % (stem, i)
        self.scripts[new_name] = code
        return new_name

    def remove_script(self, name):
        if name in self.scripts and len(self.scripts) > 1:
            del self.scripts[name]
            if self.entry == name:
                self.entry = self.order()[0]
            return True
        return False

    def set_entry(self, name):
        if name in self.scripts:
            self.entry = name
            return True
        return False

    def manifest(self):
        return {
            "engine": ENGINE_VERSION,
            "name": self.name,
            "entry": self.entry,
            "scripts": sorted(self.scripts.keys()),
            "created": self.created,
            "modified": time.time(),
        }


# ---------------------------------------------------------------- listagem
def list_projects():
    """[(pasta, caminho_completo, nome_exibido)] de todo projeto salvo."""
    root = projects_root()
    out = []
    if os.path.isdir(root):
        for entry in sorted(os.listdir(root)):
            path = os.path.join(root, entry)
            manifest_path = os.path.join(path, PROJECT_FILE)
            if os.path.isdir(path) and os.path.isfile(manifest_path):
                display = entry
                try:
                    with open(manifest_path, "r", encoding="utf-8") as fh:
                        display = json.load(fh).get("name", entry)
                except Exception:
                    pass
                out.append((entry, path, display))
    return out


# ------------------------------------------------------------------- criar
def create_project(name):
    """Cria um projeto NOVO em memoria (com um exemplo de 2 scripts que se
    comunicam). So vira pasta de verdade quando `save_project` for chamado."""
    proj = Project(name=name or "Novo Projeto")
    folder = _safe_name(proj.name)
    root = projects_root()
    dest, i = os.path.join(root, folder), 1
    while os.path.isdir(dest):
        i += 1
        dest = os.path.join(root, "%s_%d" % (folder, i))
    proj.path = dest
    proj.add_script("main.lua", DEFAULT_MAIN)
    proj.add_script("ajudante.lua", DEFAULT_MODULE)
    proj.entry = "main.lua"
    return proj


# ------------------------------------------------------------------- salvar
def save_project(proj):
    """Grava o projeto (manifesto + scripts) na pasta em disco. Devolve o
    caminho da pasta."""
    if not proj.path:
        proj.path = os.path.join(projects_root(), _safe_name(proj.name))
    scripts_dir = os.path.join(proj.path, SCRIPTS_DIR)
    if not os.path.isdir(scripts_dir):
        os.makedirs(scripts_dir)
    # remove do disco scripts que nao existem mais no projeto em memoria
    for fn in os.listdir(scripts_dir):
        if fn.lower().endswith(".lua") and fn not in proj.scripts:
            try:
                os.remove(os.path.join(scripts_dir, fn))
            except Exception:
                pass
    for name, code in proj.scripts.items():
        with open(os.path.join(scripts_dir, name), "w", encoding="utf-8") as fh:
            fh.write(code)
    with open(os.path.join(proj.path, PROJECT_FILE), "w", encoding="utf-8") as fh:
        json.dump(proj.manifest(), fh, ensure_ascii=False, indent=2)
    return proj.path


# -------------------------------------------------------------------- abrir
def load_project(path):
    manifest_path = os.path.join(path, PROJECT_FILE)
    with open(manifest_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    proj = Project(name=data.get("name") or os.path.basename(path), path=path)
    proj.entry = data.get("entry", "main.lua")
    proj.created = data.get("created", time.time())
    scripts_dir = os.path.join(path, SCRIPTS_DIR)
    names = list(data.get("scripts") or [])
    if os.path.isdir(scripts_dir):
        for fn in sorted(os.listdir(scripts_dir)):
            if fn.lower().endswith(".lua") and fn not in names:
                names.append(fn)  # recupera arquivos fora do manifesto
    for name in names:
        fp = os.path.join(scripts_dir, name)
        if os.path.isfile(fp):
            with open(fp, "r", encoding="utf-8") as fh:
                proj.scripts[name] = fh.read()
    if not proj.scripts:
        proj.add_script("main.lua", DEFAULT_MAIN)
    if proj.entry not in proj.scripts:
        proj.entry = proj.order()[0]
    return proj


def delete_project(path):
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------- exportar .Lsp
def _safe_extract_path(dest_dir, member_name):
    """Resolve o caminho de uma entrada de dentro do .Lsp (zip) pra um
    destino seguro DENTRO de dest_dir - protege contra Zip Slip (entradas
    tipo 'assets/../../../etc/algo' ou caminho absoluto tentando escapar
    da pasta de destino). Devolve None se a entrada for suspeita."""
    dest_dir = os.path.abspath(dest_dir)
    name = (member_name or "").replace("\\", "/")
    name = name.lstrip("/")
    if not name or name.startswith("../") or "/../" in name or name == "..":
        return None
    target = os.path.abspath(os.path.join(dest_dir, name))
    if target != dest_dir and not target.startswith(dest_dir + os.sep):
        return None
    return target


def export_lsp(proj, dest_path=None):
    """Empacota o projeto inteiro (manifesto + scripts + assets) num
    arquivo `.Lsp` (um zip). Devolve o caminho final do arquivo."""
    if dest_path is None:
        dest_path = os.path.join(perms.storage_dir(), _safe_name(proj.name) + LSP_EXT)
    if not dest_path.lower().endswith(LSP_EXT.lower()):
        dest_path += LSP_EXT
    manifest_json = json.dumps(proj.manifest(), ensure_ascii=False, indent=2)
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(PROJECT_FILE, manifest_json)
        for name, code in proj.scripts.items():
            zf.writestr(SCRIPTS_DIR + "/" + name, code)
        assets_dir = os.path.join(proj.path, ASSETS_DIR) if proj.path else None
        if assets_dir and os.path.isdir(assets_dir):
            for root, _dirs, files in os.walk(assets_dir):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, proj.path)
                    zf.write(full, rel.replace(os.sep, "/"))
    return dest_path


# ------------------------------------------------------------- ler .Lsp
def read_lsp(lsp_path):
    """Le um `.Lsp` e devolve `(manifest, scripts)` sem gravar nada em
    disco -- e o que o LuaStudio Player usa pra rodar direto do pacote."""
    scripts = {}
    manifest = {}
    with zipfile.ZipFile(lsp_path, "r") as zf:
        names = zf.namelist()
        if PROJECT_FILE in names:
            try:
                manifest = json.loads(zf.read(PROJECT_FILE).decode("utf-8"))
            except Exception:
                manifest = {}
        prefix = SCRIPTS_DIR + "/"
        for n in names:
            if n.startswith(prefix) and n.lower().endswith(".lua"):
                short = n[len(prefix):]
                if "/" not in short:
                    scripts[short] = zf.read(n).decode("utf-8")
    if not manifest:
        manifest = {"name": os.path.splitext(os.path.basename(lsp_path))[0],
                    "entry": "main.lua", "scripts": sorted(scripts.keys())}
    if manifest.get("entry") not in scripts and scripts:
        manifest["entry"] = sorted(scripts.keys())[0]
    return manifest, scripts


def extract_lsp_assets(lsp_path, dest_dir):
    """Extrai so a pasta assets/ do `.Lsp` pra dest_dir (usado pra achar
    imagens/sons que os scripts do jogo referenciam)."""
    out_dir = os.path.join(dest_dir, ASSETS_DIR)
    with zipfile.ZipFile(lsp_path, "r") as zf:
        prefix = ASSETS_DIR + "/"
        for n in zf.namelist():
            if n.startswith(prefix) and not n.endswith("/"):
                target = _safe_extract_path(dest_dir, n)
                if target is None:
                    continue  # entrada suspeita (zip slip) - ignora
                target_folder = os.path.dirname(target)
                if not os.path.isdir(target_folder):
                    os.makedirs(target_folder)
                with open(target, "wb") as fh:
                    fh.write(zf.read(n))
    return out_dir


def import_lsp_as_project(lsp_path):
    """Importa um `.Lsp` pra dentro de Projects/, pra dar pra editar de
    volta no LuaStudio (IDE). Devolve o Project ja salvo em disco."""
    manifest, scripts = read_lsp(lsp_path)
    proj = create_project(manifest.get("name") or "Projeto importado")
    # renomeia cada script pelo mesmo sanitizador de add_script() - nomes
    # de dentro de um .Lsp nao sao confiaveis (podem ter vindo de um zip
    # editado a mao), entao nunca viram nome de arquivo direto no disco.
    safe_scripts = {}
    for raw_name, code in (scripts or {}).items():
        safe_scripts[_safe_script_name(raw_name)] = code
    proj.scripts = safe_scripts
    if not proj.scripts:
        proj.add_script("main.lua", DEFAULT_MAIN)
    proj.entry = manifest.get("entry", "main.lua")
    if proj.entry not in proj.scripts:
        proj.entry = sorted(proj.scripts.keys())[0]
    save_project(proj)
    try:
        extract_lsp_assets(lsp_path, proj.path)
    except Exception:
        pass
    return proj


def find_lsp_files():
    """Procura arquivos `.Lsp` nos lugares mais comuns (pasta do
    LuaStudio, raiz do armazenamento, Download) pra listar num popup de
    'Importar .Lsp'."""
    seen, out = set(), []
    storage = perms.storage_dir()
    bases = [storage]
    parent = os.path.dirname(storage.rstrip(os.sep))
    if parent:
        bases.append(parent)
        bases.append(os.path.join(parent, "Download"))
    for b in bases:
        if not b or not os.path.isdir(b):
            continue
        try:
            for fn in sorted(os.listdir(b)):
                if fn.lower().endswith(LSP_EXT.lower()):
                    full = os.path.join(b, fn)
                    if full not in seen:
                        seen.add(full)
                        out.append(full)
        except Exception:
            pass
    return out


# --------------------------------------------------- assets (importar)
def assets_dir(proj, create=False):
    """Caminho da pasta `assets/` do projeto (a pasta 'Source/Assets'
    que o navegador de arquivos usa como atalho). Se `create=True` e o
    projeto ja tem uma pasta no disco (`proj.path`), cria a pasta se
    ainda nao existir."""
    if not proj.path:
        return None
    path = os.path.join(proj.path, ASSETS_DIR)
    if create:
        try:
            if not os.path.isdir(path):
                os.makedirs(path)
        except Exception:
            pass
    return path


def _unique_name(dest_dir, name):
    """Evita sobrescrever: 'foto.png' -> 'foto_2.png' -> 'foto_3.png'..."""
    base, ext = os.path.splitext(name)
    candidate = name
    i = 1
    while os.path.exists(os.path.join(dest_dir, candidate)):
        i += 1
        candidate = "%s_%d%s" % (base, i, ext)
    return candidate


def import_asset_file(proj, src_path):
    """Copia um arquivo de QUALQUER pasta do dispositivo (escolhido no
    navegador de arquivos livre) pra dentro de `assets/` do projeto
    atual. Devolve o caminho relativo (ex: 'assets/personagem.png') pra
    usar em `SpriteSource` etc, ou None se falhar. Precisa que o
    projeto ja tenha sido salvo pelo menos uma vez (tem `proj.path`)."""
    if not proj.path or not src_path or not os.path.isfile(src_path):
        return None
    if not os.path.isdir(proj.path):
        try:
            os.makedirs(proj.path)
        except Exception:
            return None
    dest_dir = assets_dir(proj, create=True)
    if not dest_dir:
        return None
    name = _unique_name(dest_dir, os.path.basename(src_path))
    dest = os.path.join(dest_dir, name)
    try:
        shutil.copyfile(src_path, dest)
    except Exception:
        return None
    return "/".join([ASSETS_DIR, name])

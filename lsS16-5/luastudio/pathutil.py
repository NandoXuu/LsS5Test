# -*- coding: utf-8 -*-
"""Resolucao de caminhos relativos ao "Source" (raiz do projeto / do .Lsp).

O Source e a pasta raiz do projeto: na Engine e `Documents/<nome>/`, e
dentro de um `.Lsp` e o conteudo do proprio pacote. Um caminho como
`Assets/hero.png` e sempre relativo a essa raiz.

O Android costuma ser tolerante com maiusculas/minusculas e o Linux/Mac
nao; projetos antigos usavam `assets/...` e os novos usam `Assets/...`.
Por isso a busca tenta o caminho exato e, se nao achar, compara cada
pedaco ignorando maiusculas/minusculas.
"""

import os


def _match_ci(folder, name):
    """Entrada de `folder` cujo nome bate com `name` ignorando caixa."""
    try:
        low = name.lower()
        for entry in os.listdir(folder):
            if entry.lower() == low:
                return entry
    except OSError:
        pass
    return None


def find_ci(base, rel):
    """Caminho existente para `rel` dentro de `base` (tolerando caixa) ou
    None se nao existir."""
    rel = (rel or "").replace("\\", "/")
    exact = os.path.join(base, rel)
    if os.path.exists(exact):
        return exact
    cur = base
    for part in [p for p in rel.split("/") if p and p != "."]:
        if part == "..":
            return None
        nxt = os.path.join(cur, part)
        if not os.path.exists(nxt):
            real = _match_ci(cur, part)
            if real is None:
                return None
            nxt = os.path.join(cur, real)
        cur = nxt
    return cur if os.path.exists(cur) else None


def find_child_dir(base, name):
    """Subpasta de `base` chamada `name` (ignorando caixa), ou None."""
    real = _match_ci(base, name)
    if real is None:
        return None
    full = os.path.join(base, real)
    return full if os.path.isdir(full) else None


# ------------------------------------------------------------ assets
_INDEX = {}          # base -> (timestamp, {nome_minusculo: caminho})
_INDEX_TTL = 1.5     # segundos ate permitir re-varrer a pasta apos um miss
_SKIP_DIRS = {"__pycache__", ".lsfontcache"}


def _build_index(base):
    import time
    idx = {}
    count = 0
    for cur, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith(".") and d not in _SKIP_DIRS)
        for fn in sorted(files):
            idx.setdefault(fn.lower(), os.path.join(cur, fn))
            count += 1
            if count > 50000:
                break
    _INDEX[base] = (time.time(), idx)
    return idx


def _index_lookup(base, name):
    import time
    entry = _INDEX.get(base)
    if entry is None:
        idx = _build_index(base)
    else:
        idx = entry[1]
        if name not in idx and time.time() - entry[0] > _INDEX_TTL:
            idx = _build_index(base)      # arquivo novo (import) apareceu?
    return idx.get(name)


def find_asset(base, rel):
    """Acha um arquivo do projeto a partir do `Source` escrito no script.

    Ordem: caminho exato (ignorando caixa) -> dentro de Assets/ e Sound/ ->
    sem o primeiro pedaco ("assets/x.png" -> "x.png") -> so pelo NOME do
    arquivo em qualquer pasta do Source. Devolve None se nao achar."""
    if not rel:
        return None
    rel = str(rel).replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    rel = rel.lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    hit = find_ci(base, rel)
    if hit and os.path.isfile(hit):
        return hit
    for d in ("Assets", "Sound"):
        sub = find_child_dir(base, d)
        if sub:
            hit = find_ci(sub, rel)
            if hit and os.path.isfile(hit):
                return hit
    parts = rel.split("/")
    if len(parts) > 1:
        hit = find_ci(base, "/".join(parts[1:]))
        if hit and os.path.isfile(hit):
            return hit
    hit = _index_lookup(os.path.abspath(base), parts[-1].lower())
    if hit and os.path.isfile(hit):
        return hit
    return None


def describe_source(base):
    """Resumo curto do Source pra log: pasta e quantos arquivos tem em
    Assets/ e Sound/."""
    out = [os.path.abspath(base)]
    for d in ("Assets", "Sound"):
        sub = find_child_dir(base, d)
        n = 0
        if sub:
            for _cur, _dirs, files in os.walk(sub):
                n += len(files)
        out.append("%s: %d" % (d, n) if sub else "%s: (nao existe)" % d)
    return " | ".join(out)

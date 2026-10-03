# -*- coding: utf-8 -*-
"""Sistema de Tilemaps do LuaStudio.

Um "mapa" e um dict em memoria:

    {
      "package": "meujogo.mapa1",     # nome do pacote/mapa
      "tile_w": 64, "tile_h": 64,     # tamanho de cada tile, em pixels
      "cols": 100, "rows": 100,       # tamanho da grade
      "tileset": "tileset.png",       # nome do arquivo de imagem (fica na
                                       # MESMA pasta do arquivo do mapa)
      "layers": [
          {"name": "Layer1", "data": [0, 0, 3, 3, 3, 0, ...]}  # row-major,
      ]                                # 0 = tile vazio, N = tile N do atlas
    }

Dois formatos de arquivo, os dois lidos pela engine sem precisar escrever
nenhum codigo Lua de tilemap na mao - so `create.tilemap.Nome = {File=...}`:

  - ".lsm"    (LuaScriptMap): formato BINARIO proprio, compacto e rapido
              de ler - cada camada e comprimida com RLE (run-length: pares
              contagem+tile), o que fica muito pequeno em mapas com
              areas grandes repetidas/vazias (o caso comum de tilemap).
              E o formato RECOMENDADO (o Editor de Tilemaps marca ele
              como padrao) por causa da otimizacao de tamanho/velocidade.

  - ".JsonTm" (JSON Tile Mapping): JSON puro (minificado, sem indentacao,
              pra carregar mais rapido e pesar menos), bom pra debugar o
              mapa a olho ou editar na mao/por script externo.

Os dois guardam os MESMOS dados - dá pra converter de um pro outro sem
perda (ver `save`/`load`, que escolhem o formato pela extensao).
"""

import os
import json
import struct

MAGIC = b"LSM1"
FORMAT_VERSION = 1

EXT_LSM = ".lsm"
EXT_JSONTM = ".JsonTm"


# ------------------------------------------------------------------ dados
def new_map(package="mapa", tile_w=64, tile_h=64, cols=100, rows=100, tileset=""):
    """Cria um mapa novo, todo vazio (tile 0 em toda a grade)."""
    cols = max(1, int(cols))
    rows = max(1, int(rows))
    total = cols * rows
    return {
        "package": package or "mapa",
        "tile_w": max(1, int(tile_w)),
        "tile_h": max(1, int(tile_h)),
        "cols": cols,
        "rows": rows,
        "tileset": tileset or "",
        "layers": [{"name": "Layer1", "data": [0] * total}],
    }


def get_tile(map_data, col, row, layer=0):
    cols, rows = map_data["cols"], map_data["rows"]
    col, row = int(col), int(row)
    if col < 0 or row < 0 or col >= cols or row >= rows:
        return 0
    layers = map_data.get("layers") or []
    if layer < 0 or layer >= len(layers):
        return 0
    return layers[layer]["data"][row * cols + col]


def set_tile(map_data, col, row, tile_id, layer=0):
    cols, rows = map_data["cols"], map_data["rows"]
    col, row = int(col), int(row)
    if col < 0 or row < 0 or col >= cols or row >= rows:
        return False
    layers = map_data.get("layers") or []
    if layer < 0 or layer >= len(layers):
        return False
    layers[layer]["data"][row * cols + col] = int(tile_id) & 0xFFFF
    return True


def tile_uv(tile_id, tex_w, tex_h, tile_w, tile_h):
    """(u0, v0, u1, v1) do tile dentro do atlas do tileset, pro tile_id
    (1-based - quem chama ja filtrou o 0/vazio). Fatia o atlas em blocos
    de tile_w x tile_h, linha por linha (esquerda->direita, cima->baixo)."""
    tex_w, tex_h = max(1, int(tex_w)), max(1, int(tex_h))
    tile_w, tile_h = max(1, int(tile_w)), max(1, int(tile_h))
    tex_cols = max(1, tex_w // tile_w)
    idx = max(0, int(tile_id) - 1)
    tx, ty = idx % tex_cols, idx // tex_cols
    u0 = (tx * tile_w) / float(tex_w)
    u1 = ((tx + 1) * tile_w) / float(tex_w)
    # Kivy: v=0 e embaixo da textura, v=1 e em cima - a linha 0 do atlas
    # (topo do PNG) fica em v ALTO.
    v1 = 1.0 - (ty * tile_h) / float(tex_h)
    v0 = 1.0 - ((ty + 1) * tile_h) / float(tex_h)
    return u0, v0, u1, v1


def tileset_tile_count(tex_w, tex_h, tile_w, tile_h):
    cols = max(1, int(tex_w) // max(1, int(tile_w)))
    rows = max(1, int(tex_h) // max(1, int(tile_h)))
    return cols, rows, cols * rows


# --------------------------------------------------------- RLE (otimizacao)
def _rle_encode(ids):
    """[(contagem, tile_id), ...] - cada run cabe em uint16 (65535); runs
    maiores sao quebrados em varios pares."""
    runs = []
    n = len(ids)
    i = 0
    while i < n:
        v = ids[i]
        j = i + 1
        while j < n and ids[j] == v:
            j += 1
        count = j - i
        while count > 0:
            c = min(count, 65535)
            runs.append((c, v & 0xFFFF))
            count -= c
        i = j
    return runs


def _rle_decode(runs, total):
    out = []
    for count, tid in runs:
        out.extend([tid]) if count == 1 else out.extend([tid] * count)
    if len(out) < total:
        out.extend([0] * (total - len(out)))
    return out[:total]


def _pack_str(s):
    b = (s or "").encode("utf-8")
    return struct.pack("<H", len(b)) + b


def _unpack_str(buf, off):
    n = struct.unpack_from("<H", buf, off)[0]
    off += 2
    s = buf[off:off + n].decode("utf-8")
    return s, off + n


# ------------------------------------------------------------- .lsm (binario)
def save_lsm(map_data, path):
    """Grava em formato binario proprio (LuaScriptMap): header + camadas
    comprimidas com RLE. Bem menor e mais rapido de carregar que JSON em
    mapas grandes com bastante area repetida/vazia."""
    layers = map_data.get("layers") or []
    total = map_data["cols"] * map_data["rows"]
    buf = bytearray()
    buf += MAGIC
    buf += struct.pack("<B", FORMAT_VERSION)
    buf += struct.pack("<HHHH", map_data["tile_w"], map_data["tile_h"],
                        map_data["cols"], map_data["rows"])
    buf += struct.pack("<H", len(layers))
    buf += _pack_str(map_data.get("package") or "")
    buf += _pack_str(map_data.get("tileset") or "")
    for layer in layers:
        buf += _pack_str(layer.get("name") or "Layer")
        runs = _rle_encode(list(layer.get("data") or [])[:total])
        buf += struct.pack("<I", len(runs))
        for count, tid in runs:
            buf += struct.pack("<HH", count, tid)
    with open(path, "wb") as fh:
        fh.write(bytes(buf))
    return path


def load_lsm(path):
    with open(path, "rb") as fh:
        buf = fh.read()
    if buf[:4] != MAGIC:
        raise ValueError("arquivo .lsm invalido (assinatura incorreta)")
    off = 4
    off += 1  # versao (reservado pra compatibilidade futura)
    tile_w, tile_h, cols, rows = struct.unpack_from("<HHHH", buf, off)
    off += 8
    layer_count = struct.unpack_from("<H", buf, off)[0]
    off += 2
    package, off = _unpack_str(buf, off)
    tileset, off = _unpack_str(buf, off)
    total = cols * rows
    layers = []
    for _i in range(layer_count):
        name, off = _unpack_str(buf, off)
        run_count = struct.unpack_from("<I", buf, off)[0]
        off += 4
        runs = []
        for _r in range(run_count):
            count, tid = struct.unpack_from("<HH", buf, off)
            off += 4
            runs.append((count, tid))
        layers.append({"name": name, "data": _rle_decode(runs, total)})
    if not layers:
        layers = [{"name": "Layer1", "data": [0] * total}]
    return {"package": package, "tile_w": tile_w, "tile_h": tile_h,
            "cols": cols, "rows": rows, "tileset": tileset, "layers": layers}


# ------------------------------------------------------------- .JsonTm (json)
def save_jsontm(map_data, path):
    """JSON minificado (sem espacos/indentacao) - continua 100% legivel e
    editavel na mao, so nao desperdica bytes com formatacao."""
    payload = {
        "format": "JsonTm", "version": FORMAT_VERSION,
        "package": map_data.get("package") or "",
        "tile_w": map_data["tile_w"], "tile_h": map_data["tile_h"],
        "cols": map_data["cols"], "rows": map_data["rows"],
        "tileset": map_data.get("tileset") or "",
        "layers": [{"name": l.get("name") or "Layer", "data": list(l.get("data") or [])}
                   for l in (map_data.get("layers") or [])],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    return path


def load_jsontm(path):
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    cols = max(1, int(payload.get("cols") or 1))
    rows = max(1, int(payload.get("rows") or 1))
    total = cols * rows
    layers = []
    for l in (payload.get("layers") or []):
        data = [int(v) for v in (l.get("data") or [])]
        if len(data) < total:
            data.extend([0] * (total - len(data)))
        layers.append({"name": l.get("name") or "Layer", "data": data[:total]})
    if not layers:
        layers = [{"name": "Layer1", "data": [0] * total}]
    return {"package": payload.get("package") or "", "cols": cols, "rows": rows,
            "tile_w": max(1, int(payload.get("tile_w") or 64)),
            "tile_h": max(1, int(payload.get("tile_h") or 64)),
            "tileset": payload.get("tileset") or "", "layers": layers}


# --------------------------------------------------------------- dispatcher
def save(map_data, path, fmt=None):
    """Salva no formato pedido (`fmt` = 'lsm' ou 'json'/'jsontm') ou, se
    `fmt` nao for passado, decide pela extensao de `path`. Garante a
    extensao certa no arquivo final e devolve o caminho gravado."""
    fmt = (fmt or "").strip().lower()
    if not fmt:
        fmt = "lsm" if path.lower().endswith(EXT_LSM.lower()) else "json"
    if fmt == "lsm":
        if not path.lower().endswith(EXT_LSM.lower()):
            path += EXT_LSM
        return save_lsm(map_data, path)
    if not path.lower().endswith(EXT_JSONTM.lower()):
        path += EXT_JSONTM
    return save_jsontm(map_data, path)


def load(path):
    """Le `.lsm` ou `.JsonTm` (detecta pela extensao; qualquer outra
    extensao cai no leitor JSON, ja que e o formato mais tolerante)."""
    if path.lower().endswith(EXT_LSM.lower()):
        return load_lsm(path)
    return load_jsontm(path)


def tileset_path_for(map_path, map_data):
    """O tileset de um mapa mora do LADO do arquivo do mapa (mesma pasta) -
    assim o pacote (mapa + imagem) e sempre autocontido, em qualquer
    projeto/pasta onde for colocado."""
    name = map_data.get("tileset") or ""
    if not name:
        return None
    if os.path.isabs(name):
        return name
    return os.path.join(os.path.dirname(os.path.abspath(map_path)), name)

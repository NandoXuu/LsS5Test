# -*- coding: utf-8 -*-
"""Ponto de entrada do EDITOR DE TILEMAPS (app separado do LuaStudio).

No Pydroid 3: abra ESTE arquivo (nao o main.py do editor de codigo) e
toque em Play. Cria/edita mapas de tiles e salva .lsm ou .JsonTm prontos
pra soltar dentro da pasta assets/ de um projeto do LuaStudio.

IMPORTANTE: nada de pygame aqui (mesmo motivo do main.py principal) -
importar pygame antes do Kivy quebra o provider de janela SDL2 no
Pydroid 3.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "0")
try:
    from kivy.config import Config
    Config.set("kivy", "exit_on_escape", "0")
    # mesma correcao de "Too much StencilPop" do main.py principal - ver
    # o comentario la pra detalhes (MSAA x stencil buffer em GPUs Android).
    Config.set("graphics", "multisamples", "0")
    if Config.has_section("input"):
        for _key, _val in list(Config.items("input")):
            if "mtdev" in _val or "hidinput" in _val:
                Config.remove_option("input", _key)
except Exception:
    pass

if __name__ == "__main__":
    try:
        from luastudio.tilemap_editor_app import main
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print("[TilemapEditor] ERRO FATAL AO INICIAR:\n%s" % tb)
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(here, "TilemapEditor_erro.txt"), "w", encoding="utf-8") as fh:
                fh.write(tb)
        except Exception:
            pass
        raise

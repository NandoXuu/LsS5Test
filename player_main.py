# -*- coding: utf-8 -*-
"""LuaStudio Player - ponto de entrada PROPRIO, separado do editor.

Abra este arquivo (no Pydroid 3: toque em Play) pra abrir so o player:
uma tela pra escolher um pacote `.Lsp` e o jogo roda em tela cheia,
sem nenhuma parte de UI do editor (sem paleta de componentes, sem
palco de edicao, sem menus do LuaStudio - so o jogo).

Mesmos cuidados de inicializacao do `main.py` do editor: nada de
pygame antes do Kivy, e a config do Kivy precisa ser setada ANTES de
qualquer import do Kivy (por isso tudo isso vem primeiro neste
arquivo, igual no main.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Forca UTF-8 em stdout/stderr (mesmo motivo do main.py do editor).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Config do Kivy antes de qualquer import do Kivy.
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "0")
try:
    from kivy.config import Config
    Config.set("kivy", "exit_on_escape", "0")
    # Mesma correcao do editor: "Too much StencilPop (stack underflow)"
    # em algumas GPUs Android quando o multisample conflita com o
    # stencil buffer do clipping. Precisa ser setado ANTES da janela
    # ser criada.
    Config.set("graphics", "multisamples", "0")
    # Remove providers de input que nao existem no Android.
    if Config.has_section("input"):
        for _key, _val in list(Config.items("input")):
            if "mtdev" in _val or "hidinput" in _val:
                Config.remove_option("input", _key)
except Exception:
    pass

if __name__ == "__main__":
    try:
        from luastudio.player_app import main
        _lsp = None
        for _i, _a in enumerate(sys.argv[1:], 1):
            if _a == "--lsp" and _i + 1 < len(sys.argv):
                _lsp = sys.argv[_i + 1]
            elif _a.startswith("--lsp="):
                _lsp = _a.split("=", 1)[1]
        main(autoload=_lsp)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print("[LuaStudio Player] ERRO FATAL AO INICIAR:\n%s" % tb)
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(here, "LuaStudioPlayer_erro.txt"), "w", encoding="utf-8") as fh:
                fh.write(tb)
        except Exception:
            pass
        raise

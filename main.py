# -*- coding: utf-8 -*-
"""Ponto de entrada. No Pydroid 3: abra este arquivo e toque em Play.

IMPORTANTE: nada de pygame aqui. Importar pygame antes do Kivy quebra o
provider de janela SDL2 no Pydroid 3 ("Application didn't initialize
properly..."). O audio carrega pygame.mixer sob demanda, depois da janela.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Config do Kivy antes de qualquer import do Kivy.
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "0")
try:
    from kivy.config import Config
    Config.set("kivy", "exit_on_escape", "0")
    # CORRECAO: "Too much StencilPop (stack underflow)" - bug conhecido do
    # Kivy no Android quando o multisample (MSAA) da janela conflita com o
    # stencil buffer usado por ScrollView/clipping em certas GPUs (Adreno/
    # Mali). Desligar o multisample resolve. Precisa ser setado ANTES da
    # janela ser criada (por isso fica aqui, antes de qualquer outro import
    # do Kivy).
    Config.set("graphics", "multisamples", "0")
    # Remove providers de input que nao existem no Android (mtdev/hidinput).
    if Config.has_section("input"):
        for _key, _val in list(Config.items("input")):
            if "mtdev" in _val or "hidinput" in _val:
                Config.remove_option("input", _key)
except Exception:
    pass

# Nota: a mensagem "[ERROR] [Input] MTDev is not supported" do log do Kivy e
# apenas informativa no Android e nao impede o app de rodar.

if __name__ == "__main__":
    try:
        from luastudio.app import main
        main()
    except Exception:
        # Se ate a IMPORTACAO falhar (ex.: modulo faltando, erro de
        # sintaxe), garante que o erro apareca em algum lugar visivel,
        # mesmo que o console do Pydroid nao mostre nada.
        import traceback
        tb = traceback.format_exc()
        print("[LuaStudio] ERRO FATAL AO INICIAR:\n%s" % tb)
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(here, "LuaStudio_erro.txt"), "w", encoding="utf-8") as fh:
                fh.write(tb)
        except Exception:
            pass
        raise

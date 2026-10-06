# -*- coding: utf-8 -*-
"""Sistema de Temas de UI (`UI.Theme(nome, {...})` / `UI.SetTheme(nome)`).

Um tema e uma LuaTable com este formato (todas as chaves opcionais):

    UI.Theme("Cyberpunk", {
        Font = "assets/fonts/main.ttf",
        Colors = { Primary = "#00ffff", Background = "#080812", Text = "#fff" },
        Button = { Radius = 12, BorderSize = 2, ShadowBlur = 12 },
    })

Resolucao de uma propriedade (ex: Color) de um objeto com `Theme = "Cyberpunk"`:
  1. se a propriedade foi setada explicitamente pelo script -> ela sempre vence;
  2. senao, `theme.<Classe>.<Prop>` (ex: theme.Button.Radius);
  3. senao, um alias generico em `theme.Colors` (Color->Primary/Background,
     TextColor->Text, BorderColor->Border);
  4. senao, o valor padrao normal do objeto.

Ver `Instance.themed_value` em api.py - e la que essa resolucao acontece de
verdade; este modulo so guarda os temas registrados.
"""


class ThemeRegistry(object):
    def __init__(self):
        self._themes = {}
        self.current = None

    def register(self, name, table):
        self._themes[str(name)] = table

    def get(self, name):
        if not name:
            return None
        return self._themes.get(str(name))

    def set_current(self, name):
        self.current = str(name) if name else None

    def clear(self):
        self._themes = {}
        self.current = None


THEMES = ThemeRegistry()

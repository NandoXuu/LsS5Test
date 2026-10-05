-- 15: SUPER CUSTOMIZER - Theme/Style + Anchor relativo a tela
app.background("#080812")

-- ---- Theme: paleta + defaults por classe, aplicados so nas props que o
-- objeto NUNCA setou na mao (Style ainda pode sobrepor por estado) ----
UI.Theme("Cyberpunk", {
  Font = "",
  Colors = { Primary = "#2b2f52", Background = "#0c0f1c", Text = "#e6f7ff", Border = "#00ffff" },
  Button = { Radius = 14, BorderSize = 2, ShadowBlur = 14 },
})
UI.SetTheme("Cyberpunk")

create.label.Titulo = {
  Text = "Theme + Style + Anchor", Position = {20,16}, Size = {340,36},
  FontSize = 22, TextColor = "cyan",
}

-- Nao seta Color/Radius/BorderSize/BorderColor - tudo isso vem do tema.
create.button.Play = {
  Theme = "Cyberpunk", Text = "PLAY", Position = {30,70}, Size = {260,64},
  ShadowColor = "#00ffff", ShadowOffset = {0,0},
  Style = {
    Hover   = { Color = "#304080", BorderColor = "#66ffff" },
    Pressed = { Color = "#102040", Opacity = 0.9 },
    Disabled = { Color = "#303030", Opacity = 0.4 },
  },
  OnClick = function(self) print("jogar!") end,
}

-- ---- Anchor relativo a tela: fica preso ao canto/centro independente da
-- resolucao (essencial pra rodar em telas de Android com proporcoes
-- diferentes). Left/Top sao fracoes de 0..1 da tela; Offset e em pixels. ----
create.button.Configuracoes = {
  Theme = "Cyberpunk", Text = "Config", Size = {160,50},
  Anchor = { Left = 1.0, Top = 0.0 },   -- canto superior direito
  AnchorOffset = { X = -20, Y = 20 },
}

create.button.Sair = {
  Theme = "Cyberpunk", Text = "Sair", Size = {200,56},
  Anchor = { Left = 0.5, Top = 1.0 },   -- centro inferior
  AnchorOffset = { X = -100, Y = -30 },
  Style = { Hover = { Color = "#802030" } },
}

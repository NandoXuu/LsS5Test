-- 13: SUPER CUSTOMIZER - Mask (formas / texto / textura)
-- Mostra: mascara em forma (circulo), mascara de texto (o classico "texto
-- de fogo") e uma barra de vida com textura passando por uma mascara
-- retangular que encolhe conforme o Value.
app.background("#0e1220")

create.label.Titulo = {
  Text = "Mask", Position = {20,16}, Size = {300,36}, FontSize = 24, TextColor = "cyan",
}

-- ---- 1) avatar circular: qualquer imagem quadrada vira redonda ----
create.mask.Circulo = { Position = {30,70}, Size = {120,120}, Shape = "circle" }
create.image.Avatar = {
  Position = {30,70}, Size = {120,120}, Source = "assets/avatar.png",
  KeepAspect = false, Mask = "Circulo",
  BorderColor = "white", BorderSize = 3,
}

-- ---- 2) texto de fogo: a mascara e o proprio texto, o conteudo e uma
-- textura de fogo desenhada por baixo dela ----
create.mask.TextoFogo = {
  Position = {180,80}, Size = {260,100}, Shape = "text",
  Text = "FIRE", FontSize = 64,
}
create.image.Fogo = {
  Position = {180,80}, Size = {260,100}, Source = "assets/fire.png",
  Mask = "TextoFogo",
}

-- ---- 3) barra de vida com textura, recortada por uma mascara cujo
-- Size.x encolhe com o valor (0..1) - o classico "health bar" ----
local vida = 0.7
create.mask.VidaRecorte = { Position = {30,220}, Size = {320 * vida, 34}, Shape = "rectangle" }
create.image.VidaTextura = {
  Position = {30,220}, Size = {320,34}, Source = "assets/liquid.png",
  Mask = "VidaRecorte",
}
create.frame.VidaMoldura = {
  Position = {30,220}, Size = {320,34}, Color = "#00000000",
  BorderColor = "white", BorderSize = 2, Radius = 6,
}

create.button.Dano = {
  Text = "Tomar dano", Position = {30,270}, Size = {320,50}, Color = "#902030", Radius = 12,
  OnClick = function(self)
    vida = math.max(0, vida - 0.15)
    -- a mascara e so mais um objeto: mexer no Size dela recorta menos textura
    app.find("VidaRecorte").Size = {320 * vida, 34}
  end
}

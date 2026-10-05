app.background("#10131c")

create.label.Info = { Text = "", Position = {16,16}, Size = {600,120}, FontSize = 18, TextColor = "white" }
create.label.Acao = { Text = "", Position = {16,150}, Size = {600,40}, FontSize = 26, TextColor = "#ffd24a" }
create.textbox.Chat = { Position = {16,230}, Size = {420,52}, Color = "white", TextColor = "#222222", Radius = 8, FontSize = 20, Padding = 10, Placeholder = "Digite aqui (o jogo nao reage)" }

local A = keynumb.IsPressed("Z", 1)
local B = keynumb.IsPressed("X", 0.4)

onUpdate(function(dt)
  if B.pressed and A then
    app.find("Acao").Text = "ATAQUE ESPECIAL"
  elseif A.pressed then
    app.find("Acao").Text = "Ataque 1"
  elseif B.pressed then
    app.find("Acao").Text = "Ataque 2"
  end

  app.find("Info").Text = string.format(
    "Z abre janela de 1s: %.2fs\nX = especial dentro da janela\nDigitando: %s | Teclado fisico: %s",
    A.remaining, tostring(input.keyboard.isTyping()), tostring(input.keyboard.hasHardware()))
end)

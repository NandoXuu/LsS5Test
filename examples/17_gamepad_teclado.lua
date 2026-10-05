-- 17: Teclado + Gamepad (DualSense/Xbox/etc)
--
-- Teclado:  input.keyboard.isDown/isPressed/isReleased("SPACE")  lastKey()
-- Gamepad:  input.gamepad.isDown(id, "A")  (id opcional, padrao 0)
--           botoes: A B X Y LB RB LT RT LS RS START SELECT HOME DPAD_*
--           apelidos PlayStation: CROSS CIRCLE SQUARE TRIANGLE L1 R1 L2 R2 OPTIONS...
--           stick(id,"LEFT") -> {x,y,magnitude,angle}   (Y pra baixo; angle em graus)
--           trigger(id,"LT") -> 0..1     dpad(id) -> {x,y}
--           setDeadzone(id,"LEFT",0.15,"radial")  setCurve(id,"LEFT",1.5)
-- Atalhos:  input.bind("pular","SPACE","pad:A")  input.isPressed("pular")
--           input.bindAxis("horizontal","key:A","key:D","LEFT_X")
--           (letra sozinha = teclado; use "pad:A" pro botao A do controle)
-- Se algum botao/eixo do SEU controle vier trocado, use os numeros crus que
-- aparecem abaixo em "RAW" e ajuste: input.gamepad.map("A", 0)  mapAxis("LT", 4)

app.background("#0e1220")
create.label.Info = { Text = "", Position = {16,16}, Size = {420,150}, FontSize = 16, TextColor = "white" }
create.label.Raw  = { Text = "RAW: aperte algo no controle", Position = {16,170}, Size = {420,30}, FontSize = 14, TextColor = "#8fb4ff" }
create.frame.BarraLT = { Position = {16,210}, Size = {0,16}, Color = "#e0552b", Radius = 6 }
create.frame.BarraRT = { Position = {16,232}, Size = {0,16}, Color = "#2b6cf6", Radius = 6 }
create.part.Nave = { Position = {240,360}, Size = {36,36}, Color = "#4aa3ff" }

input.bind("pular", "SPACE", "pad:A")
input.bindAxis("horizontal", "key:A", "key:D", "LEFT_X")
input.bindAxis("vertical",   "key:W", "key:S", "LEFT_Y")

input.gamepad.setDeadzone("LEFT", 0.15, "radial")
input.gamepad.setCurve("LEFT", 1.5)

input.gamepad.onConnect(function(id) print("controle detectado:", id) end)
input.gamepad.onButton(function(id, nome, down)
  print("pad", id, nome, down and "apertou" or "soltou")
end)

local cor = false
local x, y = 240, 360          -- posicao da nave guardada em variaveis
onUpdate(function(dt)
  local nave = app.find("Nave")
  x = x + input.axis("horizontal") * 260 * dt
  y = y + input.axis("vertical") * 260 * dt

  local d = input.gamepad.dpad()
  x = x + d.x * 200 * dt
  y = y + d.y * 200 * dt
  nave.Position = { x, y }

  if input.isPressed("pular") then
    cor = not cor
    nave.Color = cor and "#ffd24a" or "#4aa3ff"
  end

  local s = input.gamepad.stick("LEFT")
  local lt = input.gamepad.trigger("LT")
  local rt = input.gamepad.trigger("RT")
  app.find("BarraLT").Size = { lt * 300, 16 }
  app.find("BarraRT").Size = { rt * 300, 16 }

  app.find("Info").Text = string.format(
    "Controles: %d | Tecla: %s | Botao: %s\nStick  x=%.2f y=%.2f mag=%.2f ang=%.0f\nLT=%.2f  RT=%.2f  dpad=(%d,%d)\nWASD/stick move, SPACE ou A pula",
    input.gamepad.count(), tostring(input.keyboard.lastKey()), tostring(input.gamepad.lastButton()),
    s.x, s.y, s.magnitude, s.angle, lt, rt, d.x, d.y)

  local r = input.gamepad.lastRaw()
  if r then
    app.find("Raw").Text = string.format("RAW: %s id=%d valor=%.2f (pad %d)", r.type, r.id, r.value, r.pad)
  end
end)

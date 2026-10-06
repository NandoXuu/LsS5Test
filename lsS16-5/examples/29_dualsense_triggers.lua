app.background("#0b0d16")
create.label.Info = { Text = "", Position = {16,16}, Size = {460,220}, FontSize = 16, TextColor = "white" }

local tr = dualsense.trigger
local presets = tr.presets()
local ri, li = 0, 0

tr.connect()

onUpdate(function(dt)
  if input.gamepad.isPressed("A") then
    ri = ri % #presets + 1
    tr.preset("R2", presets[ri], 1)
  end
  if input.gamepad.isPressed("B") then
    li = li % #presets + 1
    tr.preset("L2", presets[li], 1)
  end
  if input.gamepad.isPressed("X") then
    tr.spring("both", { start = 0.1, stop = 1, preload = 0.1, stiffness = 1, easing = "smooth" })
  end
  if input.gamepad.isPressed("Y") then
    tr.ramp("R2", 1.5, "vibration", { position = 0, amplitude = {0.2, 1}, frequency = {10, 60} }, { easing = "inout", loop = true })
  end
  if input.gamepad.isPressed("LB") then
    tr.sequence("both", {
      { effect = "weapon", start = 0.3, stop = 0.7, strength = 1, duration = 0.12 },
      { effect = "off", duration = 0.08 },
      { effect = "vibration", amplitude = {1, 0}, frequency = 45, duration = 0.25 },
    }, { loop = false })
  end
  if input.gamepad.isPressed("START") then tr.off("both") end
  if input.gamepad.isPressed("SELECT") then
    if tr.isConnected() then tr.disconnect() else tr.connect() end
  end

  local s = tr.status()
  app.find("Info").Text = string.format(
    "estado: %s (%s)\nR2: %s  [%s]\nL2: %s  [%s]\nA/B preset R2/L2 | X mola | Y rampa | LB sequencia\nSTART desliga | SELECT conecta/desconecta",
    s.state, s.backend, s.R2, presets[ri] or "-", s.L2, presets[li] or "-")
end)

app.background("#0b0d16")
create.label.Info = { Text = "", Position = {16,16}, Size = {440,160}, FontSize = 16, TextColor = "white" }

local cores = { "#ff0040", "#00e5ff", "#7cff4a", "#ffd24a", "#b34aff" }
local i = 0

dualsense.setColor("#ff00ff")
dualsense.setPlayer(1)

onUpdate(function(dt)
  if input.gamepad.isPressed("A") then
    i = i % #cores + 1
    dualsense.fade(cores[i], 0.4)
  end
  if input.gamepad.isPressed("B") then dualsense.pulse("#00e5ff", 1.2) end
  if input.gamepad.isPressed("X") then dualsense.blink("#ff0000", 0.12, 4) end
  if input.gamepad.isPressed("Y") then dualsense.rainbow(3) end
  if input.gamepad.isPressed("START") then dualsense.stopEffect() end
  if input.gamepad.isPressed("SELECT") then dualsense.off() end

  local lt = input.gamepad.trigger("LT")
  local rt = input.gamepad.trigger("RT")
  if lt > 0.05 or rt > 0.05 then
    dualsense.rumble(lt, rt, 0.1)
  end

  dualsense.setBrightness(1 - input.gamepad.trigger("LT") * 0.8)

  local bat = dualsense.battery()
  local c = dualsense.getColor()
  app.find("Info").Text = string.format(
    "%s\nconectado: %s | efeito: %s\ncor: %s\nbateria: %s",
    dualsense.name(), tostring(dualsense.isConnected()), tostring(dualsense.effect()),
    c and c.hex or "-", bat and string.format("%d%%%s", bat.level * 100, bat.charging and " (carregando)" or "") or "-")
end)

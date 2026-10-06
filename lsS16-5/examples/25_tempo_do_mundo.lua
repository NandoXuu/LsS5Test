-- 25_tempo_do_mundo.lua
-- environment.setConfig{TimeScale} = velocidade do MUNDO (fisica, sprites,
-- tweens, particulas, timers, camera, app.onUpdate).
-- pause.world() / pause.world(s) / pause.resume() = pausa so o mundo.
-- UI (botoes, labels, IgnoreCamera, TimeLayer = "ui"), input e
-- app.onUIUpdate continuam em tempo real.
app.background("#101218")

local bola = create.frame.Bola{
  Position = {60, 200}, Size = {40, 40}, Color = "#4ade80", Radius = 20,
  Physics = true, Velocity = {160, -300}
}

local info = create.label.Info{
  Position = {20, 20}, Size = {360, 30}, Text = "", TextColor = "white"
}

local menu = create.frame.Menu{
  Position = {20, 80}, Size = {240, 150}, Color = "#000000aa", Visible = false
}

local function setMenu(open)
  menu.Visible = open
  if open then pause.world() else pause.resume() end
end

create.button.Pausar{
  Position = {20, 250}, Size = {110, 48}, Text = "Menu",
  OnClick = function() setMenu(not pause.isPaused()) end
}

create.button.Lento{
  Position = {140, 250}, Size = {110, 48}, Text = "Lento 25%",
  OnClick = function() environment.setConfig({TimeScale = 0.25}) end
}

create.button.Normal{
  Position = {260, 250}, Size = {110, 48}, Text = "Normal",
  OnClick = function() environment.setConfig({TimeScale = 1}) end
}

create.button.Congela{
  Position = {380, 250}, Size = {140, 48}, Text = "Pausa 3s",
  OnClick = function() pause.world(3, function() app.log("mundo voltou!") end) end
}

-- logica de menu/HUD: sempre em tempo real
app.onUIUpdate(function(dt)
  info.Text = string.format("escala %.2f | %s | mundo %.1fs | UI %.1fs",
    environment.getTimeScale(),
    pause.isPaused() and "PAUSADO" or "rodando",
    environment.worldTime(), environment.uiTime())
end)

-- logica de jogo: dt do mundo (0 quando pausado, menor em camera lenta)
app.onUpdate(function(dt)
  -- ...
end)

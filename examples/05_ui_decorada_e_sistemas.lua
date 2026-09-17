-- 05: decoradores de UI, spritesheet, tween, timer, JSON e SaveData
app.background("#12141c")

-- botao com Gradient + Stroke + Shadow + Sprite interno + Transition (tudo por codigo,
-- sem arvore de nodes: e so configurar as propriedades no mesmo objeto)
local jogar = create.button.Jogar{ Position = {20,20}, Size = {200,56}, Text = "Jogar",
                                   Radius = 16, TextColor = "white" }
jogar.GradientColor1 = "#2b6cf6"
jogar.GradientColor2 = "#8a2be2"
jogar.GradientDirection = 90
jogar.StrokeColor = "white"
jogar.StrokeSize = 2
jogar.ShadowColor = "#00000090"
jogar.ShadowBlur = 14
jogar.Padding = 10
jogar:EnableTransition{ PressScale = 0.94, TransitionSpeed = 0.1 }
jogar.OnClick = function(self) app.log("jogar apertado") end

-- personagem animado via spritesheet (Sprite.Animate): 4 colunas x 2 linhas
local heroi = create.image.Heroi{ Position = {60,140}, Size = {64,64}, Source = "heroi.png",
                                  Columns = 4, Rows = 2, FrameSpeed = 10, Loop = true }

-- pulsa o heroi com Tween (sem precisar escrever a interpolacao a mao)
onUpdate(function(dt, t)
  -- nada aqui: o tween abaixo ja cuida da pulsacao, disparado uma vez
end)

local function pulsar()
  tween.to(heroi, { Scale = {1.15, 1.15, 1} }, 0.4, "ease_in_out", function()
    tween.to(heroi, { Scale = {1.0, 1.0, 1} }, 0.4, "ease_in_out")
  end)
end
timer.every(1.6, pulsar)

-- placar salvo entre execucoes com SaveData + JSON
local placar = create.label.Placar{ Position = {20,220}, Size = {260,30},
                                    TextColor = "yellow", FontSize = 18 }
local recorde = SaveData.get("recorde", 0)
placar.Text = "Recorde: " .. tostring(recorde)

local pontos = 0
onTouch(function(x, y, phase)
  if phase == "down" then
    pontos = pontos + Random.int(1, 10)
    if pontos > recorde then
      recorde = pontos
      SaveData.set("recorde", recorde)
    end
    placar.Text = "Pontos: " .. pontos .. "  |  Recorde: " .. recorde
  end
end)

-- 07: Audio HRTF 2D em tempo real
--
-- Camera2D acompanha o jogador. Monstros no espaço têm som: ao morrer,
-- caem "no limbo" (Position.Y sobe na tela, ou desce, dependendo do seu
-- jogo) e o som acompanha em tempo real, ficando mais abafado/agudo
-- conforme a posição relativa à câmera muda -- tudo suave, sem "pular".

app.background("#05050a")

local cam = create.camera2d.Cam{ Position = {0, 0}, Zoom = 1.0 }

local jogador = create.part.Nave{ Position = {0, 0}, Size = {40, 40}, Color = "#4aa3ff" }
cam.FollowTarget = jogador
cam.FollowSmooth = 0.15   -- câmera segue suave

-- Monstro no espaço, com um som (Loop) que representa o "motor"/rugido dele
local monstro = create.part.Monstro{ Position = {260, -140}, Size = {50, 50}, Color = "#ff5566" }
local somMonstro = create.sound.SomMonstro{ Source = "monstro_loop.ogg", Volume = 0.9, Loop = true }
somMonstro.Position = monstro.Position

-- Liga o panning 2D em tempo real: X = esquerda/direita, Y = "elevação"
-- (mais brilhante se estiver acima na tela, mais abafado se estiver abaixo).
sound.playHRTF2D("SomMonstro", {
  Bus = "SFX",
  Smooth = 0.12,          -- suavização (tween contínuo) em segundos
  PanRange = 500,         -- distância (mundo) pra pan chegar em -1/+1
  ElevationRange = 500,   -- distância (mundo) pra elevação chegar em -1/+1
  MinDistance = 0,
  MaxDistance = 1200,     -- além disso, volume vira 0
  MuffleCutoff = 600,     -- corte do abafado (Hz) -- mais baixo = mais abafado
  BrightGain = 6,         -- reforço de agudo quando o som vem "de cima" (dB)
})

app.onUpdate(function(dt, t)
  -- mantém o som grudado na posição do monstro (se ele se move sozinho)
  somMonstro.Position = monstro.Position
end)

-- Simula "atirar e matar o monstro": ele cai no limbo e o som some suave
function MatarMonstro()
  monstro.CastShadow = false
  -- a posição do som é tweenada -- o HRTF 2D lê a Position a cada frame,
  -- então o pan/elevação acompanham o tween automaticamente, sem código extra
  tween:to(somMonstro, { Position = vec2(monstro.Position.x, -400) }, 1.4, "ease_in")
  tween:to(monstro, { Position = vec2(monstro.Position.x, -400), Color = "#552233" }, 1.4, "ease_in", function()
    monstro.Visible = false
    sound.stopHRTF2D("SomMonstro")
  end)
end

local botaoAtirar = create.button.Atirar{ Position = {110, 500}, Size = {180, 56},
                                          Text = "Atirar no monstro", Radius = 14 }
botaoAtirar.OnClick = MatarMonstro

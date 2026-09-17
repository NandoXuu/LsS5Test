-- 04: fisica (gravidade, quique, Area2D) + escala/espelhamento por eixo
app.background("#0e1220")
physics.gravity(0, 900, 0)

create.label.Titulo = { Text = "Fisica + Escala", Position = {20,10}, Size = {320,36},
                        FontSize = 22, TextColor = "cyan" }

-- chao estatico (nao cai, mas outros colidem nele)
local chao = create.frame.Chao{ Position = {0,520}, Size = {360,20}, Color = "#33406b" }
chao:EnablePhysics{ Static = true }

-- bolinha caindo e quicando
local bola = create.frame.Bola{ Position = {60,60}, Size = {40,40}, Color = "orange", Radius = 20 }
bola:EnablePhysics{ Bounce = 0.6 }

-- caixa que estica e comprime nos dois eixos (nao so um) e depois espelha
local caixa = create.image.Caixa{ Position = {180,60}, Size = {80,80}, Source = "" ,
                                  Color = "#2b6cf6" }
caixa:EnablePhysics{ Bounce = 0.2, Friction = 0.4 }

onUpdate(function(dt, t)
  -- estica X e comprime Y ao mesmo tempo (nao trava num eixo so)
  local sx = 1.0 + 0.5 * math.sin(t * 2)
  local sy = 1.0 + 0.5 * math.cos(t * 2)
  caixa:Stretch(sx, sy)
  -- espelha horizontalmente a cada 2 segundos
  caixa:Flip(math.floor(t) % 2 == 0, false)
end)

-- Area2D: uma zona sensor que detecta quando a bola entra/sai (sem empurrar)
local zona = create.frame.Zona{ Position = {260,400}, Size = {90,90}, Color = "#22335533",
                                BorderColor = "lime" }
zona:MakeArea(true)
zona.OnAreaEnter = function(self, outro) app.log("entrou na zona:", outro.Name) end
zona.OnAreaExit  = function(self, outro) app.log("saiu da zona:", outro.Name) end

-- toque na tela empurra a bola pra cima (impulso)
onTouch(function(x, y, phase)
  if phase == "down" then
    bola:ApplyImpulse(0, -400, 0)
    android.vibrate(20)
  end
end)

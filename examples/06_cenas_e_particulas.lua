-- 06: Scene Manager (Scenes.register/load com fade) + Particle System

Scenes.register("menu", function()
  app.background("#101018")
  local titulo = create.label.Titulo{ Position={60,180}, Size={280,50},
                                      Text="MEU JOGO", FontSize=32, TextColor="white" }
  local jogar = create.button.Jogar{ Position={110,260}, Size={180,56}, Text="Jogar",
                                     Radius=14, GradientColor1="#2b6cf6", GradientColor2="#8a2be2" }
  jogar:EnableTransition{ PressScale=0.92 }
  jogar.OnClick = function() Scenes.load("jogo", 0.4) end   -- 0.4s = fade preto de ida e volta
end)

Scenes.register("jogo", function()
  app.background("#132018")
  create.label.HUD{ Position={10,10}, Size={200,30}, Text="Toque pra atirar faisca!", TextColor="yellow" }

  -- fogueira: emissor continuo
  local fogueira = create.particles.Fogo{ Position={200,420}, Rate=40, Emitting=true,
                                          Direction=-90, SpreadAngle=25,
                                          Speed={40,90}, Life={0.6,1.1},
                                          SizeStart=16, SizeEnd=2,
                                          Color1="orange", Color2="#ff000000" }

  local voltar = create.button.Voltar{ Position={10,540}, Size={120,44}, Text="< Menu", Radius=10 }
  voltar.OnClick = function() Scenes.load("menu", 0.4) end

  -- toque em qualquer lugar = explosao de faiscas (burst) naquele ponto
  onTouch(function(x, y, phase)
    if phase == "down" then
      local faisca = create.particles.Faisca{ Position={x,y}, Emitting=false,
                                              Color1="yellow", Color2="#ffffff00",
                                              SizeStart=10, SizeEnd=0, Life={0.3,0.5},
                                              Speed={80,160}, SpreadAngle=180 }
      faisca:Burst(20)
      android.vibrate(15)
    end
  end)
end)

Scenes.load("menu")

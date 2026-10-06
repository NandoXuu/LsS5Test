-- 12: Pitch ao vivo (streaming) -- muda em tempo real, sem pausar o som
--
-- Diferente de sound.playFX({Pitch=...}), que so fixa o pitch UMA vez no
-- instante em que o som comeca a tocar, aqui o pitch pode ser trocado a
-- qualquer momento -- inclusive com o som ja rodando -- sem cortar,
-- reiniciar ou dar nenhum "click". Da pra fazer sirene, vibrato, glide,
-- ou qualquer curva de pitch "tipo onda".

app.background("#0a0a12")
create.label.Info = { Text = "Pitch ao vivo (toque pra alternar o modo)",
  Position = {20,20}, Size = {360,40}, FontSize = 18, TextColor = "cyan" }

local motor = create.sound.Motor{ Source = "motor_loop.ogg", Volume = 0.8, Loop = true }

-- Comeca a tocar em stream, alimentado em pequenos pedacos (chunks) que
-- ja nascem com o pitch mais recente -- por isso da pra mudar sem pausa.
sound.playLivePitch("Motor", { Bus = "SFX", Pitch = 0, ChunkMs = 30 })

local modo = "sirene"   -- "sirene" (onda continua) ou "vibrato" (tremido rapido)

create.button.Alternar = { Text = "Alternar modo", Position = {20,80}, Size = {220,50},
  Color = "#2b6cf6", Radius = 12,
  OnClick = function()
    modo = (modo == "sirene") and "vibrato" or "sirene"
  end }

onUpdate(function(dt, t)
  local semitons
  if modo == "sirene" then
    -- onda lenta e ampla: sobe e desce +-7 semitons a cada ~4s
    semitons = math.sin(t * (2 * math.pi / 4.0)) * 7.0
  else
    -- vibrato rapido e sutil: +-0.5 semitom, ~6x por segundo
    semitons = math.sin(t * (2 * math.pi * 6.0)) * 0.5
  end
  sound.setPitch("Motor", semitons)   -- pode chamar todo frame, sem gaguejar
end)

-- Pra parar o streaming (ex.: ao trocar de cena):
-- sound.stopLivePitch("Motor")  -- ou sound.stop("Motor"), que ja cobre isso

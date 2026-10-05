-- 11: FREEDOM IN INTERFACE BUILDING
-- Custom UI / Custom Drawing / Immediate-mode / Custom Widget / HUD programming
--
-- `create.canvas` nao tem visual proprio: voce liga um `OnDraw`, e todo
-- frame ele te da um contexto `draw` com formas primitivas (arc, circle,
-- line, rect, polygon, text...) pra desenhar o que quiser, sem montar
-- nenhuma arvore de nodes - igual um _draw() customizado de outras
-- engines. Isso e o mesmo papel de:
--   Custom UI / Custom Controls, Custom Drawing / Procedural UI,
--   Immediate-mode drawing, Custom Widget, HUD/UI Programming, UI Authoring.

app.background("#0d0710")

-- ============================================================
-- WIDGET 1: barra semicircular de carregamento (sem shader, sem nodes extras)
-- ============================================================

local radius = 70
local thickness = 14
local start_angle = 0
local end_angle = 180        -- 0->180 = semicirculo de baixo

local progress = 0.0
local load_speed = 0.35
local wait_at_full = 0.15
local unload_speed = 1.2

local STATE_LOADING, STATE_WAITING, STATE_UNLOADING = 1, 2, 3
local state = STATE_LOADING
local wait_timer = 0.0

local medidor = create.canvas.Medidor{ Position = {60, 60}, Size = {160, 160} }

local function clamp01(v)
  if v < 0 then return 0 end
  if v > 1 then return 1 end
  return v
end

local function lerp(a, b, t)
  return a + (b - a) * t
end

medidor.OnDraw = function(self, draw)
  local cx, cy = 80, 80

  -- arco de fundo (bem apagado)
  draw.arc(cx, cy, radius, start_angle, end_angle, "#3f0d5920", thickness)

  if progress <= 0 then return end

  local current_angle = lerp(start_angle, end_angle, progress)
  local segments = math.max(2, math.floor(80 * progress))

  -- gradiente roxo: desenha em fatias, cada uma com uma cor um pouco
  -- mais clara (mesma ideia do exemplo original, sem shader nenhum)
  local dark = {0.12, 0.01, 0.22, 0.65}
  local bright = {0.75, 0.15, 1.0, 0.65}
  for i = 0, segments - 1 do
    local t1 = i / segments
    local t2 = (i + 1) / segments
    local a1 = lerp(start_angle, current_angle, t1)
    local a2 = lerp(start_angle, current_angle, t2)
    local col = {
      lerp(dark[1], bright[1], t1),
      lerp(dark[2], bright[2], t1),
      lerp(dark[3], bright[3], t1),
      dark[4],
    }
    draw.arc(cx, cy, radius, a1, a2, col, thickness)
  end
end

onUpdate(function(dt, t)
  if state == STATE_LOADING then
    progress = clamp01(progress + load_speed * dt)
    if progress >= 1.0 then
      progress = 1.0
      wait_timer = wait_at_full
      state = STATE_WAITING
    end
  elseif state == STATE_WAITING then
    wait_timer = wait_timer - dt
    if wait_timer <= 0 then
      state = STATE_UNLOADING
    end
  elseif state == STATE_UNLOADING then
    progress = clamp01(progress - unload_speed * dt)
    if progress <= 0 then
      progress = 0
      state = STATE_LOADING
    end
  end
end)

-- ============================================================
-- WIDGET 2: mira pulsando (custom UI, sem sprite nenhuma)
-- ============================================================

local mira = create.canvas.Mira{ Position = {320, 60}, Size = {80, 80} }
local pulse = 0.0

mira.OnDraw = function(self, draw)
  local center_x, center_y = 40, 40
  local pulse_size = math.sin(pulse * 3.0) * 4.0
  local r = 25 + pulse_size
  local line_size = 10.0
  local gap = 6.0
  local line_color = {0.75, 0.2, 1.0, 0.7}

  draw.circle(center_x, center_y, 3.0, {0.9, 0.5, 1.0, 0.9})

  draw.line(center_x - r - line_size, center_y, center_x - r - gap, center_y, line_color, 3)
  draw.line(center_x + r + gap, center_y, center_x + r + line_size, center_y, line_color, 3)
  draw.line(center_x, center_y - r - line_size, center_x, center_y - r - gap, line_color, 3)
  draw.line(center_x, center_y + r + gap, center_x, center_y + r + line_size, line_color, 3)
end

onUpdate(function(dt, t)
  pulse = pulse + dt
end)

-- ============================================================
-- BONUS: o canvas tambem recebe clique/hover como qualquer outro
-- controle 2D (OnClick/OnMouseEnter/OnMouseExit) - da pra construir um
-- "botao" 100% desenhado a mao, sem usar create.button.
-- ============================================================

local botao = create.canvas.BotaoCustom{ Position = {60, 260}, Size = {220, 56} }
local hover = false

botao.OnDraw = function(self, draw)
  local w, h = self.Size.x, self.Size.y
  local bg = hover and "#8a2be2" or "#3a1a55"
  draw.rect(0, 0, w, h, bg, h / 2)
  draw.rect_outline(0, 0, w, h, "#c07bff", 2, h / 2)
  draw.text(w / 2, h / 2 - 10, "JOGAR", "white", 20, nil, "center")
end

botao.OnMouseEnter = function(self) hover = true end
botao.OnMouseExit = function(self) hover = false end
botao.OnClick = function(self) app.log("botao customizado clicado") end

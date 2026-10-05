light2d.ambient("#ffffff", 0.05)

local img = create.image.Tijolo{
  Source = "assets/texture.png",
  NormalMap = "assets/normal.png",
  Position = {80, 80},
  Size = {360, 360},
  KeepAspect = true,
  Lit = true,
  Filter = "linear",

  NormalStrength = 2.0,
  FlipY = false,
  ViewNormal = false,

  Albedo = 1.0,
  Roughness = 0.5,
  Specular = 0.5,
  Metallic = 0.0,
  Emission = 0.0,
  AO = 1.0,
}

local luz = create.light2d.Luz{
  Type = "point",
  Color = "#FFCC80",
  Intensity = 5.0,
  Range = 350,
  Height = 100,
}

local angulo = 0
onUpdate(function(dt)
  angulo = angulo + dt * 1.2
  luz.Position = {260 + math.cos(angulo) * 126, 260 + math.sin(angulo) * 126, 0}
end)

local botaoNormal = create.button.Normal{ Position = {20, 460}, Size = {110, 44}, Text = "NORMAL" }
local botaoLuz = create.button.Luz{ Position = {140, 460}, Size = {110, 44}, Text = "LUZ" }
local botaoY = create.button.InverterY{ Position = {260, 460}, Size = {130, 44}, Text = "INVERTER Y" }

botaoNormal.OnClick = function() img.ViewNormal = true end
botaoLuz.OnClick = function() img.ViewNormal = false end
botaoY.OnClick = function() img.FlipY = not img.FlipY end

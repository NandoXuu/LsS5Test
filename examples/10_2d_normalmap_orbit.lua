local img = create.image.Image{
  Source = "assets/Image.png",
  NormalMap = "assets/ImageNormal.png",
  Position = {120, 120},
  Size = {320, 320},
  KeepAspect = true,
  Lit = true,
  Filter = "nearest",
}

local light = create.light2d.Orbit{
  Type = "point",
  Color = "#fff0c0",
  Intensity = 3.0,
  Range = 500,
  Height = 100,
  Enabled = true,
}

onUpdate(function(dt, t)
  local a = t * 1.2
  light.Position = {280 + math.cos(a) * 220, 280 + math.sin(a) * 220, 0}
end)

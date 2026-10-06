-- 02: Cena 3D (matematica pura)
app.background("#070b16")
create.camera.Main = { Position = {0,3,-9}, Target = {0,0,0}, FOV = 70 }

create.part.Chao  = { Shape="plane",  Position={0,-2,0}, Size={8,1,8}, Color="#22314d" }
create.part.Cubo  = { Shape="cube",   Position={-2.5,0,0}, Size={1,1,1}, Color="orange" }
create.part.Bola  = { Shape="sphere", Position={0,0,0},    Size={1.2,1.2,1.2}, Color="cyan" }
create.part.Pir   = { Shape="pyramid",Position={2.5,0,0},  Size={1,1.4,1}, Color="#c04af0" }

create.label.HUD = { Text="3D puro", Position={16,16}, Size={200,36}, FontSize=22, TextColor="white" }

onUpdate(function(dt, t)
  app.find("Cubo"):Rotate(50*dt, 70*dt, 0)
  app.find("Pir"):Rotate(0, 90*dt, 0)
  local b = app.find("Bola")
  b.Position = vec3(0, math.sin(t*2), 0)
  app.find("Main").Position = vec3(math.sin(t*0.5)*9, 3, math.cos(t*0.5)*-9)
end)

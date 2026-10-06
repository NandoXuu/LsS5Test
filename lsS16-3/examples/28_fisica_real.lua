app.background("#0e1220")
physics.world.Gravity = {0, 980}
physics.debug = {Colliders = true, Contacts = true, Velocity = true}

local chao = create.frame.Chao{Position = {0, 560}, Size = {800, 40}, Color = "#33406b"}
chao:EnablePhysics{Type = "static"}

local rampa = create.frame.Rampa{Position = {40, 330}, Size = {320, 16}, Color = "#4a5a8a", Rotation = 18}
rampa:EnablePhysics{Type = "static"}

local copo = create.frame.Copo{Position = {560, 440}, Size = {140, 120}, Color = "#00000000"}
copo:EnablePhysics{Type = "static"}
copo:AddCollider{Shape = "mesh", Points = {
    {-70, -60}, {-54, -60}, {-54, 44}, {54, 44}, {54, -60}, {70, -60}, {70, 60}, {-70, 60}
}}

local bola = create.frame.Bola{Position = {70, 200}, Size = {40, 40}, Color = "orange", Radius = 20}
bola:EnablePhysics{Type = "dynamic", Mass = 1, Friction = 0.8, Restitution = 0.3}
bola:AddCollider{Shape = "circle"}

local caixa = create.frame.Caixa{Position = {420, 100}, Size = {60, 60}, Color = "red"}
caixa:EnablePhysics{Type = "dynamic", Mass = 2, Restitution = 0.1}
caixa:AddCollider{Shape = "box"}
caixa.OnCollisionEnter = function(self, other, contact)
    app.log("Colisao:", other.Name, "impulso", math.floor(contact.Impulse))
end

local barra = create.frame.Barra{Position = {300, 40}, Size = {140, 20}, Color = "cyan"}
barra:EnablePhysics{Type = "dynamic", Mass = 1.5}
physics.joint.Revolute{A = barra, Anchor = {370, 50}}

local peso = create.frame.Peso{Position = {660, 120}, Size = {30, 30}, Color = "yellow"}
peso:EnablePhysics{Type = "dynamic", Mass = 1}
peso:AddCollider{Shape = "circle"}
local ancora = create.frame.Ancora{Position = {668, 40}, Size = {14, 14}, Color = "white"}
ancora:EnablePhysics{Type = "static"}
physics.joint.Spring{A = ancora, B = peso, Length = 90, Frequency = 1.5, DampingRatio = 0.15}

local plataforma = create.frame.Plataforma{Position = {200, 480}, Size = {160, 16}, Color = "lime"}
plataforma:EnablePhysics{Type = "kinematic"}
local dir = 1
app.onUpdate(function(dt)
    local x = plataforma.Position.x
    if x > 420 then dir = -1 elseif x < 160 then dir = 1 end
    plataforma:Move(70 * dir * dt, 0)
end)

local zona = create.frame.Zona{Position = {590, 500}, Size = {80, 40}, Color = "#22335533"}
zona:EnablePhysics{Type = "static"}
zona:AddCollider{Shape = "box", IsSensor = true}
zona.OnTriggerEnter = function(self, outro) app.log("entrou na zona:", outro.Name) end

onTouch(function(x, y, phase)
    if phase == "down" then
        bola:ApplyImpulse(0, -450)
        caixa:ApplyImpulse(150, -300, caixa.Position.x, caixa.Position.y)
        caixa:ApplyTorque(40000)
    end
end)

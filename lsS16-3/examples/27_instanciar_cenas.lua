-- 27: Instanciar cenas dentro de outras (scene.instantiate / Instance)
--
-- Crie um arquivo Enemy.lua (em Scripts/ ou em Scenes/) assim:
--
--   return {
--       Objects = {
--           { Class = "image", Name = "Body", Source = "Assets/enemy.png",
--             Position = {0, 0}, Size = {64, 64} },
--           { Class = "label", Name = "Name", Text = "Enemy", Position = {0, -20} },
--       },
--       Script = "Scripts/EnemyLogic.lua",   -- opcional; dentro dele `self` e o inimigo
--   }
--
-- Posicoes dentro de Objects sao LOCAIS (relativas ao Position do grupo).

local e1 = scene.instantiate("Enemy", { Position = {300, 200} })
local e2 = scene.instantiate("Enemy", { Position = {500, 200}, Scale = {2, 2}, Vida = 5 })
local e3 = Instance.Enemy{ Position = {700, 200} }        -- mesma coisa, outra sintaxe

e1.Position = {320, 240}      -- move o grupo inteiro
e2.Body.Tint = "red"          -- acessa cada objeto pelo Name
print(e2.Vida)                -- campos extras ficam guardados no grupo

local so_o_corpo = Instance.Enemy.Body{ Position = {100, 400} }   -- so UM objeto da cena

e3:Destroy()                  -- remove o grupo todo

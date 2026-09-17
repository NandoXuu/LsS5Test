-- 01: UI 2D basica
android.requestPermission("storage")
app.background("#0e1220")

create.label.Titulo = { Text = "UI 2D", Position = {20,20}, Size = {300,44}, FontSize = 28, TextColor = "cyan" }
create.frame.Painel = { Position = {20,80}, Size = {320,220}, Color = "#1b2136", Radius = 18 }

local cliques = 0
create.button.Contador = {
  Text = "Cliques: 0", Position = {40,110}, Size = {280,60}, Color = "#2b6cf6", Radius = 14,
  OnClick = function(self)
    cliques = cliques + 1
    self.Text = "Cliques: " .. cliques
    android.vibrate(30)
  end
}

create.toggle.Liga = { Position = {40,190}, Size = {80,40},
  OnChange = function(self, v) print("toggle:", v) end }

create.slider.Vol = { Position = {40,250}, Size = {280,30}, Min = 0, Max = 100, Value = 50,
  Color = "#333a55",
  OnChange = function(self, v) app.find("Titulo").Text = "Volume " .. math.floor(v) end }

create.label.Girando = { Text = "girando", Position = {40,330}, Size = {160,40}, Color = "#e0552b", Radius = 8 }
onUpdate(function(dt, t)
  app.find("Girando").Rotation = t * 60
end)

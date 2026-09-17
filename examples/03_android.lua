-- 03: Permissoes Android (Pydroid 3), imagens e sons
local ok, tbl = android.requestPermissions({"storage", "microphone", "vibrate"})
print("permissoes concedidas:", ok)
print("pasta:", android.storagePath())
android.toast("LuaStudio rodando!")

app.background("#101018")
create.label.Info = { Text = "Android: " .. tostring(android.isAndroid()),
  Position = {20,20}, Size = {320,40}, FontSize = 20, TextColor = "yellow" }

create.image.Logo = { Source = "assets/logo.png", Position = {20,80}, Size = {160,160} }

create.sound.Beep = { Source = "assets/beep.wav", Volume = 0.8, Loop = false }
create.button.Tocar = { Text = "Tocar som", Position = {20,260}, Size = {220,60},
  Color = "#2b6cf6", Radius = 14,
  OnClick = function() sound.play("Beep"); android.vibrate(50) end }

create.button.Salvar = { Text = "Salvar arquivo", Position = {20,340}, Size = {220,60},
  Color = "#1f9d55", Radius = 14,
  OnClick = function() print("gravado:", fs.write("teste.txt", "ola do Lua")) end }

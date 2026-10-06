-- 08: Unicode/UTF-8 completo + fontes customizadas
-- Coloque os arquivos de fonte em assets/fonts/ do projeto, ex.:
--   assets/fonts/myfontexample.ttf
--   assets/fonts/myfontexample.woff2
--   assets/fonts/myfontsvg.svg   (fonte SVG legada)
app.background("#0e1220")

-- strings ja aceitam qualquer alfabeto/emoji direto no codigo, sem nada
-- especial de configuracao (acentos, chines, arabe, emoji...)
create.text.pl = {
  Text = "FontExample: acentuação, emoji 🎮 e 中文 funcionam ✅",
  Position = {20, 20}, Size = {680, 50}, FontSize = 22, TextColor = "white",
  Font = "myfontexample.ttf",   -- "" (ou omitir) = fonte padrao do sistema
}

create.label.Info = {
  Text = "utf8.len(\"café\") = " .. utf8.len("café"),
  Position = {20, 80}, Size = {400, 40}, FontSize = 18, TextColor = "#8fb3ff",
}

create.button.TrocarFonte = {
  Text = "Trocar pra .woff2", Position = {20, 140}, Size = {280, 60},
  Color = "#2b6cf6", Radius = 14,
  OnClick = function(self)
    -- troca a fonte em tempo real; se o arquivo/formato nao existir ou
    -- faltar biblioteca (fonttools/brotli), o motor avisa no console e
    -- fica na fonte anterior, sem travar o jogo
    app.find("pl"):SetFont("myfontexample.woff2")
    self.Text = "Fonte trocada!"
  end
}

create.button.FonteSVG = {
  Text = "Trocar pra fonte SVG", Position = {20, 220}, Size = {280, 60},
  Color = "#e0552b", Radius = 14,
  OnClick = function(self)
    app.find("pl"):ReFont("myfontsvg.svg")   -- ReFont = mesma coisa que SetFont
  end
}

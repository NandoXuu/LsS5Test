-- TextBox nativo do LuaStudio: input real + renderer proprio.
app.background("#202020")

create.textbox.Login = {
    Position = {40, 80},
    Size = {500, 64},
    Color = "white",
    TextColor = "#222222",
    BorderColor = "red",
    BorderSize = 3,
    Radius = 10,
    FontSize = 24,
    Padding = 12,
    Placeholder = "Digite seu nome...",
    TextEffect = "rainbow",

    OnChange = function(self, texto)
        app.find("Preview").Text = "Texto: " .. texto
    end,

    OnSubmit = function(self, texto)
        print("Login/submit:", texto)
    end
}

create.label.Preview = {
    Position = {40, 170},
    Size = {700, 50},
    Text = "Texto: ",
    TextColor = "white",
    FontSize = 22,
    Align = "left"
}

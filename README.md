LuaStudio

LuaStudio é uma IDE e engine Open-Source para Lua, projetada principalmente para desenvolvimento de jogos e aplicações diretamente em celulares Android.

O projeto foi desenvolvido em Python utilizando Kivy, com um interpretador Lua próprio e sistemas de renderização, física, áudio, partículas, iluminação e interface integrados.

«🎮 Create. Code. Play. — Directly from your phone.»

---

✨ Recursos

📱 Mobile-first

O LuaStudio foi projetado para funcionar diretamente no Android através do Pydroid 3, permitindo criar e executar projetos Lua sem depender de um computador.

A interface inclui:

- Editor Lua com syntax highlighting
- Números de linha
- Auto-indentação
- Barra de símbolos para teclado touchscreen
- Terminal integrado
- Execução e parada do projeto
- Gerenciamento de arquivos
- Exemplos incluídos
- Sistema de permissões Android

---

🎨 Renderização 2D

O engine possui um sistema completo para criação de cenas 2D.

Objetos disponíveis:

create.button
create.label
create.text
create.frame
create.image
create.slider
create.toggle
create.particles
create.camera2d
create.light2d

Exemplo:

local player = create.image.Player{
    Source = "assets/player.png",
    Position = {100, 100},
    Size = {64, 64}
}

player.OnClick = function(self)
    print("Clicked!")
end

Também existem recursos como:

- Rotação
- Escala independente por eixo
- Espelhamento
- ZIndex
- Cores
- Bordas
- Gradientes
- Sombras
- Padding
- Sprites internos
- Animação por spritesheet
- Transições de UI
- Camera2D
- Screen shake
- Camera follow
- Limites de câmera
- Conversão World ↔ Screen

---

🧊 Renderização 3D

O LuaStudio também possui suporte a cenas 3D.

Objetos disponíveis:

create.part
create.camera
create.light

Shapes suportadas incluem:

cube
box
sphere
pyramid
cone
plane
cylinder

O sistema de renderização possui:

- Pipeline de renderização
- Batching
- Culling
- G-Buffer
- Deferred shading
- Iluminação
- Sombras
- Shaders
- PBR
- Toon shading
- Lambert
- Unlit
- Rim light
- Ambient occlusion aproximado

---

💡 Iluminação

O engine possui sistemas de iluminação independentes para 2D e 3D.

3D

create.light.Sun{
    Type = "directional",
    Color = "white",
    Intensity = 1,
    CastShadow = true
}

Tipos disponíveis:

directional
point
spot

2D

create.light2d.Lamp{
    Type = "point",
    Position = {300, 200},
    Range = 250,
    Intensity = 1,
    CastShadow = true
}

A iluminação 2D possui suporte a:

- Point lights
- Spot lights
- Directional lights
- Falloff
- Sombras por oclusão
- Luz ambiente
- Light filtering

A iluminação 2D é opt-in através de "Lit=true", mantendo compatibilidade com projetos antigos.

---

⚙️ Física

A física 2D pode ser ativada individualmente em objetos:

local player = create.part.Player{
    Position = {100, 100},
    Size = {50, 50},
    Physics = true
}

Suporta:

- Gravidade
- Colisão
- Objetos estáticos
- Áreas/sensores
- Velocidade
- Impulsos
- Bounce
- Friction
- Eventos de colisão

Exemplo:

player.OnCollide = function(self, other)
    print("Collision with:", other.Name)
end

---

🎵 Áudio

O LuaStudio possui sistema de áudio baseado em Pygame, carregado sob demanda.

Recursos incluem:

- Sons
- Loop
- Volume
- Mixer
- Buses
- Volume em dB
- Pitch shifting
- EQ
- Reverb
- Compressor
- Spatial audio
- Pan
- Atenuação por distância
- Doppler
- HRTF/áudio espacial

Buses disponíveis incluem:

Master
Music
SFX
Voice
UI

Alguns efeitos DSP dependem do "numpy".

---

✨ Partículas

O engine possui um sistema de partículas integrado:

create.particles.Fire{
    Rate = 20,
    MaxParticles = 200,
    Speed = {60, 60},
    Life = {1, 1},
    SizeStart = 10,
    SizeEnd = 2
}

É possível controlar:

- Emissão
- Quantidade máxima
- Velocidade
- Vida
- Tamanho inicial/final
- Direção
- Spread
- Gravidade
- Cores
- Área de emissão

---

🧮 Vector2 e Vector3

O LuaStudio possui objetos vetoriais próprios:

local position = Vector2.new(100, 200)

print(position.x)
print(position.y)

Operações disponíveis incluem:

:length()
:distance()
:normalize()
:lerp()
:dot()
:add()
:sub()
:scale()
:unpack()

"Vector3" também possui:

:cross()

---

📲 Android

O engine possui integração com recursos do Android através da API "android".

Exemplo:

if android.isAndroid() then
    android.vibrate(100)
end

Também existem funções para:

android.requestPermission()
android.requestPermissions()
android.hasPermission()
android.toast()
android.notify()

---

🛡️ Robustez

O runtime possui mecanismos para impedir que erros individuais destruam toda a execução.

Entre eles:

- Proteção contra divisão por zero
- Limite de instruções Lua
- Proteção contra loops infinitos
- Sanitização de "NaN" e "Infinity"
- Proteção do update por frame
- Isolamento de erros de física, partículas, animações e tweens
- Isolamento de erros de renderização por objeto
- Proteção contra "dt" extremamente alto
- Proteção contra Zip Slip na importação de projetos
- Restrição de acesso de arquivos fora da pasta do projeto

Por exemplo, um loop como:

while true do
end

não deve simplesmente congelar o aplicativo inteiro: o interpretador possui um orçamento de instruções para interromper a execução problemática.

---

🗂️ Estrutura do projeto

Uma estrutura básica pode ser:

MyGame/
├── main.lua
├── assets/
│   ├── player.png
│   └── music.wav
└── ...

O projeto também possui exemplos oficiais:

examples/
├── 01_ui_2d.lua
├── 02_cena_3d.lua
├── 03_android.lua
├── 04_fisica_e_escala.lua
├── 05_ui_decorada_e_sistemas.lua
├── 06_cenas_e_particulas.lua
└── 07_audio_hrtf2d.lua

---

🚀 Instalação no Android

Requisitos

- Android
- Pydroid 3
- Python
- Kivy

Clone o repositório:

git clone https://github.com/NandoXuu/LsS5Test.git

Entre na pasta:

cd LsS5Test

Instale as dependências:

pip install -r requirements.txt

Depois execute:

main.py

pelo Pydroid 3.

«Importante: no Pydroid 3, execute "main.py" diretamente. O projeto carrega o áudio sob demanda para evitar problemas de inicialização da janela do Kivy.»

---

💻 Desktop

Também é possível executar o projeto em ambientes desktop compatíveis com Python e Kivy.

pip install -r requirements.txt
python main.py

---

📚 Documentação

A documentação detalhada da API está disponível em:

doc.txt

Novidades e mudanças recentes:

NOVIDADES.md

Exemplos de código:

examples/

A API principal do engine está implementada em:

luastudio/api.py

---

🔧 Dependências

Principais dependências:

Kivy
Pillow
Pygments

Dependências opcionais:

Pygame
NumPy

O Pygame é utilizado principalmente para áudio, enquanto alguns recursos de DSP dependem do NumPy.

---

📖 Filosofia

O LuaStudio foi criado com uma ideia simples:

«desenvolver em Lua sem precisar de um PC.»

A proposta é colocar ferramentas normalmente encontradas em engines maiores dentro de um ambiente que possa ser executado diretamente em um celular.

O objetivo é tornar possível experimentar, programar e desenvolver jogos usando apenas um dispositivo Android.

---

🧪 Status

LuaStudio está em desenvolvimento.

Novos sistemas e melhorias continuam sendo adicionados ao engine, enquanto a compatibilidade com projetos existentes é mantida sempre que possível.

---

📄 Licença

Este projeto é Open-Source.

Consulte o arquivo de licença do repositório para obter os termos completos de uso, modificação e distribuição.

---

👤 Autor

NandoXuu 
(made with 50% IA WORK)
LuaStudio — uma engine Lua feita para desenvolvimento diretamente no celular.

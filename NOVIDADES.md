# Novidades do motor — LuaStudio / LuaStudioPlayer

Sistemas novos adicionados ao motor (mesmo código nos dois projetos, em
`luastudio/` e `luastudio_engine/`):

## Renderização
- **texture.py** — filtragem de textura (nearest / bilinear / trilinear+mipmap)
  com cache e batching (mesma imagem com filtros diferentes reaproveita os
  pixels já decodificados). Use `Filter` no SpriteSource: `"nearest"`,
  `"bilinear"`, `"trilinear"`.
- **pipeline.py** — render pipeline com estágios (cull → G-Buffer → sombras →
  deferred shading), batching de objetos por (malha, shader) e caching de
  iluminação para objetos com `Static = true`.
- **lighting.py** — objetos `create.light.Nome{...}` com `Type` (directional /
  point / spot), `Color`, `Intensity`, `Range`, `SpotAngle`, `CastShadow`,
  `Layer`, `Enabled`. Light filtering (máx. de luzes relevantes por objeto) e
  sombras planares suavizadas (várias amostras).
- **shading.py** — sistema de shaders por objeto (`Shader = "lambert" |
  "toon" | "unlit" | "pbr"`), G-Buffer lógico por face + deferred shading,
  especular, rim light e AO aproximado (advanced lighting/shadows).
- **postfx.py** — pós-processamento via Fbo+GLSL do Kivy: vinheta, bloom,
  aberração cromática, saturação e exposição. `postfx.set{Vignette=.., ...}`.

## Camera2D e Light2D (2D em paridade com o 3D)
- **camera2d.py / api.py** — `create.camera2d.Nome{ Position=, Zoom=, Rotation= }`:
  camera de verdade pro 2D (antes so existia camera 3D). A primeira criada
  vira a ativa automaticamente. Suporta `:Follow(alvo, suavizacao, offset)`,
  `:Shake(forca, duracao)` (screen shake), `:SetZoom/GetZoom/ZoomBy`,
  `:SetBounds/ClearBounds` (limite de mapa) e `:WorldToScreen/ScreenToWorld`,
  alem dos metodos genericos (:MoveTo, :Move, :Rotate, :GetPosition) que ja
  funcionavam em qualquer objeto. Objetos com `IgnoreCamera=true` continuam
  fixos na tela (HUD), por cima do resto - do jeito que sempre funcionou.
- **lighting2d.py** — `create.light2d.Nome{ Type="point"|"spot"|"directional",
  Color=, Intensity=, Range=, SpotAngle=, CastShadow=, Layer=, Enabled= }`:
  o mesmo sistema de luzes do 3D (lighting.py), adaptado pro plano XY do
  palco 2D - falloff quadratico, spot com cone em graus, light filtering
  (`light2d.setMaxLights(n)`) e sombras por oclusao de retangulo entre luz
  e objeto (objetos com `CastShadow=true`). `light2d.ambient(cor, intensidade)`
  controla a luz ambiente da cena. Objetos so recebem luz se tiverem
  `Lit=true` (opt-in, igual Physics/IsArea) - sem isso, nada muda.

Retrocompativel: sem `create.camera2d` nem `create.light2d` na cena, o 2D
renderiza exatamente como antes (nenhum objeto e afetado por padrao).

## Correções de robustez (crash / travamento / valores invalidos)
- **Divisao por zero** (`lua/interp.py`) - `1/0`, `0/0`, `x % 0`, `x // 0`
  agora geram um erro Lua tratavel em vez de produzir `Infinity`/`NaN`
  silenciosamente e deixar isso vazar pro renderer.
- **Loop infinito trava o app** - o orcamento de instrucoes do
  interpretador (`instruction_budget`) agora esta ligado de verdade (e
  resetado a cada frame/toque), e passou a valer tambem em `repeat...until`,
  `for` numerico e `for` generico (antes so `while` tinha protecao). Um
  `while true do end` (ou equivalente) agora da erro so naquele frame, em
  vez de travar o aplicativo inteiro.
- **NaN/Infinity podiam chegar no Kivy** - `safe_float()` sanitiza qualquer
  numero nao-finito no funil central de propriedades (`set_prop`, `to_vec`,
  `vec_table`, `to_color`, `Rotation`, `ZIndex`): NaN vira 0, Infinity vira
  um numero grande porem finito. Protege Position/Size/Scale/Rotation/cores/
  luzes/particulas contra "sumir" a UI por causa de um valor invalido.
- **`_tick()` sem protecao** (Player e Editor) - `runtime.update(dt)` e
  `stage.redraw()` agora tem `try/except` proprios: uma excecao num frame
  fica so no log, sem matar o `Clock.schedule_interval` (o que antes podia
  deixar a tela congelada/preta ate reabrir o app).
- **`dt` gigante** - `update()` agora usa `safe_dt()` (trava em 0.1s por
  frame), pra evitar saltos absurdos em fisica/tween/camera quando o app
  volta de segundo plano.
- **Frame isolado por etapa** - fisica, tween, particulas, timers,
  animacoes e Camera2D rodam via `_safe_step()` dentro de `update()`: se
  uma travar, as outras continuam no mesmo frame.
- **Render isolado por objeto e por camada** - `Stage.redraw()` agora
  sempre desenha o fundo antes de tudo, isola 3D e 2D um do outro, e cada
  objeto 2D é desenhado dentro de um `try/except` proprio (`_draw_one`) -
  um objeto com prop invalida some sozinho, sem apagar o resto da cena.
  `PushMatrix`/`PopMatrix` da Camera2D agora usam `try/finally`, entao a
  matriz da camera nunca "vaza" pro resto do frame se algo quebrar no meio.
- **Zip Slip na extracao de `.Lsp`** (`project.py`) - `extract_lsp_assets`
  valida que cada arquivo dentro do zip fica DENTRO da pasta de destino
  antes de escrever (`_safe_extract_path`); entradas tipo
  `assets/../../../etc/algo` sao ignoradas. `import_lsp_as_project` tambem
  passa os nomes de script pelo mesmo sanitizador de `add_script()`.
- **`require()`/`fs.read`/`fs.write` podiam escapar da pasta do projeto**
  - `Runtime.resolve()` agora bloqueia caminhos relativos com `..` que
  tentem sair de `base_dir` (devolve um caminho que nao existe, entao a
  leitura/escrita so falha normalmente, sem crashar).

## Áudio
- **audio_dsp.py** + **audio.py** — Mixer com buses (Master/Music/SFX/Voice/UI),
  volume em dB, roteamento (`mixer.route`, `mixer.setVolumeDB`); pitch
  shifting; EQ de 3 bandas; DSP (Reverb Schroeder, Compressor com
  attack/release); áudio espacial (pan + atenuação por distância + doppler
  leve) via `sound.playFX(nome, {Spatial=true, ...})` e `sound.setListener`.
  (Pitch/EQ/Reverb/Compressor precisam de `numpy` instalado; sem ele, o som
  toca normalmente, só sem o efeito.)

## Profiler
- **profiler.py** — `profiler.enable(true)`, `profiler.report()`,
  `profiler.fps()`. Mede tempo de render3d/render2d por frame.

## Audio HRTF 2D (panning por aproximacao da camera, em tempo real)
- **audio_dsp.py / audio.py** — novo sistema de panning 2D "estilo HRTF"
  pra jogos com `camera2d`: o som acompanha a posicao do objeto (X/Y) em
  relacao a camera, a cada frame, e:
  - eixo X -> pan estereo esquerda/direita (equal-power).
  - eixo Y -> "elevacao": o motor toca 3 camadas do mesmo som ao mesmo
    tempo (seca / abafada-grave / brilhante-aguda) e faz cross-fade de
    volume em tempo real entre elas conforme o som sobe ou desce na tela —
    sem precisar reprocessar audio a cada frame (so ajusta volume/pan dos
    3 canais). Simula a pista de elevacao do HRTF real (som de cima soa
    mais brilhante; som de baixo/longe soa mais abafado).
  - a posicao relativa e suavizada (`Smooth`, tipo um Tween continuo
    framerate-independente) pra nunca "pular" — o pan e a elevacao sempre
    deslizam suave enquanto o objeto se move, mesmo se a posicao for
    animada com `tween:to(objeto, {Position=...})`.
  - distancia tambem controla volume geral (atenuacao), igual ao
    espacial 3D ja existente.
- Uso: `sound.playHRTF2D("MonstroMorreu", {Bus="SFX", Smooth=0.12,
  PanRange=480, ElevationRange=480, MinDistance=0, MaxDistance=900,
  MuffleCutoff=650, BrightGain=5, BrightFreq=5000})`. Depois e so mover a
  `Position` do objeto som (na mao, com fisica, ou com `tween:to`) que o
  audio acompanha sozinho a cada frame. `sound.stopHRTF2D("Nome")` pra
  parar. Funciona automaticamente com o `create.camera2d` da cena (posicao
  + zoom + shake); `sound.setCamera2D(pos, zoom)` existe caso queira
  controlar a "camera de audio" na mao.
- Sem `numpy`, as camadas abafada/brilhante caem pra copia do som seco
  (sem quebrar o jogo), igual aos outros efeitos de DSP.

## API Lua nova (globals)
- `mixer.setVolume/setVolumeDB/setMute/route/dbToLinear/linearToDB`
- `postfx.set{Vignette=, Bloom=, Aberration=, Saturation=, Exposure=, Enabled=}`
- `profiler.enable/report/fps/reset`
- `sound.playFX(nome, opts)`, `sound.setListener(pos, forward)`
- `sound.playHRTF2D(nome, opts)`, `sound.stopHRTF2D(nome)`,
  `sound.setCamera2D(pos, zoom)` — panning 2D em tempo real (ver acima)
- `create.light.Nome{Type="point", Color="orange", Intensity=1.5, Range=15,
  CastShadow=true}`

Tudo é retrocompatível: cenas antigas sem luzes continuam com a luz
direcional fixa de sempre, e chamadas antigas de `render3d.project_scene`,
`audio.play/stop/stopAll` continuam funcionando sem mudar nada.


MADE by Humans WITH AI
(CHATGPT (CodeX) & CLAUDE CODE)

-- 09_glsl_pbr_normalmap.lua
-- Shader GLSL de verdade (GPU, por pixel) + normal map + PBR.
--
-- Leia GLSL_UPGRADE.md antes de mexer aqui: explica o que e real (roda na
-- GPU via kivy.graphics.RenderContext) e as limitacoes dessa primeira
-- versao (UV sintetico por face, sem IBL/reflexo de ambiente).

-- 1) Registra um shader GLSL. Pode ser GLSL "desktop" (como abaixo, com
--    #version/in/out) OU estilo GLSL ES (varying/gl_FragColor) -- o motor
--    adapta sozinho. Tambem da pra apontar pra um arquivo:
--    Fragment = "shaders/meu_shader.glsl"
create.shader.Ondas = {
  Fragment = [[
    #version 330 core

    in vec2 vTexCoord;
    uniform float uTime;

    out vec4 fragColor;

    void main() {
        // normal map + PBR ja vem prontos via stdlib injetada (unpackNormal/pbrLight)
        vec3 N = unpackNormal(uNormalMap, vTexCoord, normalize(vNormal), vTangent);
        vec3 albedo = uHasAlbedoMap > 0.5 ? sRGBToLinear(texture2D(uAlbedoMap, vTexCoord).rgb)
                                           : uBaseColor.rgb;
        vec3 lit = pbrLight(N, vWorldPos, albedo, uRoughness, uMetallic);

        // um toque animado por cima (usa uTime, so pra provar que roda por pixel)
        float pulse = 0.05 * sin(uTime + vTexCoord.x * 6.0);
        fragColor = vec4(linearToSRGB(lit + pulse), 1.0);
    }
  ]]
}

-- 2) Material: liga o shader a texturas + parametros PBR. NormalMap aceita
--    tabela (Source/Roughness/Metallic) ou so uma string com o caminho.
create.material.ChaoMat = {
  Shader    = "Ondas",
  Albedo    = "assets/chao.png",
  NormalMap = { Source = "assets/chao_normal.png", Roughness = 0.55, Metallic = 0.05 },
}

-- 3) Um `part` normal, so apontando `Material` pro nome registrado acima.
create.part.Chao = {
  Shape    = "plane",
  Material = "ChaoMat",
  Size     = { 12, 1, 12 },
  Position = { 0, 0, 0 },
}

-- objeto sem shader custom: continua desenhado do jeito de sempre (flat
-- shading em CPU), pra mostrar que os dois caminhos convivem na mesma cena
create.part.Caixa = {
  Shape    = "cube",
  Shader   = "pbr",
  Color    = "#c65b3f",
  Position = { 2, 1, 3 },
}

create.light.Sol = {
  Type      = "point",
  Position  = { 3, 6, -2 },
  Color     = "#fff1d6",
  Intensity = 2.2,
}

create.camera.Main = {
  Position = { 0, 4, -9 },
  Target   = { 0, 0, 0 },
  FOV      = 60,
}

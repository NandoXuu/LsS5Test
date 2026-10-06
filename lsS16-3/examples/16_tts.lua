-- 16: Text to Speech (voz sintetizada)
--
-- tts.speak(texto, idioma)                 fala sem travar o jogo
-- tts.speak(texto, idioma, funcao)         funcao(ok, erro) roda quando termina
-- tts.speak(texto, idioma, { Slow = false, Volume = 1.0, Interrupt = false, OnFinish = fn })
-- tts.stop()  tts.isSpeaking()  tts.setLanguage("pt")  tts.getLanguage()
--
-- Idiomas: "pt", "en", "es", "fr", "de", "it", "ja", "ko", "ru"...
-- Sotaques: "pt-BR", "pt-PT", "en-US", "en-GB", "es-MX", "fr-CA"...
-- Requer: pip install gTTS (e internet na primeira vez de cada frase).
-- A voz sai pelo bus "Voice": mixer.setVolume("Voice", 0.8).

app.background("#05050a")

function luastudiotts()
  tts.speak("Olá! Este é um teste de voz em português.", "pt")
  tts.speak("Hello! This is a voice test in English.", "en")
  tts.speak("¡Hola! Esta es una prueba de voz en español.", "es")
  tts.speak("Bonjour! Ceci est un test de voix en français.", "fr", function(ok, erro)
    if ok then print("terminou de falar") else print("erro: " .. tostring(erro)) end
  end)
end

luastudiotts()

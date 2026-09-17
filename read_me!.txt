LuaStudio Mobile
================
IDE Lua com Kivy + Pygame para Android (Pydroid 3).
Instale: kivy, pillow, pygments pelo Pip do Pydroid 3 (pygame e OPCIONAL,
somente para som).

IMPORTANTE (Pydroid 3): abra e execute SEMPRE o main.py. Nao execute nem
importe pygame antes do Kivy - isso faz o Kivy perder o provider de janela
("Application didn't initialize properly / Window = None"). Nesta versao o
pygame.mixer so e carregado quando um som e realmente tocado.
Abra main.py e toque em Play. Documentacao completa em doc.txt.

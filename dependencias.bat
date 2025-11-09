@echo off
title Instalador de Dependencias do Raposo Launcher
echo Instalando dependencias... Por favor, aguarde.

echo.
echo --- Instalando TTKBootstrap (para a interface) ---
python -m pip install ttkbootstrap

echo.
echo --- Instalando Requests (para downloads) ---
python -m pip install requests

echo.
echo --- Instalando Pillow (para imagens) ---
python -m pip install pillow

echo.
echo --- Instalando PyPresence (para o Discord) ---
python -m pip install pypresence

echo.
echo --- Instalacao Concluida! ---
echo.
pause
@echo off
title Limpar Cache de Icones - Windows
echo Limpando cache de icones do Windows...
echo.

taskkill /f /im explorer.exe >nul 2>&1
timeout /t 2 /nobreak >nul

del /f /q "%localappdata%\IconCache.db" >nul 2>&1
del /f /q "%localappdata%\Microsoft\Windows\Explorer\iconcache_*.db" >nul 2>&1
del /f /q "%localappdata%\Microsoft\Windows\Explorer\thumbcache_*.db" >nul 2>&1

timeout /t 2 /nobreak >nul
start explorer.exe

echo [OK] Cache limpo. O icone correto aparecera em instantes.
timeout /t 3 /nobreak >nul

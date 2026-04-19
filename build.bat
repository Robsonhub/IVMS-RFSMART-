@echo off
setlocal EnableDelayedExpansion
title Build — Monitor Tapete de Ouro

echo ============================================================
echo   Monitor CFTV — Tapete de Ouro  ^|  Build Script
echo ============================================================
echo.

:: Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale Python 3.10+ e adicione ao PATH.
    pause & exit /b 1
)

:: Instala/atualiza dependencias de runtime
echo [1/4] Instalando dependencias de runtime...
pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [ERRO] Falha ao instalar requirements.txt & pause & exit /b 1 )

:: Instala PyInstaller
echo [2/4] Instalando PyInstaller...
pip install pyinstaller>=6.0 --quiet
if errorlevel 1 ( echo [ERRO] Falha ao instalar PyInstaller & pause & exit /b 1 )

:: Limpa builds anteriores
echo [3/4] Limpando builds anteriores...
if exist dist\MonitorTapeteOuro rmdir /s /q dist\MonitorTapeteOuro
if exist build\MonitorTapeteOuro rmdir /s /q build\MonitorTapeteOuro

:: Gera o executavel
echo [4/4] Gerando executavel (pode demorar 2-5 minutos)...
pyinstaller monitor_tapete.spec --noconfirm
if errorlevel 1 ( echo [ERRO] Build falhou. Veja mensagens acima. & pause & exit /b 1 )

echo.
echo ============================================================
echo   Build concluido com sucesso!
echo   Pasta: dist\MonitorTapeteOuro\
echo   Execute:  dist\MonitorTapeteOuro\MonitorTapeteOuro.exe
echo ============================================================

:: Pergunta se quer gerar o instalador Inno Setup
where iscc >nul 2>&1
if errorlevel 1 (
    echo.
    echo [INFO] Inno Setup nao encontrado. Para gerar o instalador .exe:
    echo        1. Instale o Inno Setup: https://jrsoftware.org/isinfo.php
    echo        2. Execute:  iscc installer.iss
) else (
    echo.
    set /p GERAR_INSTALLER="Gerar instalador Windows (.exe)? [S/N]: "
    if /i "!GERAR_INSTALLER!"=="S" (
        echo Gerando instalador...
        iscc installer.iss
        if errorlevel 1 ( echo [AVISO] Falha ao gerar instalador. ) else (
            echo Instalador gerado em: dist\MonitorTapeteOuro_Setup.exe
        )
    )
)

pause

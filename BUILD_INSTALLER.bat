@echo off
setlocal EnableDelayedExpansion
title SPARTA AGENTE IA - Gerador de Instalador Windows
color 0A

echo.
echo ============================================================
echo   SPARTA AGENTE IA v1.1.0
echo   Gerador de Instalador Windows (.exe)
echo ============================================================
echo.

cd /d "%~dp0"

:: ── ETAPA 1: Verificar Python ─────────────────────────────────────────────
echo [1/6] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado.
    echo.
    echo Instale Python 3.10 ou superior:
    echo   https://www.python.org/downloads/
    echo Marque "Add Python to PATH" durante a instalacao.
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo [OK] Python %PYVER%
echo.

:: ── ETAPA 2: Instalar dependencias Python ────────────────────────────────
echo [2/6] Instalando dependencias...
python -m pip install --upgrade pip --quiet
python -m pip install anthropic opencv-python python-dotenv requests pyinstaller pillow onvif-zeep --quiet
if errorlevel 1 (
    echo [ERRO] Falha nas dependencias. Verifique a internet.
    pause & exit /b 1
)
echo [OK] Dependencias OK
echo.

:: ── ETAPA 3: Gerar icone .ico ────────────────────────────────────────────
echo [3/6] Gerando icone...
if exist "assets\logo_dark.png.png" (
    python convert_icon.py
    if errorlevel 1 (
        echo [AVISO] Icone nao gerado - executavel ficara sem icone personalizado.
    ) else (
        echo [OK] Icone: assets\sparta.ico
    )
) else (
    echo [AVISO] Logo nao encontrado - sem icone personalizado.
)
echo.

:: ── ETAPA 4: Build com PyInstaller ───────────────────────────────────────
echo [4/6] Gerando executavel (5 a 10 minutos, nao feche)...
echo.
if exist "dist\MonitorTapeteOuro"  rmdir /s /q "dist\MonitorTapeteOuro"
if exist "build\MonitorTapeteOuro" rmdir /s /q "build\MonitorTapeteOuro"

python -m PyInstaller monitor_tapete.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERRO] Build PyInstaller falhou. Veja o log acima.
    pause & exit /b 1
)
echo.
echo [OK] Executavel gerado em dist\MonitorTapeteOuro\
echo.

:: ── ETAPA 5: Verificar / Instalar Inno Setup ─────────────────────────────
echo [5/6] Verificando Inno Setup...

set "ISCC="
for %%P in (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
    "C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    "%USERPROFILE%\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
) do (
    if exist %%P set "ISCC=%%~P"
)

if defined ISCC goto :inno_ok

:: Tenta instalar via winget
echo [INFO] Inno Setup nao encontrado. Instalando via winget...
winget --version >nul 2>&1
if errorlevel 1 goto :inno_manual

winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements --silent
if errorlevel 1 goto :inno_manual

set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" goto :inno_ok

:inno_manual
echo.
echo [ATENCAO] Instale o Inno Setup manualmente:
echo.
echo   1. Acesse: https://jrsoftware.org/isinfo.php
echo   2. Baixe e instale o Inno Setup 6
echo   3. Execute este script novamente
echo.
pause & exit /b 1

:inno_ok
echo [OK] Inno Setup: %ISCC%
echo.

:: ── ETAPA 6: Gerar instalador .exe ───────────────────────────────────────
echo [6/6] Gerando instalador Windows...
echo.
"%ISCC%" installer.iss
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao gerar o instalador.
    pause & exit /b 1
)

echo.
echo ============================================================
echo   INSTALADOR GERADO COM SUCESSO!
echo.
echo   Arquivo: dist\SPARTA_AgentIA_Setup_v1.1.0.exe
echo.
echo   Este instalador:
echo   - Wizard profissional (Next / Next / Finish)
echo   - Termos de uso com aceite obrigatorio
echo   - Atalho na Area de Trabalho (opcional)
echo   - Aparece em Programas e Recursos do Windows
echo   - Desinstalador completo incluido
echo ============================================================
echo.
set "DIST_DIR=%~dp0dist"
echo Abrindo pasta: %DIST_DIR%
explorer.exe "%DIST_DIR%"
echo.
pause

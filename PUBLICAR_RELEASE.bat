@echo off
setlocal EnableDelayedExpansion
title SPARTA AGENTE IA - Publicar Release Servidor
color 0A

cd /d "%~dp0"

echo Diretorio: %CD%
echo.

:: ── Localiza Python (PATH primeiro, depois caminhos padrão) ───────────────
set "PY="
for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PY echo %%P | findstr /i "WindowsApps" >nul || set "PY=%%P"
)
if not defined PY (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "%PROGRAMFILES%\Python312\python.exe"
        "%PROGRAMFILES%\Python311\python.exe"
        "%PROGRAMFILES%\Python310\python.exe"
    ) do (
        if not defined PY if exist %%P set "PY=%%~P"
    )
)
if not defined PY (
    echo [ERRO] Python nao encontrado. Instale Python 3.10+ em:
    echo   https://www.python.org/downloads/
    pause & exit /b 1
)
echo [Python] %PY%
echo.

:: ── Lê versão do version.py ───────────────────────────────────────────────
"%PY%" -c "from version import VERSION; print(VERSION)" > "%TEMP%\sparta_ver.txt" 2>&1
if errorlevel 1 (
    echo [ERRO] Falha ao ler version.py:
    type "%TEMP%\sparta_ver.txt"
    echo.
    pause & exit /b 1
)
set /p VERSION=<"%TEMP%\sparta_ver.txt"
if not defined VERSION (
    echo [ERRO] Nao foi possivel ler a versao de version.py
    pause & exit /b 1
)
set "TAG=v%VERSION%"
set "ZIP_NAME=SPARTA_AgentIA_%TAG%.zip"
set "ZIP_PATH=dist\%ZIP_NAME%"
set "DIST_DIR=dist\MonitorTapeteOuro"

echo.
echo ============================================================
echo   SPARTA AGENTE IA %TAG%
echo   Build + Publicacao no servidor self-hosted
echo ============================================================
echo.

:: ── ETAPA 1: Verificar Python ─────────────────────────────────────────────
echo [1/5] Verificando Python...
"%PY%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python invalido: %PY%
    pause & exit /b 1
)
echo [OK]
echo.

:: ── ETAPA 2: Instalar dependencias Python ─────────────────────────────────
echo [2/5] Instalando dependencias Python...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install -r requirements.txt --quiet
"%PY%" -m pip install pyinstaller pillow --quiet
if errorlevel 1 (
    echo [ERRO] Falha nas dependencias.
    pause & exit /b 1
)
echo [OK]
echo.

:: ── ETAPA 3: Build PyInstaller ────────────────────────────────────────────
echo [3/5] Gerando executavel (pode demorar 5-10 min)...
echo.
if exist "%DIST_DIR%"  rmdir /s /q "%DIST_DIR%"
if exist "build\MonitorTapeteOuro" rmdir /s /q "build\MonitorTapeteOuro"

"%PY%" -m PyInstaller monitor_tapete.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERRO] Build PyInstaller falhou.
    pause & exit /b 1
)
echo [OK] Executavel em %DIST_DIR%\
echo.

:: ── ETAPA 3b: Criar .env padrão na pasta dist ─────────────────────────────
echo [3b] Criando .env padrao com UPDATE_SERVER_URL...
set "ENV_DIST=%DIST_DIR%\.env"
if not exist "%ENV_DIST%" (
    echo UPDATE_SERVER_URL=https://138.186.129.103:4543/latest.json> "%ENV_DIST%"
    echo [OK] .env criado em %ENV_DIST%
) else (
    findstr /i "UPDATE_SERVER_URL" "%ENV_DIST%" >nul 2>&1
    if errorlevel 1 (
        echo.>> "%ENV_DIST%"
        echo UPDATE_SERVER_URL=https://138.186.129.103:4543/latest.json>> "%ENV_DIST%"
        echo [OK] UPDATE_SERVER_URL adicionado ao .env existente
    ) else (
        echo [OK] .env ja contem UPDATE_SERVER_URL
    )
)
echo.

:: ── ETAPA 4: Empacotar .zip ───────────────────────────────────────────────
echo [4/5] Empacotando %ZIP_NAME%...
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"

:: Encerra o app se estiver rodando (libera arquivos bloqueados)
taskkill /f /im MonitorTapeteOuro.exe >nul 2>&1
timeout /t 2 /nobreak >nul

"%PY%" -c "import zipfile,pathlib;src=pathlib.Path(r'%DIST_DIR%');out=pathlib.Path(r'%ZIP_PATH%');zf=zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6);[zf.write(f,f.relative_to(src)) for f in src.rglob('*') if f.is_file()];zf.close();sz=round(out.stat().st_size/1048576,1);print(f'[OK] {out.name}  ({sz} MB)')"
if errorlevel 1 (
    echo [ERRO] Falha ao criar .zip
    pause & exit /b 1
)
echo.

:: ── ETAPA 5: Publicar no servidor self-hosted ─────────────────────────────
echo [5/5] Publicando no servidor self-hosted...
echo.

"%PY%" scripts\upload_to_vm.py "%ZIP_PATH%" "%VERSION%"
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao publicar no servidor.
    echo Verifique scripts\.env.publish e a conectividade SSH.
    pause & exit /b 1
)

echo.
echo ============================================================
echo   RELEASE %TAG% PUBLICADA COM SUCESSO!
echo   https://138.186.129.103:4543/latest.json
echo ============================================================
echo.
pause

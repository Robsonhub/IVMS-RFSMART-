@echo off
setlocal EnableDelayedExpansion
title SPARTA AGENTE IA - Publicar Release GitHub
color 0A

cd /d "%~dp0"

echo Diretorio: %CD%
echo.

:: ── Localiza Python ───────────────────────────────────────────────────────
set "PY="
for %%P in (
    "C:\Users\robso\AppData\Local\Programs\Python\Python312\python.exe"
    "C:\Users\robso\AppData\Local\Programs\Python\Python311\python.exe"
    "C:\Users\robso\AppData\Local\Programs\Python\Python310\python.exe"
) do (
    if not defined PY if exist %%P set "PY=%%~P"
)
if not defined PY (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PY echo %%P | findstr /i "WindowsApps" >nul || set "PY=%%P"
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
echo   Build + Publicacao automatica no GitHub
echo ============================================================
echo.

:: ── ETAPA 1: Verificar Python ─────────────────────────────────────────────
echo [1/6] Verificando Python...
"%PY%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python invalido: %PY%
    pause & exit /b 1
)
echo [OK]
echo.

:: ── ETAPA 2: Verificar GitHub CLI ─────────────────────────────────────────
echo [2/6] Verificando GitHub CLI (gh)...

:: Localiza gh.exe nos caminhos conhecidos
set "GH="
for %%G in (
    "C:\Program Files\GitHub CLI\gh.exe"
    "C:\Program Files (x86)\GitHub CLI\gh.exe"
) do ( if not defined GH if exist %%G set "GH=%%~G" )
if not defined GH (
    for /f "delims=" %%G in ('where gh 2^>nul') do if not defined GH set "GH=%%G"
)

if not defined GH (
    echo [INFO] GitHub CLI nao encontrado. Instalando via winget...
    winget install --id GitHub.cli --source winget --accept-package-agreements --accept-source-agreements --silent
    :: Atualiza PATH manualmente apos instalacao
    set "PATH=%PATH%;C:\Program Files\GitHub CLI"
    for %%G in ("C:\Program Files\GitHub CLI\gh.exe") do if exist %%G set "GH=%%~G"
)
if not defined GH (
    echo.
    echo [ERRO] GitHub CLI nao encontrado apos instalacao.
    echo Instale manualmente em https://cli.github.com e reabra o terminal.
    pause & exit /b 1
)
echo [OK] %GH%
echo.

:: ── Verifica autenticação ─────────────────────────────────────────────────
"%GH%" auth status >nul 2>&1
if errorlevel 1 (
    echo [INFO] Fazendo login no GitHub...
    "%GH%" auth login
    if errorlevel 1 (
        echo [ERRO] Login cancelado.
        pause & exit /b 1
    )
)

:: ── ETAPA 3: Instalar dependencias Python ─────────────────────────────────
echo [3/6] Instalando dependencias Python...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install anthropic opencv-python python-dotenv requests pyinstaller pillow onvif-zeep --quiet
if errorlevel 1 (
    echo [ERRO] Falha nas dependencias.
    pause & exit /b 1
)
echo [OK]
echo.

:: ── ETAPA 4: Build PyInstaller ────────────────────────────────────────────
echo [4/6] Gerando executavel (pode demorar 5-10 min)...
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

:: ── ETAPA 5: Empacotar .zip ───────────────────────────────────────────────
echo [5/6] Empacotando %ZIP_NAME%...
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

:: ── ETAPA 6: Publicar Release no GitHub ───────────────────────────────────
echo [6/6] Publicando Release %TAG% no GitHub...
echo.

"%GH%" release view %TAG% >nul 2>&1
if not errorlevel 1 (
    echo [AVISO] Release %TAG% ja existe no GitHub.
    set /p "SOBRESCREVER=Deseja deletar e recriar? (s/N): "
    if /i "!SOBRESCREVER!"=="s" (
        "%GH%" release delete %TAG% --yes --cleanup-tag
    ) else (
        echo Operacao cancelada.
        pause & exit /b 0
    )
)

"%GH%" release create %TAG% "%ZIP_PATH%" ^
    --title "SPARTA AGENTE IA %TAG%" ^
    --notes "Release automatica gerada pelo PUBLICAR_RELEASE.bat" ^
    --repo Robsonhub/IVMS-RFSMART-

if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao publicar no GitHub.
    pause & exit /b 1
)

echo.
echo ============================================================
echo   RELEASE %TAG% PUBLICADA COM SUCESSO!
echo   https://github.com/Robsonhub/IVMS-RFSMART-/releases/tag/%TAG%
echo ============================================================
echo.
pause

@echo off
setlocal EnableDelayedExpansion
title SPARTA AGENTE IA - Publicar Release GitHub
color 0A

cd /d "%~dp0"

echo Diretorio: %CD%
echo.

:: ── Lê versão do version.py ───────────────────────────────────────────────
python -c "from version import VERSION; print(VERSION)" > "%TEMP%\sparta_ver.txt" 2>&1
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
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale Python 3.10+
    pause & exit /b 1
)
echo [OK]
echo.

:: ── ETAPA 2: Verificar GitHub CLI ─────────────────────────────────────────
echo [2/6] Verificando GitHub CLI (gh)...
gh --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] GitHub CLI nao encontrado. Instalando via winget...
    winget install --id GitHub.cli --accept-package-agreements --accept-source-agreements --silent
    if errorlevel 1 (
        echo.
        echo [ERRO] Nao foi possivel instalar o GitHub CLI.
        echo Instale manualmente: https://cli.github.com
        pause & exit /b 1
    )
    :: Recarrega PATH
    call RefreshEnv.cmd >nul 2>&1
)
echo [OK]
echo.

:: ── Verifica autenticação ─────────────────────────────────────────────────
gh auth status >nul 2>&1
if errorlevel 1 (
    echo [INFO] Fazendo login no GitHub...
    gh auth login
    if errorlevel 1 (
        echo [ERRO] Login cancelado.
        pause & exit /b 1
    )
)

:: ── ETAPA 3: Instalar dependencias Python ─────────────────────────────────
echo [3/6] Instalando dependencias Python...
python -m pip install --upgrade pip --quiet
python -m pip install anthropic opencv-python python-dotenv requests pyinstaller pillow onvif-zeep --quiet
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

python -m PyInstaller monitor_tapete.spec --noconfirm
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

python -c "
import zipfile, pathlib
src = pathlib.Path(r'%DIST_DIR%')
out = pathlib.Path(r'%ZIP_PATH%')
files = [f for f in src.rglob('*') if f.is_file()]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for i, f in enumerate(files, 1):
        z.write(f, f.relative_to(src))
        print(f'\r  {int(i*100/len(files))}%% ({i}/{len(files)})', end='', flush=True)
print()
print(f'[OK] {out.name}  ({out.stat().st_size/1048576:.1f} MB)')
"
if errorlevel 1 (
    echo [ERRO] Falha ao criar .zip
    pause & exit /b 1
)
echo.

:: ── ETAPA 6: Publicar Release no GitHub ──────────────────────────────────
echo [6/6] Publicando Release %TAG% no GitHub...
echo.

:: Verifica se a tag já existe
gh release view %TAG% >nul 2>&1
if not errorlevel 1 (
    echo [AVISO] Release %TAG% ja existe no GitHub.
    set /p "SOBRESCREVER=Deseja deletar e recriar? (s/N): "
    if /i "!SOBRESCREVER!"=="s" (
        gh release delete %TAG% --yes --cleanup-tag
    ) else (
        echo Operacao cancelada.
        pause & exit /b 0
    )
)

gh release create %TAG% "%ZIP_PATH%" ^
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

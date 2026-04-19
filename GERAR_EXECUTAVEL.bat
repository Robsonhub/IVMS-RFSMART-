@echo off
setlocal EnableDelayedExpansion
title Gerador de Executavel — Monitor Tapete de Ouro
chcp 65001 >nul 2>&1
color 0A

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║     Monitor CFTV — Tapete de Ouro                       ║
echo  ║     Gerador de Executavel  (siga as etapas abaixo)      ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

set "PASTA=%~dp0"
set "PYTHON_EXE="
set "PYTHON_VER="

:: ─── ETAPA 1: Localizar Python ───────────────────────────────────────────────
echo  [1/5] Verificando se Python esta instalado...

for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python312\python.exe"
) do (
    if exist %%~P (
        set "PYTHON_EXE=%%~P"
        goto :python_encontrado
    )
)

:: Tenta pelo PATH
for /f "delims=" %%i in ('where python.exe 2^>nul') do (
    "%%i" --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%%i"
        goto :python_encontrado
    )
)

:: ─── Python não encontrado: instala via winget ───────────────────────────────
echo  [!] Python nao encontrado. Instalando automaticamente...
echo.

winget --version >nul 2>&1
if errorlevel 1 (
    echo  [ERRO] Nao foi possivel instalar Python automaticamente.
    echo.
    echo  Instale manualmente:
    echo    1. Acesse: https://www.python.org/downloads/
    echo    2. Clique em "Download Python 3.12.x"
    echo    3. Execute o instalador e marque "Add Python to PATH"
    echo    4. Depois rode este script novamente
    echo.
    pause & exit /b 1
)

echo  Instalando Python 3.12 via winget (aguarde)...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo  [ERRO] Falha na instalacao automatica do Python.
    echo  Instale manualmente em: https://www.python.org/downloads/
    pause & exit /b 1
)

:: Recarrega PATH
call refreshenv.cmd >nul 2>&1
set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "!PYTHON_EXE!" set "PYTHON_EXE=C:\Python312\python.exe"

:python_encontrado
for /f "tokens=2" %%v in ('"!PYTHON_EXE!" --version 2>&1') do set "PYTHON_VER=%%v"
echo  [OK] Python !PYTHON_VER! encontrado em: !PYTHON_EXE!
echo.

:: ─── ETAPA 2: Instalar dependencias ─────────────────────────────────────────
echo  [2/5] Instalando bibliotecas necessarias (pode demorar 2-5 min)...
"!PYTHON_EXE!" -m pip install --upgrade pip --quiet
"!PYTHON_EXE!" -m pip install anthropic opencv-python python-dotenv requests pyinstaller --quiet
if errorlevel 1 (
    echo  [ERRO] Falha ao instalar bibliotecas. Verifique sua conexao com a internet.
    pause & exit /b 1
)
echo  [OK] Bibliotecas instaladas.
echo.

:: ─── ETAPA 3: Limpar builds anteriores ───────────────────────────────────────
echo  [3/5] Limpando versoes antigas...
if exist "%PASTA%dist\MonitorTapeteOuro" rmdir /s /q "%PASTA%dist\MonitorTapeteOuro"
if exist "%PASTA%build\MonitorTapeteOuro" rmdir /s /q "%PASTA%build\MonitorTapeteOuro"
echo  [OK] Pasta limpa.
echo.

:: ─── ETAPA 4: Gerar executavel ───────────────────────────────────────────────
echo  [4/5] Gerando executavel (aguarde, pode demorar 3-8 minutos)...
echo  Nao feche esta janela!
echo.
cd /d "%PASTA%"
"!PYTHON_EXE!" -m PyInstaller monitor_tapete.spec --noconfirm
if errorlevel 1 (
    echo.
    echo  [ERRO] Falha ao gerar o executavel.
    echo  Tente rodar novamente. Se o erro persistir, veja o log acima.
    pause & exit /b 1
)
echo  [OK] Executavel gerado com sucesso!
echo.

:: ─── ETAPA 5: Montar pasta para pendrive ─────────────────────────────────────
echo  [5/5] Preparando pasta para copiar ao pendrive...

set "DESTINO=%PASTA%PENDRIVE_MonitorTapeteOuro"
if exist "%DESTINO%" rmdir /s /q "%DESTINO%"
mkdir "%DESTINO%"

xcopy /e /q "%PASTA%dist\MonitorTapeteOuro\*" "%DESTINO%\" >nul

:: Copia o instalador de configuracao (readme rapido)
(
echo Monitor Tapete de Ouro — Instrucoes
echo =====================================
echo.
echo 1. Copie esta pasta inteira para o computador de destino
echo 2. Execute MonitorTapeteOuro.exe
echo 3. Na primeira execucao, uma janela de configuracao abrira automaticamente
echo 4. Preencha:
echo    - Chave API Claude  (obtenha em: https://console.anthropic.com)
echo    - URL RTSP da camera Intelbras
echo 5. Clique em "Salvar e iniciar monitoramento"
echo.
echo Para reconfigurar no futuro: delete o arquivo .env e abra o programa novamente
echo Clips de alerta sao salvos na pasta: clips_alertas\
echo Log de eventos: monitor.log
) > "%DESTINO%\LEIA-ME.txt"

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║   CONCLUIDO COM SUCESSO!                                 ║
echo  ╠══════════════════════════════════════════════════════════╣
echo  ║                                                          ║
echo  ║  Pasta para copiar ao pendrive:                          ║
echo  ║  PENDRIVE_MonitorTapeteOuro\                             ║
echo  ║                                                          ║
echo  ║  Instrucoes para instalar na maquina destino:            ║
echo  ║  1. Copie a pasta do pendrive para o computador          ║
echo  ║  2. Execute MonitorTapeteOuro.exe                        ║
echo  ║  3. Configure a API key e URL da camera na tela           ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

explorer "%DESTINO%"
pause

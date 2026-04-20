@echo off
cd /d "%~dp0"
echo Gerando instalador...
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "installer.iss"
if errorlevel 1 (
    echo [ERRO] Falha ao gerar instalador.
    pause & exit /b 1
)
echo.
echo Instalador gerado: dist\SPARTA_AgentIA_Setup_v1.1.0.exe
explorer.exe "%~dp0dist"
pause

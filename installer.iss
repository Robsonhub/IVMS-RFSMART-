; Inno Setup Script — Monitor Tapete de Ouro
; Requer: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; Gerar apos o build.bat: iscc installer.iss

#define AppName      "Monitor Tapete de Ouro"
#define AppVersion   "1.0.0"
#define AppPublisher "Mineracao — Seguranca Patrimonial"
#define AppExeName   "MonitorTapeteOuro.exe"
#define SourceDir    "dist\MonitorTapeteOuro"

[Setup]
AppId={{B4A2C3D1-7E8F-4A5B-9C0D-1E2F3A4B5C6D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\MonitorTapeteOuro
DefaultGroupName={#AppName}
OutputDir=dist
OutputBaseFilename=MonitorTapeteOuro_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=no
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
; Copia toda a pasta gerada pelo PyInstaller
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";          FileName: "{app}\{#AppExeName}"
Name: "{group}\Configurar";          FileName: "{app}\{#AppExeName}"; Parameters: "--config"
Name: "{group}\Desinstalar";         FileName: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}";    FileName: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Abre o configurador apos instalar
Filename: "{app}\{#AppExeName}"; Description: "Abrir configuracao e iniciar monitoramento"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove logs e .env gerados em tempo de execucao
Type: files; Name: "{app}\monitor.log"
Type: files; Name: "{app}\.env"
Type: dirifempty; Name: "{app}"

[Code]
// Verifica que a pasta de build existe antes de continuar
function InitializeSetup(): Boolean;
var
  Msg: String;
begin
  Result := True;
  if not DirExists(ExpandConstant('{src}\{#SourceDir}')) then
  begin
    Msg := 'Pasta de build nao encontrada: ' + ExpandConstant('{#SourceDir}') + #13#10 +
           'Execute build.bat primeiro e depois gere o instalador.';
    MsgBox(Msg, mbError, MB_OK);
    Result := False;
  end;
end;

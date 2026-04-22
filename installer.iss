; Inno Setup 6 - SPARTA AGENTE IA

#define AppName      "SPARTA AGENTE IA"
#define AppVersion   "1.2.2"
#define AppPublisher "Tapete de Ouro - Seguranca Patrimonial"
#define AppExeName   "MonitorTapeteOuro.exe"
#define SourceDir    "dist\MonitorTapeteOuro"

[Setup]
AppId={{B4A2C3D1-7E8F-4A5B-9C0D-1E2F3A4B5C6D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
DefaultDirName={autopf}\SPARTA-AGENTE-IA
DefaultGroupName={#AppName}
OutputDir=dist
OutputBaseFilename=SPARTA_AgentIA_Setup_v{#AppVersion}
LicenseFile=TERMOS_DE_USO.rtf
WizardStyle=modern
DisableWelcomePage=no
PrivilegesRequired=lowest
CloseApplications=yes
Compression=lzma2/ultra64
SolidCompression=yes
VersionInfoVersion=1.2.2.0
VersionInfoProductName={#AppName}
VersionInfoProductVersion=1.2.1.0

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos"
Name: "startupicon"; Description: "Iniciar com o Windows"; GroupDescription: "Atalhos"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "TERMOS_DE_USO.rtf"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; FileName: "{app}\{#AppExeName}"
Name: "{group}\Desinstalar"; FileName: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; FileName: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; FileName: "{app}\{#AppExeName}"; Tasks: startupicon; Flags: runminimized

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Iniciar agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\monitor.log"
Type: files; Name: "{app}\.env"
Type: dirifempty; Name: "{app}"

[Code]
const
  UPDATE_SERVER_URL = 'https://138.186.129.103:4543/latest.json';

procedure EnsureUpdateServer();
var
  EnvFile, NewLine: String;
  Content: AnsiString;
begin
  EnvFile := ExpandConstant('{app}\.env');
  NewLine  := 'UPDATE_SERVER_URL=' + UPDATE_SERVER_URL;

  if not FileExists(EnvFile) then
  begin
    SaveStringToFile(EnvFile, NewLine + #13#10, False);
    Exit;
  end;

  if LoadStringFromFile(EnvFile, Content) then
  begin
    if Pos('UPDATE_SERVER_URL=', Content) = 0 then
      SaveStringToFile(EnvFile, #13#10 + NewLine + #13#10, True);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    EnsureUpdateServer();
end;


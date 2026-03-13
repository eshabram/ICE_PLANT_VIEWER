#define MyAppName "Ice Plant Viewer"
#define MyAppPublisher "ICE_PLANT"
#define MyAppExeName "Ice Plant Viewer.exe"
#define MyAppIconFile AddBackslash(SourcePath) + "..\assets\ice_plant.ico"

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#ifndef MyAppSourceDir
  #error MyAppSourceDir must be defined.
#endif

#ifndef MyAppOutputDir
  #define MyAppOutputDir AddBackslash(SourcePath) + "..\dist\releases"
#endif

[Setup]
AppId={{D37AA75A-1A4C-4ED8-9A58-062F4D7D1E7B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#MyAppOutputDir}
OutputBaseFilename=Ice-Plant-Viewer-{#MyAppVersion}-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile={#MyAppIconFile}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

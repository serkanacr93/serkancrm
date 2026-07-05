[Setup]
AppName=CRM Sistemi
AppVersion=1.0
DefaultDirName={autopf}\CRM Sistemi
DefaultGroupName=CRM Sistemi
OutputBaseFilename=CRM_Sistemi_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
OutputDir=.

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "dist\CRM_Sistemi.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CRM Sistemi"; Filename: "{app}\CRM_Sistemi.exe"
Name: "{commondesktop}\CRM Sistemi"; Filename: "{app}\CRM_Sistemi.exe"

[Run]
Filename: "{app}\CRM_Sistemi.exe"; Description: "CRM Sistemi'ni başlat"; Flags: nowait postinstall skipifsilent

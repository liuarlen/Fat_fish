#define ProjectDir AddBackslash(SourcePath) + ".."
#define BuildDir AddBackslash(ProjectDir) + "dist\Fat_fish"
#define AppExe "Fat_fish.exe"

#if !FileExists(BuildDir + "\" + AppExe)
  #error "Build the PyInstaller app first: dist\Fat_fish\Fat_fish.exe was not found."
#endif

[Setup]
AppId={{B5E5280A-6DE2-4C95-98E1-71519EF84F82}}
AppName=肥鱼译文
AppVersion=1.2.1
AppVerName=肥鱼译文 (Fat_fish) 1.2.1
AppPublisher=YiPage
DefaultDirName={code:GetDefaultDir}
DisableDirPage=no
DefaultGroupName=肥鱼译文
UninstallDisplayName=肥鱼译文
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile={#ProjectDir}\resources\app.ico
OutputDir={#ProjectDir}\dist
OutputBaseFilename=Fat_fish_Setup_1.2.1
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectDir}\packaging\使用说明.txt"; DestDir: "{app}"; DestName: "使用说明.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\肥鱼译文"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\肥鱼译文"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "启动肥鱼译文"; Flags: postinstall nowait skipifsilent

[Code]
function GetDefaultDir(Param: String): String;
begin
  Result := GetEnv('LOCALAPPDATA');
  if Result = '' then
    Result := GetEnv('USERPROFILE') + '\AppData\Local';
  Result := Result + '\Programs\Fat_fish';
end;

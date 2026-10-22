; ========================================================================
; 厦大体育馆自动预约工具 (XMU Gym Booking) - Inno Setup 安装包制作脚本
; 可使用 Inno Setup Compiler (ISCC.exe) 一键编译生成标准的 Windows 安装向导 EXE
; ========================================================================

#define MyAppName "厦大体育馆自动预约工具"
#define MyAppEnglishName "XMU_Gym_Booking"
#ifndef MyAppVersion
  #error MyAppVersion must be supplied by build_release.py
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build_release.py
#endif
#ifndef ReleaseOutput
  #error ReleaseOutput must be supplied by build_release.py
#endif
#define MyAppPublisher "XMU Open Source Community"
#define MyAppURL "https://github.com/hechen-coder/XMU-Gym-reservation-script"
#define MyAppExeName "XMU_Gym_Booking.exe"

[Setup]
; 基础应用信息
AppId={{9F82A4D1-5C8F-4A9B-B1D6-8F8D69A5E4E2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; 安装默认路径与开始菜单组
DefaultDirName={localappdata}\Programs\{#MyAppEnglishName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; 安装包产物输出配置
OutputDir={#ReleaseOutput}
OutputBaseFilename=XMU_Gym_Booking_Setup_v{#MyAppVersion}
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; 现代外观与高压缩比
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=auto

; 界面语言
[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"; Flags: checkedonce

[Files]
; 打包后的整个应用程序自包含目录
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "portable-mode"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 开始菜单项
Name: "{group}\{#MyAppName} (控制中心)"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\🌐 启动网页预约控制台"; Filename: "{app}\{#MyAppExeName}"; Parameters: "web"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\⏰ 启动早 7 点准点抢票"; Filename: "{app}\{#MyAppExeName}"; Parameters: "schedule"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\🌐 项目主页与在线说明"; Filename: "{#MyAppURL}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

; 桌面快捷方式 (默认以网页版直观打开)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Run]
; 安装完成后可选立即启动
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebView2: Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKCU, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM32, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM64, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + MemoGroupInfo + NewLine + MemoTasksInfo + NewLine +
    '若未安装 WebView2 Runtime，安装过程中需要联网下载窗口组件。已有 Runtime 时不会重复安装。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if not SaveStringToFile(ExpandConstant('{app}\installed-mode'), 'installed', False) then
      RaiseException('无法创建应用模式标记，请检查安装目录权限。');
    if not HasWebView2 then
    begin
      if not Exec(ExpandConstant('{app}\prerequisites\MicrosoftEdgeWebview2Setup.exe'),
        '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
        RaiseException('无法启动 WebView2 安装器，请在应用修复窗口中重试。');
      if ((ResultCode <> 0) and (ResultCode <> 3010)) or not HasWebView2 then
        RaiseException('WebView2 安装未完成。组件需要联网下载，请检查网络、权限，或重新打开应用的修复窗口。');
    end;
  end;
end;

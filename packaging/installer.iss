; ========================================================================
; 厦大体育馆自动预约工具 (XMU Gym Booking) - Inno Setup 安装包制作脚本
; 可使用 Inno Setup Compiler (ISCC.exe) 一键编译生成标准的 Windows 安装向导 EXE
; ========================================================================

#define MyAppName "厦大体育馆自动预约工具"
#define MyAppEnglishName "XMU_Gym_Booking"
#define MyAppVersion "1.1.2"
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
DefaultDirName={autopf}\{#MyAppEnglishName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; 安装包产物输出配置
OutputDir=..\dist
OutputBaseFilename=XMU_Gym_Booking_Setup_v{#MyAppVersion}
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; 现代外观与高压缩比
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=auto

; 界面语言
[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"; Flags: checkedonce

[Files]
; 打包后的整个应用程序自包含目录
Source: "..\dist\XMU_Gym_Booking\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 开始菜单项
Name: "{group}\{#MyAppName} (控制中心)"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\🌐 启动网页预约控制台"; Filename: "{app}\{#MyAppExeName}"; Parameters: "web"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\⏰ 启动早 7 点准点抢票"; Filename: "{app}\{#MyAppExeName}"; Parameters: "schedule"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\🌐 项目主页与在线说明"; Filename: "{#MyAppURL}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

; 桌面快捷方式 (默认以网页版直观打开)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "web"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Run]
; 安装完成后可选立即启动
Filename: "{app}\{#MyAppExeName}"; Parameters: "web"; Description: "立即运行 {#MyAppName} (打开网页版)"; Flags: nowait postinstall skipifsilent

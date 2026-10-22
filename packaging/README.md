# 构建与打包

保留 Python 3.8 Windows x64。构建不会自动安装或升级依赖，不结束正在使用的旧应用，也不会删除或覆盖已有 `dist` 内容。

1. 准备通过原生库自检的 Python 3.8 x64 环境；直接依赖版本基线见 `constraints-python38.txt`。它是本机版本约束，不等于已经在干净环境验证的完整 wheel 锁文件。
2. 安装 Inno Setup 6 编译器。当前本机位置为 `D:\Inno Setup 6\ISCC.exe`，也可通过 `--iscc` 指定其他位置。
3. 从 [微软官方页面](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) 获取约 2 MB 的 **Evergreen Bootstrapper**，放在 `packaging/prerequisites/MicrosoftEdgeWebview2Setup.exe`，或通过参数指定现有文件。已有 Runtime 时不下载，缺失或修复时需要联网。

```powershell
conda activate base
python packaging/build_release.py --check --runtime-installer "D:\Downloads\MicrosoftEdgeWebview2Setup.exe" --iscc "D:\Inno Setup 6\ISCC.exe"
python packaging/build_release.py --runtime-installer "D:\Downloads\MicrosoftEdgeWebview2Setup.exe" --iscc "D:\Inno Setup 6\ISCC.exe"
```

默认构建 ZIP 和 Setup 两种制品。只有显式 `--portable-only` 才跳过 Setup，此模式不能视为完整双制品发布。`--no-obfuscation` 仅用于明确选择的诊断构建，正式混淆失败会停止，不自动退回明文构建。

新产物写入 `dist/releases/v版本/UTC时间-随机批次/`；每次使用全新目录，旧 ZIP、便携文件夹和校验清单全部保留。源码在 `build/releases/批次/source` 快照中混淆，开发目录保持原样。

构建前验证微软安装器签名和原生依赖；构建后复制产物执行真实 OCR、加密模块、授权模块与回环 HTTP 自检。失败目录保留 `BUILD_INCOMPLETE`，禁止发布。成功后仍须完成干净 Windows 上的实际界面及组件安装验收。

完整步骤见 [发布指南](../docs/打包与发布部署指南.md)，设计与验收矩阵见 [兼容性方案](../docs/打包与启动兼容性优化方案.md)。

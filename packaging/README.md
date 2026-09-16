# 厦大体育馆自动预约工具 - 发布与安装包构建系统

本文档详细介绍了如何将本项目打包构建为**供普通电脑用户直接下载使用的安装包与免安装便携版**。

---

## 🌟 整体发布方案概览

许多开源项目之所以能够提供诸如 `.exe` 安装程序或 `.zip` 解压即用包，是因为建立了一套完整的打包与持续集成（CI/CD）流水线：

```
源码与静态资源 
    │
    ├── 1. 启动入口适配器 (packaging/launcher.py)
    │      └─ 解决工作目录漂移，提供双击无参数交互菜单与自动打开网页
    │
    ├── 2. PyInstaller 编译 (packaging/XMU_Gym_Booking.spec)
    │      └─ 自动提取 ddddocr 的 ONNX 深度学习模型，排除 Anaconda 冗余巨库
    │
    ├── 3. 绿色便携版压缩 (dist/XMU_Gym_Booking_v1.0.0_Portable_Windows_x64.zip)
    │      └─ 解压即用，内置启动脚本与小白使用说明
    │
    ├── 4. Inno Setup 安装向导 (packaging/installer.iss)
    │      └─ 编译生成标准的 Windows 安装向导 (dist/XMU_Gym_Booking_Setup_v1.0.0.exe)
    │
    └── 5. GitHub Actions 云端流水线 (.github/workflows/release.yml)
           └─ 推送 Git Tag 自动在微软云端打包并发布到 GitHub Releases 供全球下载
```

---

## 🚀 本地一键打包步骤

### 方式一：鼠标双击一键打包（最简单）
在 `packaging/` 文件夹下，直接双击运行：
👉 **`一键构建发布包.bat`**

脚本将全自动检测环境、编译可执行程序、组装便携包并计算 SHA256 校验和。

### 方式二：终端命令行打包
在项目根目录下打开命令行运行：
```bash
python packaging/build_release.py
```

构建完成后，所有产物将自动存放在项目根目录下的 **`dist/`** 目录中：
- 📁 **`dist/XMU_Gym_Booking/`**：自包含的绿色免安装运行目录；
- 📦 **`dist/XMU_Gym_Booking_v1.0.0_Portable_Windows_x64.zip`**：压缩便携版（可直接上传网盘或群文件分享）；
- 💿 **`dist/XMU_Gym_Booking_Setup_v1.0.0.exe`**：Windows 安装向导程序（若本地安装了 Inno Setup 6 将自动生成）；
- 📝 **`dist/SHA256SUMS.txt`**：文件完整性校验哈希清单。

---

## 💿 Windows 安装包制作 (Inno Setup)

本项目已编写完整的安装向导脚本 `packaging/installer.iss`：
- **安装效果**：如同常规商业软件，提供许可说明、自定义安装路径、创建桌面快捷方式与开始菜单，并自带卸载工具。
- **本地编译前提**：电脑需安装免费开源的 [Inno Setup 6](https://jrsoftware.org/isdl.php)。
- 安装后将 `ISCC.exe` 所在目录加入环境变量，或者再次运行 `python packaging/build_release.py`，系统即可自动检测并编译出 Setup 安装包。

---

## ☁️ GitHub Actions 云端自动发布（推荐开源实践）

你无需在自己的电脑上安装 Inno Setup 或耗费 CPU 编译：
1. 将本项目推送到你的 GitHub 仓库；
2. 在本地打上版本标签（例如 `v1.0.0`）并推送到 GitHub：
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
3. GitHub Actions 将自动唤醒 Windows 虚拟机：
   - 自动拉取代码并安装 Python 运行环境；
   - 自动安装 Inno Setup 编译器；
   - 自动运行 `build_release.py` 构建绿色版与安装包；
   - 自动在项目的 **GitHub Releases** 页面生成版本发布，并将安装包和压缩包上传供所有人高速下载！

---

## 🛠️ 技术难点与排坑要点

### 1. `ddddocr` 离线模型丢失问题
- **原因**：`ddddocr` 内部通过 `os.path.join(os.path.dirname(__file__), 'common.onnx')` 读取模型。PyInstaller 默认不会打包 `.onnx` 后缀文件。
- **解决方案**：在 `packaging/XMU_Gym_Booking.spec` 中动态检测 `ddddocr` 的安装路径，并显式将 `common.onnx`、`common_det.onnx` 和 `common_old.onnx` 复制到目标目录的 `ddddocr/` 中。

### 2. 快捷方式启动导致配置文件找不到
- **原因**：用户如果将可执行文件创建快捷方式放置在桌面上双击，Windows 的默认工作路径会变成桌面或系统目录，导致程序寻找 `./config/config.yaml` 失败。
- **解决方案**：在 `packaging/launcher.py` 头部通过 `sys.frozen` 判定，强制 `os.chdir(os.path.dirname(sys.executable))` 将工作路径重定向至程序所在真实目录。

### 3. 双击闪退问题
- **原因**：原生的 `main.py` 要求必须输入 action 参数（如 `python main.py web`），直接双击 exe 时由于参数为空会报错闪退。
- **解决方案**：`packaging/launcher.py` 会自动检测参数数量：若无参数，展示交互式终端导航菜单，并且默认启动 Web 控制台并自动唤醒系统默认浏览器打开 `http://localhost:8080`。

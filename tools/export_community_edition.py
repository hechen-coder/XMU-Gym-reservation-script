#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
开源社区版自动化导出引擎 (Community Edition Exporter)
用于将当前商业核心工程安全导出为符合“开放核心模式 (Open-Core)”的社区开源版。
"""

import os
import sys
import shutil
import argparse

# 解决 Windows 控制台编码问题
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL_DIR = os.path.join(PROJECT_ROOT, "tools", "community_templates")


def build_community_readme():
    """生成开源社区版专属 README.md，增加版本对比表与引流链接"""
    src_readme_path = os.path.join(PROJECT_ROOT, "README.md")
    with open(src_readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 在功能亮点后注入功能对比表
    comparison_table = """
---

## ⚖️ 开源社区版 vs 桌面专业版 功能对比

本项目采用 **Open-Core (开放核心)** 模式进行维护。我们开源完整的网络通信底层、系统架构设计与逆向协议白皮书以供学术探讨；同时将全自动化的秒杀抢票、降级算法与图形化客户端封装为专业版提供给需要省心使用的同学：

| 核心特性 | 源码开源版 (Community) | 桌面专业版 (Release 编译包) |
| :--- | :---: | :---: |
| **基础场馆余票查询 (Terminal Query)** | ✅ 完全开放 (终端整洁输出) | ✅ 现代化图形进度看板 |
| **全套系统架构白皮书与逆向协议分析** | ✅ 完全开放 (学术交流探讨) | ✅ 包含 |
| **无需配置 Python / 开箱即用** | ❌ 需自配 Python 环境 | ⚡ **独立 EXE，双击直接运行** |
| **📱 纯代码企业微信扫码直达登录** | ❌ 需抓包手动配 YAML | ⚡ **手机扫码 3 秒直达** |
| **⏰ 早 7 点准点毫秒并发秒杀** | ❌ 专业版独占 | ⚡ **自动提前自愈 + 准点毫秒秒抢** |
| **🎯 首选满额就近时段自适应降级** | ❌ 专业版独占 | ⚡ **动态计算最近场次，绝不空手** |
| **🔄 热门时段退票捡漏自动回捞** | ❌ 专业版独占 | ⚡ **持续挂机监听，出票毫秒拦截** |
| **📲 微信 PushPlus / 邮件结果推送** | ❌ 需自行编写通道扩展 | ⚡ **即时弹窗卡片推送** |
| **🛡️ 商业级客户端安全授权守护** | — | 🔒 **专属机器码 HWID 授权** |

👉 **立即前往 Releases 下载开箱即用的专业版桌面客户端**：  
[https://github.com/hechen-coder/XMU-Gym-reservation-script/releases](https://github.com/hechen-coder/XMU-Gym-reservation-script/releases)

---
"""

    target_pos = content.find("## 🚀 两种启动方式")
    if target_pos != -1:
        new_content = content[:target_pos] + comparison_table + "\n" + content[target_pos:]
    else:
        new_content = content + "\n" + comparison_table

    return new_content


def export_community(target_dir: str):
    """核心导出执行函数"""
    print("=" * 72)
    print("      厦大体育馆预约项目 - 开源社区版自动化导出引擎")
    print("=" * 72)
    print(f"[*] 目标导出路径: {target_dir}")

    if os.path.exists(target_dir):
        print(f"[*] 清理历史导出目录: {target_dir}")
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    # 1. 复制顶级文件
    for fname in ["LICENSE", "requirements.txt", "query_gym.py"]:
        src = os.path.join(PROJECT_ROOT, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(target_dir, fname))
            print(f"[+] 拷贝文件: {fname}")

    # 生成并写入专有社区版 README.md
    community_readme = build_community_readme()
    with open(os.path.join(target_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(community_readme)
    print("[+] 生成社区版专有 README.md (已注入功能对比表)")

    # 拷贝社区版 main.py 模板
    shutil.copy2(os.path.join(TPL_DIR, "main.py"), os.path.join(target_dir, "main.py"))
    print("[+] 注入社区版 main.py (含 query 开放与 pro 功能引导桩)")

    # 2. 复制 docs/ 完整技术文档体系
    src_docs = os.path.join(PROJECT_ROOT, "docs")
    dst_docs = os.path.join(target_dir, "docs")
    if os.path.exists(src_docs):
        shutil.copytree(src_docs, dst_docs)
        print("[+] 拷贝完整技术文档体系 docs/")

    # 3. 复制 config/ 示例文件
    dst_config = os.path.join(target_dir, "config")
    os.makedirs(dst_config, exist_ok=True)
    for ex in ["config.example.yaml", "config.advanced.example.yaml"]:
        src_ex = os.path.join(PROJECT_ROOT, "config", ex)
        if os.path.exists(src_ex):
            shutil.copy2(src_ex, os.path.join(dst_config, ex))
            print(f"[+] 拷贝配置示例: config/{ex}")

    # 4. 复制 images/ (排除大型视频)
    src_imgs = os.path.join(PROJECT_ROOT, "images")
    dst_imgs = os.path.join(target_dir, "images")
    if os.path.exists(src_imgs):
        shutil.copytree(src_imgs, dst_imgs, ignore=shutil.ignore_patterns("*.mp4"))
        print("[+] 拷贝图片素材 images/ (排除大型视频)")

    # 5. 组装 xdty_booking 核心包
    dst_pkg = os.path.join(target_dir, "xdty_booking")
    os.makedirs(dst_pkg, exist_ok=True)

    for f in ["__init__.py", "config.py"]:
        shutil.copy2(os.path.join(PROJECT_ROOT, "xdty_booking", f), os.path.join(dst_pkg, f))

    for sub in ["api", "utils", "solver"]:
        src_sub = os.path.join(PROJECT_ROOT, "xdty_booking", sub)
        dst_sub = os.path.join(dst_pkg, sub)
        if os.path.exists(src_sub):
            shutil.copytree(src_sub, dst_sub, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            print(f"[+] 拷贝开放模块: xdty_booking/{sub}/")

    # core 模块：保留 models.py，但注入 scheduler.py 与 booking_engine.py 引导桩
    dst_core = os.path.join(dst_pkg, "core")
    os.makedirs(dst_core, exist_ok=True)
    shutil.copy2(os.path.join(PROJECT_ROOT, "xdty_booking", "core", "__init__.py"), os.path.join(dst_core, "__init__.py"))
    shutil.copy2(os.path.join(PROJECT_ROOT, "xdty_booking", "core", "models.py"), os.path.join(dst_core, "models.py"))
    shutil.copy2(os.path.join(TPL_DIR, "scheduler.py"), os.path.join(dst_core, "scheduler.py"))
    shutil.copy2(os.path.join(TPL_DIR, "booking_engine.py"), os.path.join(dst_core, "booking_engine.py"))
    print("[+] 保护性组装 xdty_booking/core/ (models.py 开放，秒杀与降级算法已替换为引导桩)")

    # cas_qr_login 模块：保留指引文档与空桩
    dst_cas = os.path.join(target_dir, "cas_qr_login")
    os.makedirs(dst_cas, exist_ok=True)
    shutil.copy2(os.path.join(TPL_DIR, "cas_README.md"), os.path.join(dst_cas, "README.md"))
    with open(os.path.join(dst_cas, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("# Community stub\n")
    print("[+] 保护性组装 cas_qr_login/ (核心票据实现已剥离，保留技术指引)")

    # 6. 生成社区版 .gitignore
    community_gitignore = """# Python 缓存
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/

# 本地配置与数据
config/config.yaml
data/
logs/
*.log
captchas/
request/
images/*.mp4
"""
    with open(os.path.join(target_dir, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(community_gitignore.strip() + "\n")
    print("[+] 生成社区版 .gitignore")

    print("\n" + "=" * 72)
    print("  [SUCCESS] 开源社区版已完整导出至:")
    print(f"  {os.path.abspath(target_dir)}")
    print("=" * 72)
    print("  【资产安全审计报告】：")
    print("    - 核心商业抢票算法 (scheduler / fallback)   : [PRO] 已彻底剥离并注入引流桩")
    print("    - 企业微信 CAS 扫码底层实现                  : [PRO] 已彻底剥离")
    print("    - 机器码与授权安全验证模块 (security/)      : [SAFE] 未包含任何代码")
    print("    - 开发者私钥与发卡器 (keygen.py)             : [SAFE] 绝对未包含")
    print("    - 基础余票查询 (query) 与网络数据模型       : [OK] 完好可用")
    print("    - 全套技术文档与白皮书                       : [OK] 完整开放")
    print("    - 专业版 Releases 引流对比表                : [OK] 已自动注入 README")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导出开源社区版")
    parser.add_argument("--output", "-o", default=os.path.join(PROJECT_ROOT, "dist", "community_edition"),
                        help="输出目标目录，默认为 dist/community_edition")
    args = parser.parse_args()
    export_community(args.output)

# Windows 环境初始化与运行

本文用于在一台新的 64 位 Windows 电脑上，从 Git 拉取 E-HRM 项目、创建
Conda 环境并启动桌面软件。文末同时提供 Windows EXE 打包入口。

## 1. 环境要求

- Windows 10 或 Windows 11 64 位；
- Git for Windows；
- Miniconda 或 Anaconda；
- 可访问 GitHub、Conda 和 Playwright 浏览器下载地址；
- 至少预留 4 GB 磁盘空间。

源码运行不需要单独安装 Node.js、Chrome 或 Chromium。

## 2. 安装和初始化基础工具

打开 PowerShell，检查 Git：

```powershell
git --version
```

检查 Conda：

```powershell
conda --version
```

如果刚安装 Miniconda，执行：

```powershell
conda init powershell
```

关闭 PowerShell，再重新打开。如果 PowerShell 仍不能识别 Conda，可以先在
“Anaconda Prompt”中完成环境创建。

## 3. 拉取项目

下面以 `D:\workspace\NJNCC` 为例：

```powershell
New-Item -ItemType Directory -Force D:\workspace\NJNCC
Set-Location D:\workspace\NJNCC
git clone https://github.com/xiaoxia888/E-HRM.git
Set-Location E-HRM
git switch main
git pull --ff-only origin main
```

确认当前代码状态：

```powershell
git status
git log -1 --oneline
```

## 4. 创建 Conda 环境

开发和源码运行推荐直接使用组合环境文件：

```powershell
conda env create -f environment.yml
conda activate ehrm
```

如果 `ehrm` 环境已经存在：

```powershell
conda env update -n ehrm -f environment.yml
conda activate ehrm
```

检查环境：

```powershell
python --version
python -c "import PySide6, playwright, openpyxl; print('环境检查通过')"
```

Python 应为 `3.11.x`。

## 5. 安装 Playwright Chromium

```powershell
python -m playwright install chromium
```

检查安装结果：

```powershell
python -m playwright install --list
```

项目只使用 Chromium。

## 6. 运行测试

```powershell
python -m pytest -q
```

首次初始化和每次更新依赖后都建议执行测试。

## 7. 启动桌面软件

```powershell
conda activate ehrm
Set-Location D:\workspace\NJNCC\E-HRM
python scripts\run_gui.py
```

也可以运行：

```powershell
ehrm-gui
```

## 8. 首次使用

### ERP 设置

1. 打开“系统设置”；
2. 进入“账户与连接”；
3. 输入 ERP 用户名和密码；
4. 点击“保存账号”；
5. 点击“测试连接”。

ERP 账号密码保存在应用目录的 `runtime/data/auth.sqlite3`，不会写入配置文件。

### NocoBase 设置

1. 打开“系统设置 → 账户与连接 → NocoBase”；
2. 输入 NocoBase 登录账号和密码；
3. 点击“保存账号”；
4. 点击“测试连接”，确认登录与 Token 状态正常。

测试成功后 JWT、过期时间和账号信息统一保存在
`runtime/data/auth.sqlite3`。点击“清除 NocoBase 登录状态”只会删除 Token，
不会删除账号密码。

### 权益单获取

1. 进入“权益单获取”；
2. 下载并填写 Excel 模板；
3. 导入 Excel；
4. 选择导出方式和保存目录；
5. 点击“获取权益单”；
6. 程序按系统配置完成智慧人社登录和安全验证；
7. 登录完成后自动查询、下载，并按设置决定是否上传 ERP。

NocoBase 中提交的权益申请可在“权益申请”页面分页查询、查看详情并打印。

## 9. 运行数据位置

运行数据统一位于 `E-HRM.exe` 同级的 `runtime` 目录：

```text
E-HRM\
├── E-HRM.exe
└── runtime\
    ├── logs\
    ├── data\
    ├── diagnostics\
    └── output\
```

子目录按实际功能启用时创建，其中包括日志、用户偏好、浏览器资料、失败截图和
验证码诊断图片。源码运行时使用项目根目录下相同结构的 `runtime`。
ERP、智慧人社和 NocoBase 的账号、密码、Token 或浏览器认证状态保存在
`runtime/data/auth.sqlite3`，请限制该文件的访问权限并做好备份。

默认下载目录为：

```text
%USERPROFILE%\Downloads
```

## 10. 更新项目

```powershell
Set-Location D:\workspace\NJNCC\E-HRM
git status
git pull --ff-only origin main
conda env update -n ehrm -f environment.yml
conda activate ehrm
python -m playwright install chromium
python -m pytest -q
python scripts\run_gui.py
```

如果工作区存在本地修改，请先检查 `git status`，不要直接覆盖。

## 11. 构建 Windows EXE

只有需要制作安装包的 Windows 构建机才需要执行本节。

先安装构建依赖：

```powershell
conda env update -n ehrm -f environment.yml
conda env update -n ehrm -f environment.windows-build.yml
conda activate ehrm
```

如需生成最终安装程序，另外安装 Inno Setup 6。然后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\build_windows.ps1 `
    -Version 0.2.0
```

最终安装程序位于：

```text
dist\E-HRM-Setup-0.2.0\E-HRM-Setup-0.2.0.exe
```

完整打包说明见：

```text
packaging\windows\README.md
```

## 12. 常见问题

### PowerShell 禁止执行脚本

使用单次绕过方式，不需要永久修改系统策略：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\build_windows.ps1 `
    -Version 0.2.0
```

### Conda 环境无法激活

```powershell
conda init powershell
```

执行后关闭并重新打开 PowerShell。

### Playwright 提示浏览器不存在

```powershell
conda activate ehrm
python -m playwright install chromium
```

### 软件能够启动但 ERP 无法登录

进入“系统设置 → 账户与连接”，重新输入密码并测试连接。必要时先清除 ERP
登录状态，再保存账号并重新测试。

### 构建后被 SmartScreen 提示

未签名的内部测试程序可能触发 Windows SmartScreen。正式发布时应为主程序和
安装程序配置代码签名证书。

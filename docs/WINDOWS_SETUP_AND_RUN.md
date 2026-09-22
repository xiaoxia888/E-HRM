# Windows Web 服务器初始化、运行与打包

本文包含两个独立流程：Web 工作台部署，以及在 Windows 构建机生成 EXE 安装包。
所有命令默认在项目根目录执行。

## 第一部分：Web 工作台部署

### 1. 运行约束

- 支持 64 位 Windows 10/11；
- 使用普通 Windows 用户运行，不使用 `SYSTEM`；
- 同一套项目只能启动一个 Web 服务实例，不能使用多 worker；
- 当前系统仅适合可信内网，不应直接暴露到互联网；
- 不要把 `config\settings.toml`、`runtime\` 或真实账号密码提交到 Git。

### 2. 准备基础软件

安装 Git for Windows 和 Miniconda/Miniforge/Anaconda，然后打开 64 位 PowerShell：

```powershell
git --version
conda --version
[Environment]::Is64BitOperatingSystem
```

如果找不到 Conda，执行 `conda init powershell` 后重新打开 PowerShell。

### 3. 安装 SQL Server ODBC 驱动

安装 64 位 `Microsoft ODBC Driver 17 for SQL Server`。驱动名称必须与
`config\settings.toml` 一致。

### 4. 获取代码

```powershell
New-Item -ItemType Directory -Force D:\Applications
Set-Location D:\Applications
git clone https://github.com/xiaoxia888/E-HRM.git
Set-Location E-HRM
git switch main
git pull --ff-only origin main
```

### 5. 一键初始化服务器环境

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\setup_server_windows.ps1
```

脚本会创建或更新 `ehrm` Conda 环境，把 Chromium 安装到项目自己的
`runtime\playwright-browsers\`，构建 Web 页面，并检查 FastAPI、Playwright、
pyodbc、ODBC 驱动和 Chromium。脚本不会启动 Web 服务。

### 6. 配置系统

编辑 `config\settings.toml`，核对智慧人社、ERP、NocoBase、SQL Server、ODBC
驱动、Ollama 和模型配置。业务账号在 Web 页面“系统设置 → 账户与连接”中维护。

### 7. 启动 Web 服务

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_server_windows.ps1
```

默认监听 `0.0.0.0:8000`。修改地址或端口：

```powershell
$env:EHRM_HOST = "127.0.0.1"
$env:EHRM_PORT = "8080"
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_server_windows.ps1
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

### 8. 更新 Web 部署

停止服务并确认没有任务执行后：

```powershell
git status
git pull --ff-only origin main
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\setup_server_windows.ps1
```

完成后由管理员按原方式重新启动服务。

## 第二部分：构建 Windows EXE 安装包

本部分只在专用 Windows 构建机执行，不用于 Web 服务器部署。

### 9. 准备完整构建环境

安装 64 位 Windows、Git、Conda、Microsoft ODBC Driver 17 和 Inno Setup 6。

```powershell
conda env create -f environment.yml
conda env update -n ehrm -f environment.windows-build.yml
```

解析 `ehrm` 环境的真实目录，避免系统 Python 或其他环境被误用：

```powershell
$envs = (conda env list --json | ConvertFrom-Json).envs
$EhrmPrefix = $envs | Where-Object { (Split-Path $_ -Leaf) -eq "ehrm" } | Select-Object -First 1
$EhrmPython = Join-Path $EhrmPrefix "python.exe"
& $EhrmPython -c "import PySide6, playwright, pyodbc; print('构建环境检查通过'); print(pyodbc.drivers())"
```

输出必须包含 `ODBC Driver 17 for SQL Server`。

### 10. 检查构建环境

```powershell
& $EhrmPython scripts\check_windows_build_environment.py
```

需要同时检查数据库连接时：

```powershell
& $EhrmPython scripts\check_windows_build_environment.py --check-database
```

### 11. 生成安装包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\build_windows.ps1 `
  -Version 0.2.0
```

构建脚本会安装 Chromium、执行测试、运行 PyInstaller、检查打包内容并调用 Inno
Setup。最终安装程序位于：

```text
dist\E-HRM-Setup-0.2.0\E-HRM-Setup-0.2.0.exe
```

详细打包结构见 `packaging\windows\README.md`。

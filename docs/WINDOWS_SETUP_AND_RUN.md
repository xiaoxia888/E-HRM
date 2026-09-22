# Windows 环境初始化、迁移与运行

本文适用于 64 位 Windows 10/11，可按需要选择以下方式：

- **Web 工作台**：供本机或可信内网浏览器访问；
- **桌面客户端**：在当前 Windows 用户桌面运行；
- **安装包构建**：仅供发布人员生成 EXE 安装包。

所有源码命令默认在项目根目录执行。

## 1. 运行边界

- Web 工作台只能启动 **1 个 E-HRM 实例、1 个 worker**；
- 当前 Web 工作台没有用户登录和权限隔离，不得直接暴露到互联网；
- 浏览器自动化依赖当前用户的浏览器资料和账号数据库，不要以
  `LocalSystem` 或 Windows 服务的 Session 0 身份运行；
- `runtime\` 包含账号、登录会话和业务文件，迁移、备份和权限设置均按敏感数据
  处理；
- 迁移或更新前先等待任务结束或安全停止任务。

## 2. 环境要求

- Windows 10/11 64 位；
- Git for Windows；
- Miniconda、Miniforge 或 Anaconda；
- 可访问 Git、Conda、npm 和 Playwright 下载源；
- Web 部署至少预留 4 GB，桌面/打包环境建议预留 6 GB；
- 能访问智慧人社、ERP、NocoBase、Ollama 和 ERP SQL Server 等业务地址。

打开 64 位 PowerShell 检查：

```powershell
git --version
conda --version
[Environment]::Is64BitOperatingSystem
```

如果刚安装 Conda：

```powershell
conda init powershell
```

执行后关闭并重新打开 PowerShell。仍无法识别时可使用 Anaconda Prompt。

## 3. 安装 SQL Server ODBC 驱动

需要从 ERP/NCC SQL Server 补齐人员、单位或部门时，目标电脑必须安装 64 位
`Microsoft ODBC Driver 17 for SQL Server`。驱动名称必须与
`config\settings.toml` 中的配置一致。

安装后可在 Conda 环境中检查：

```powershell
python -c "import pyodbc; print(pyodbc.drivers())"
```

输出应包含：

```text
ODBC Driver 17 for SQL Server
```

## 4. 部署代码

以下以 `D:\Applications\E-HRM` 为例：

```powershell
New-Item -ItemType Directory -Force D:\Applications
Set-Location D:\Applications
git clone https://github.com/xiaoxia888/E-HRM.git
Set-Location E-HRM
git switch main
git pull --ff-only origin main
git status
git log -1 --oneline
```

不要把 `runtime\`、数据库、浏览器资料或真实账号密码提交到 Git。

## 5. Web 工作台环境

`environment.server.yml` 包含 Python 后端、Playwright 和构建 Web 页面所需的
Node.js，不安装 PySide6 桌面组件和 Windows 打包工具。

```powershell
conda env create -f environment.server.yml
conda activate ehrm
python --version
node --version
python -c "import fastapi, playwright, pyodbc; print('服务器环境检查通过')"
```

已有环境时：

```powershell
conda env update -n ehrm -f environment.server.yml --prune
conda activate ehrm
```

安装浏览器并构建页面：

```powershell
python -m playwright install chromium
Set-Location frontend
npm ci
npm run build
Set-Location ..
```

构建产物写入 `src\ehrm\web\static`。项目要求 Node.js `20.19+`、`22.12+`
或 `24+`；服务器环境默认安装 Node.js 22。

## 6. 配置与账号

系统配置入口为 `config\settings.toml`。部署到新电脑后核对：

- 智慧人社、ERP 和 NocoBase 地址；
- ERP SQL Server 地址、端口、库名与 ODBC 驱动；
- Ollama 地址和模型；
- 浏览器是否使用 `headless = true`。

智慧人社、ERP 和 NocoBase 的业务账号应在“系统设置 → 账户与连接”中保存，数据
写入 `runtime\data\auth.sqlite3`。不要把真实密码写入部署文档或提交到 Git。

## 7. 迁移旧电脑数据

### 7.1 旧电脑备份

确认任务已结束并停止 E-HRM 后，在旧项目根目录执行：

```powershell
Compress-Archive -Path .\runtime -DestinationPath "$env:USERPROFILE\Desktop\ehrm-runtime-backup.zip"
```

SQLite 可能同时使用 `-wal`、`-shm` 文件，不能在程序运行时只复制
`auth.sqlite3`。备份文件包含敏感数据，应通过受控方式传输。

### 7.2 新电脑恢复

确认新电脑尚未运行 E-HRM，在新项目根目录执行：

```powershell
Expand-Archive -Path C:\安全路径\ehrm-runtime-backup.zip -DestinationPath .
```

主要数据包括：

- `runtime\data\auth.sqlite3*`：账号、密码和登录 Token；
- `runtime\data\preferences.json`：下载目录、默认账号等偏好；
- `runtime\web-browser-profiles\`：Web 账号浏览器资料；
- `runtime\data\*-browser-profile\`：桌面/命令行浏览器资料；
- `runtime\uploads\`、`runtime\output\`：上传源文件和结果文件；
- `runtime\tasks\`：任务结果记录；
- `runtime\logs\`：历史日志，可选择不迁移。

任务调度状态在内存中，迁移后不会续跑未完成任务。浏览器会话也可能因设备变化
失效，首次启动后应测试各账号连接并按需重新登录。

如果只迁移账号和偏好，至少在程序停止状态下复制整个 `runtime\data\`，不要只
复制 SQLite 主文件。

## 8. 首次运行和验证 Web 工作台

先只监听本机：

```powershell
Set-Location D:\Applications\E-HRM
conda run --no-capture-output -n ehrm ehrm-web --host 127.0.0.1 --port 8000
```

在另一个 PowerShell 中检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

浏览器访问 `http://127.0.0.1:8000`，依次检查页面加载、账号连接、模板下载、导入、
任务中心和 ERP 人员查询。确认本机正常后再结束前台进程，改为内网监听：

```powershell
conda run --no-capture-output -n ehrm ehrm-web --host 0.0.0.0 --port 8000
```

内网地址为 `http://<服务器内网IP>:8000`。Windows 防火墙只应对实际办公网段放行
TCP 8000，不要设置公网端口映射。

## 9. 使用任务计划程序自动运行

需要登录后自动启动时，使用“任务计划程序”，并设置：

1. 触发器选择“用户登录时”；
2. 选择部署 E-HRM 的普通用户；
3. 选择“仅当用户登录时运行”，不要以 `SYSTEM` 运行；
4. 操作的程序填写 Conda 可执行文件绝对路径，例如
   `C:\Users\ehrm\miniconda3\Scripts\conda.exe`；
5. 参数填写：

   ```text
   run --no-capture-output -n ehrm ehrm-web --host 0.0.0.0 --port 8000
   ```

6. “起始于”填写项目绝对路径，例如 `D:\Applications\E-HRM`；
7. 在任务属性中选择“如果任务已在运行，不启动新实例”。

任务启动后用健康检查接口验证。不要在计划任务运行时再手工启动第二个实例。

## 10. 桌面客户端源码运行

只使用桌面客户端或进行完整开发时，使用组合环境：

```powershell
conda env create -f environment.yml
conda activate ehrm
python -m playwright install chromium
python -c "import PySide6, playwright, openpyxl; print('桌面环境检查通过')"
ehrm-gui
```

已有 `ehrm` 服务器环境时，可增量安装桌面依赖和测试依赖：

```powershell
conda env update -n ehrm -f environment.frontend.yml
python -m pip install -r requirements\dev.lock.txt
```

首次使用时在“系统设置 → 账户与连接”中保存并测试智慧人社、ERP、NocoBase
账号。运行数据仍位于项目根目录的 `runtime\`。

## 11. 更新 Web 部署

先停止计划任务、确认没有运行中任务并备份 `runtime\`，再执行：

```powershell
Set-Location D:\Applications\E-HRM
git status
git pull --ff-only origin main
conda env update -n ehrm -f environment.server.yml --prune
conda run -n ehrm python -m playwright install chromium
conda run -n ehrm npm --prefix frontend ci
conda run -n ehrm npm --prefix frontend run build
conda run -n ehrm python -c "import ehrm.web.app; print('后端加载检查通过')"
```

检查通过后再启动计划任务并调用健康检查接口。工作区存在本地修改时先检查
`git status`，不要强制覆盖，也不要删除或回滚 `runtime\`。

## 12. 构建 Windows EXE

只有制作桌面安装包的 Windows 构建机才执行本节。先创建完整桌面环境，再安装
Windows 构建依赖：

```powershell
conda env create -f environment.yml
conda env update -n ehrm -f environment.windows-build.yml
conda activate ehrm
python -c "import pyodbc; print(pyodbc.drivers())"
```

输出必须包含 `ODBC Driver 17 for SQL Server`。需要同时验证网络、数据库账号和
连接参数时执行：

```powershell
python scripts\check_windows_build_environment.py --check-database
```

生成最终安装程序还需安装 Inno Setup 6，然后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\build_windows.ps1 `
  -Version 0.2.0
```

最终安装程序位于：

```text
dist\E-HRM-Setup-0.2.0\E-HRM-Setup-0.2.0.exe
```

完整说明见 `packaging\windows\README.md`。

## 13. 常见问题

### PowerShell 禁止执行脚本

构建时可使用上面的单次 `-ExecutionPolicy Bypass`，不需要永久降低系统策略。

### Conda 环境无法激活

```powershell
conda init powershell
```

执行后关闭并重新打开 PowerShell。

### Web 页面显示“前端尚未构建”

```powershell
conda activate ehrm
Set-Location frontend
npm ci
npm run build
```

### Playwright 提示浏览器不存在

```powershell
conda activate ehrm
python -m playwright install chromium
```

### ERP 人员信息补齐失败

确认当前进程和 ODBC 驱动均为 64 位、驱动列表包含配置中的准确名称，并检查 SQL
Server 1433 端口、VPN/路由及 `config\settings.toml` 中的连接参数。

### 计划任务启动后网页打不开

检查任务历史、`runtime\logs\ehrm.log`、Conda 路径和“起始于”目录。确认端口未被
其他进程占用，且任务属性为“仅当用户登录时运行”。

### 构建后被 SmartScreen 提示

未签名的内部测试程序可能触发 SmartScreen。正式发布时应为主程序和安装程序配置
代码签名证书。

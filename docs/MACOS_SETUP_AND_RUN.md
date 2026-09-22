# macOS 服务器迁移、初始化与运行

本文用于把 E-HRM 迁移到一台长期运行的 macOS 电脑，并以 Web 工作台方式供可信
内网访问。文末保留桌面客户端的安装方法。所有命令默认在项目根目录执行。

## 1. 部署边界

部署前先确认以下约束：

- Web 任务协调器位于服务进程内，只能启动 **1 个 E-HRM 实例、1 个 worker**；
- 不要同时用多个终端、LaunchAgent 或 `uvicorn --workers` 启动同一套服务；
- 当前 Web 工作台没有用户登录和权限隔离，只能放在受防火墙保护的可信内网，
  不能直接暴露到互联网；
- 使用独立的普通 macOS 用户运行，不使用 `root`；
- `runtime/` 含账号、登录会话、上传文件和业务结果，必须按敏感数据管理；
- 迁移时正在执行的任务不能续跑，应先等待任务结束或安全停止任务。

推荐目录：

```text
/Users/<运行用户>/Applications/E-HRM/
├── config/
├── frontend/
├── src/
└── runtime/
```

## 2. 服务器要求

- macOS 13 或更高版本，Intel 和 Apple Silicon 均可；
- 至少 4 GB 可用磁盘空间，业务文件较多时应单独预留 `runtime/` 空间；
- Git、Miniconda/Miniforge 或 Anaconda；
- 可访问 Git 仓库、Conda、npm 和 Playwright 下载源；
- 可访问智慧人社、ERP、NocoBase、Ollama 和 ERP SQL Server 等业务地址；
- 固定内网 IP 或稳定主机名，并校准系统时间。

Conda 的 macOS 安装方式见[官方说明](https://docs.conda.io/projects/conda/en/stable/user-guide/install/macos.html)。
建议选择与 `uname -m` 一致的安装包，不要在 Apple Silicon 上混用 ARM64 与
Rosetta x86_64 环境。

检查基础环境：

```bash
sw_vers
uname -m
git --version
conda --version
```

如果终端找不到 Conda：

```bash
conda init zsh
exec zsh
```

## 3. ERP 人员库 ODBC 驱动

只有需要从 ERP/NCC SQL Server 补齐人员、单位和部门时才需要本节。项目当前
`config/settings.toml` 默认使用 `ODBC Driver 17 for SQL Server`，驱动名称必须与
配置完全一致。

使用 Homebrew 安装驱动 17：

```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew trust microsoft/mssql-release
brew update
HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql17 mssql-tools
```

Homebrew 旧版本如果不支持 `brew trust`，可略过该命令。Apple Silicon 必须使用
17.8 或更高版本。完整说明见
[Microsoft macOS ODBC 安装文档](https://learn.microsoft.com/sql/connect/odbc/linux-mac/install-microsoft-odbc-driver-sql-server-macos)。

安装后检查：

```bash
odbcinst -q -d
```

输出应包含：

```text
[ODBC Driver 17 for SQL Server]
```

## 4. 部署代码

首次部署：

```bash
mkdir -p ~/Applications
cd ~/Applications
git clone https://github.com/xiaoxia888/E-HRM.git
cd E-HRM
git switch main
git pull --ff-only origin main
git status
git log -1 --oneline
```

不要把 `runtime/`、数据库、浏览器资料或真实账号密码提交到 Git。

## 5. 创建服务器环境

服务器使用 `environment.server.yml`。它包含 Python 后端、Playwright 和构建 Web
页面所需的 Node.js，不安装 PySide6 桌面组件和 Windows 打包工具。

```bash
conda env create -f environment.server.yml
conda activate ehrm
python --version
node --version
python -c "import fastapi, playwright, pyodbc; print('服务器环境检查通过')"
```

已有环境时更新并清理不再需要的包：

```bash
conda env update -n ehrm -f environment.server.yml --prune
conda activate ehrm
```

安装 Playwright Chromium：

```bash
python -m playwright install chromium
python -m playwright install --list
```

## 6. 构建 Web 页面

正式部署应使用锁定依赖进行构建：

```bash
cd frontend
npm ci
npm run build
cd ..
```

构建产物写入 `src/ehrm/web/static/`。即使仓库中已有静态文件，迁移或更新后仍建议
重新构建，确保页面与后端代码属于同一版本。项目要求 Node.js `20.19+`、
`22.12+` 或 `24+`；服务器环境默认安装 Node.js 22。

## 7. 配置检查

系统配置入口只有 `config/settings.toml`。迁移前逐项核对：

- `[rights_statement.site]`：智慧人社地址；
- `[nocobase.site]`：NocoBase 地址；
- `[erp.site]`：ERP 地址；
- `[erp.database]`：SQL Server 地址、端口、库名和 ODBC 驱动；
- `[ai]`：Ollama 地址、模型和提示词路径；
- 浏览器是否使用 `headless = true`。

外部地址、数据库账号等环境差异应在服务器本地配置，不要把真实密码提交到仓库。
智慧人社、ERP 和 NocoBase 的业务账号应在“系统设置 → 账户与连接”中保存，数据
写入 `runtime/data/auth.sqlite3`。

建议先检查网络连通性，不要用业务账号反复试错：

```bash
nc -vz <SQL_SERVER_HOST> 1433
curl -I <NOCOBASE_BASE_URL>
curl -I <OLLAMA_BASE_URL>
```

## 8. 迁移旧机器数据

### 8.1 停止旧实例并备份

先在旧机器确认没有运行中任务，再停止 E-HRM。数据库可能使用 SQLite WAL 文件，
所以不能在服务运行时只复制 `auth.sqlite3`。应整体备份 `runtime/`：

```bash
cd /旧机器/E-HRM
tar -czf ~/Desktop/ehrm-runtime-backup.tar.gz runtime
```

将压缩包通过受控方式传到新服务器。压缩包包含账号和业务数据，不要上传到公共
网盘或 Git。

### 8.2 恢复到新服务器

在新服务器项目根目录确认还没有运行 E-HRM，然后执行：

```bash
tar -xzf /安全路径/ehrm-runtime-backup.tar.gz -C .
chmod -R go-rwx runtime
```

迁移内容说明：

- `runtime/data/auth.sqlite3*`：账号、密码和登录 Token；
- `runtime/data/preferences.json`：下载目录、默认账号等偏好；
- `runtime/web-browser-profiles/`：Web 账号浏览器资料；
- `runtime/data/*-browser-profile/`：桌面/命令行浏览器资料；
- `runtime/uploads/`、`runtime/output/`：上传源文件和结果文件；
- `runtime/tasks/`：任务结果记录；
- `runtime/logs/`：历史日志，可选择不迁移。

任务调度状态保存在内存中，迁移后不会自动继续旧机器上未完成的任务。浏览器会话
也可能因设备变化或网站策略失效，首次启动后应逐个测试账号连接并按需重新登录。

如果只迁移账号和偏好，至少在服务停止状态下复制整个 `runtime/data/`，不要只复制
单个 SQLite 主文件。

## 9. 首次前台运行与验证

先只监听本机地址：

```bash
cd ~/Applications/E-HRM
conda run --no-capture-output -n ehrm \
  ehrm-web --host 127.0.0.1 --port 8000
```

在另一个终端检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

应返回 `status: ok`、`deployment: single-server`。然后用浏览器访问
`http://127.0.0.1:8000`，完成以下检查：

1. 页面和静态资源能正常加载；
2. 系统设置中的保存账号能显示并通过连接测试；
3. 下载模板、导入和任务中心正常；
4. ERP 人员查询能够访问 SQL Server；
5. `runtime/logs/ehrm.log` 没有持续报错。

本机验证完成后再结束前台进程，并改为可信内网监听：

```bash
conda run --no-capture-output -n ehrm \
  ehrm-web --host 0.0.0.0 --port 8000
```

内网访问地址为 `http://<服务器内网IP>:8000`。只在 macOS 防火墙和上级防火墙中
放行实际办公网段，不要做公网端口映射。

## 10. 使用 LaunchAgent 开机运行

仓库提供 `packaging/macos/com.njncc.ehrm-web.plist.example`。LaunchAgent 在指定
用户登录后运行，适合需要浏览器资料和用户目录的本项目；不要改成 root
LaunchDaemon。

复制模板：

```bash
mkdir -p ~/Library/LaunchAgents
cp packaging/macos/com.njncc.ehrm-web.plist.example \
  ~/Library/LaunchAgents/com.njncc.ehrm-web.plist
```

用文本编辑器替换模板中的三处占位符：

- `__PROJECT_ROOT__`：项目绝对路径，例如 `/Users/ehrm/Applications/E-HRM`；
- `__CONDA_EXE__`：Conda 可执行文件绝对路径，可用
  `$(conda info --base)/bin/conda` 定位；
- `__LOG_ROOT__`：日志目录绝对路径，例如项目下的 `runtime/logs`。

创建日志目录并检查 plist：

```bash
mkdir -p runtime/logs
plutil -lint ~/Library/LaunchAgents/com.njncc.ehrm-web.plist
```

加载和检查：

```bash
launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/com.njncc.ehrm-web.plist
launchctl print gui/$(id -u)/com.njncc.ehrm-web
curl http://127.0.0.1:8000/api/v1/health
```

停止或重新加载：

```bash
launchctl bootout gui/$(id -u)/com.njncc.ehrm-web
```

修改 plist 后先 `bootout`，再执行 `bootstrap`。不要在 LaunchAgent 运行期间手工再
启动第二个 Web 实例。

## 11. 更新与回滚

更新前先停止 LaunchAgent、确认无运行任务并备份 `runtime/`：

```bash
cd ~/Applications/E-HRM
git status
git pull --ff-only origin main
conda env update -n ehrm -f environment.server.yml --prune
conda run -n ehrm python -m playwright install chromium
conda run -n ehrm npm --prefix frontend ci
conda run -n ehrm npm --prefix frontend run build
conda run -n ehrm python -c "import ehrm.web.app; print('后端加载检查通过')"
```

检查通过后再重新加载 LaunchAgent，并调用健康检查接口。若 `git status` 显示本地
修改，先确认这些修改，不要使用 `git reset --hard` 或强制覆盖。回滚代码时也不要
回滚或删除 `runtime/`。

## 12. 桌面客户端（可选）

服务器只运行 Web 工作台时不需要 PySide6。需要在这台 Mac 上同时使用桌面客户端
时，再增量安装桌面依赖：

```bash
conda env update -n ehrm -f environment.frontend.yml
conda activate ehrm
ehrm-gui
```

开发机需要测试依赖时可直接使用组合环境 `environment.yml`。

## 13. 常见问题

### Web 页面显示“前端尚未构建”

```bash
conda activate ehrm
cd frontend
npm ci
npm run build
```

### WebSocket 404 或任务状态不刷新

```bash
conda activate ehrm
python -m pip install -e .
```

确认只启动了一个 `ehrm-web` 进程，并且代理没有拦截 `/api/v1/tasks/ws`。

### Playwright 找不到 Chromium

```bash
conda activate ehrm
python -m playwright install chromium
```

### ERP 人员查询失败

检查 `odbcinst -q -d`、SQL Server 1433 端口、VPN/路由以及
`config/settings.toml` 中的驱动名称。安装 Driver 18 但配置仍写 Driver 17 时也会
报“找不到驱动”。

### 重启后服务没有运行

检查：

```bash
plutil -lint ~/Library/LaunchAgents/com.njncc.ehrm-web.plist
launchctl print gui/$(id -u)/com.njncc.ehrm-web
tail -n 100 runtime/logs/ehrm-web.stderr.log
```

LaunchAgent 只有在部署用户登录后才会启动；需要无人值守登录时，应由服务器管理员
结合设备安全策略配置，而不是改用 root 运行本程序。

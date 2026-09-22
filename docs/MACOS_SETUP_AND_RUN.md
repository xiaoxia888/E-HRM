# macOS Web 服务器初始化与运行

本文只说明如何在一台新的 macOS 电脑上安装、配置、启动和更新 E-HRM Web
工作台。所有命令默认在项目根目录执行。

## 1. 运行约束

- 使用普通 macOS 用户运行，不使用 `root`；
- 同一套项目只能启动一个 Web 服务实例，不能使用多 worker；
- 当前系统仅适合可信内网，不应直接暴露到互联网；
- 不要把 `config/settings.toml`、`runtime/` 或真实账号密码提交到 Git；
- 浏览器自动化必须由运行 Web 服务的同一 macOS 用户执行。

## 2. 准备基础软件

目标电脑需要：

- macOS 13 或更高版本；
- Git；
- Miniconda、Miniforge 或 Anaconda；
- Homebrew；
- 至少 4 GB 可用空间；
- 能访问 Conda、npm、Playwright 下载源及业务系统。

检查：

```bash
sw_vers
uname -m
git --version
conda --version
brew --version
```

如果找不到 Conda：

```bash
conda init zsh
exec zsh
```

Apple Silicon 应安装 ARM64 版 Conda，不要混用 Rosetta x86_64 环境。

## 3. 获取代码

```bash
mkdir -p ~/Applications
cd ~/Applications
git clone https://github.com/xiaoxia888/E-HRM.git
cd E-HRM
git switch main
git pull --ff-only origin main
```

已有代码时直接进入项目根目录。

## 4. 安装 SQL Server ODBC 驱动

ERP 人员库使用 Microsoft SQL Server。项目默认驱动名称为
`ODBC Driver 17 for SQL Server`：

```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew update
HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql17 mssql-tools
odbcinst -q -d
```

输出必须包含：

```text
[ODBC Driver 17 for SQL Server]
```

如果使用 Driver 18，必须同步修改 `config/settings.toml` 中的驱动名称。

## 5. 一键初始化服务器环境

执行仓库提供的初始化脚本：

```bash
chmod +x scripts/setup_server_macos.sh scripts/run_server_macos.sh
./scripts/setup_server_macos.sh
```

脚本会依次完成：

1. 创建或更新 `ehrm` Conda 环境；
2. 安装后端依赖和 `pyodbc`；
3. 将 Playwright Chromium 安装到项目自己的
   `runtime/playwright-browsers/`；
4. 执行 `npm ci` 并构建 Web 页面；
5. 检查 FastAPI、Playwright、pyodbc、ODBC 驱动列表；
6. 临时启动并立即关闭无界面 Chromium，确认浏览器确实可用。

初始化脚本不会启动 Web 服务。

### 为什么不使用裸 `python`

目标电脑可能同时安装 pyenv、系统 Python 和 Conda。即使终端显示 `(ehrm)`，裸
`python` 或 `conda run ... python` 仍可能被 shell 配置干扰。初始化脚本会先读取
`ehrm` 环境的真实目录，再直接调用其中的绝对 Python 路径，因此不要自行替换成
`python ...` 或 `python -m playwright ...`。

## 6. 配置系统

编辑 `config/settings.toml`，至少核对：

- 智慧人社、ERP、NocoBase 地址；
- ERP SQL Server 地址、端口、数据库和 ODBC 驱动名称；
- Ollama 地址、模型和提示词配置；
- 服务器浏览器是否设置为无界面模式。

业务账号在 Web 页面“系统设置 → 账户与连接”中维护，不要写入部署文档。

## 7. 启动 Web 服务

由管理员手工启动：

```bash
./scripts/run_server_macos.sh
```

默认监听 `0.0.0.0:8000`。如需修改：

```bash
EHRM_HOST=127.0.0.1 EHRM_PORT=8080 ./scripts/run_server_macos.sh
```

另开终端检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

浏览器访问 `http://<服务器内网IP>:8000`。防火墙只允许实际办公网段访问。

## 8. 更新程序

先停止 Web 服务并确认没有任务执行，再运行：

```bash
git status
git pull --ff-only origin main
./scripts/setup_server_macos.sh
```

脚本会更新 Conda 依赖、Playwright 浏览器和 Web 构建产物。完成后由管理员按原方式
重新启动服务。

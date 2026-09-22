# Web 工作台开发与运行

Web 工作台使用 React、TypeScript、Ant Design 和 FastAPI，与桌面客户端共用业务
代码、系统配置和项目根目录下的 `runtime/` 数据。

服务器迁移和长期运行请优先阅读：

- [macOS 服务器迁移、初始化与运行](MACOS_SETUP_AND_RUN.md)
- [Windows 环境初始化、迁移与运行](WINDOWS_SETUP_AND_RUN.md)

## 1. 必须遵守的部署边界

- 同一智慧人社账号串行排队，不同账号使用独立浏览器资料；
- 普通数据库/API 查询可并行，不占用浏览器队列；
- ERP 写入或批量提交按账号和业务资源串行；
- 任务协调器位于 FastAPI 进程内，正式环境必须保持 **单实例、单 worker**；
- 不要启动多个 `ehrm-web`，也不要使用 `uvicorn --workers 2`；
- 当前 Web 工作台没有用户登录，只能部署在受防火墙保护的可信内网。

## 2. 创建环境

服务器或只运行 Web 工作台的电脑使用：

```bash
conda env create -f environment.server.yml
conda activate ehrm
python -m playwright install chromium
```

`environment.server.yml` 同时安装 Node.js 22，用于构建前端。已有环境时：

```bash
conda env update -n ehrm -f environment.server.yml --prune
```

完整桌面开发环境可改用 `environment.yml`。

## 3. 构建前端

```bash
cd frontend
npm ci
npm run build
cd ..
```

构建产物写入 `src/ehrm/web/static/`，由 FastAPI 直接提供。项目要求 Node.js
`20.19+`、`22.12+` 或 `24+`。

## 4. 正式运行

仅本机访问：

```bash
conda run --no-capture-output -n ehrm \
  ehrm-web --host 127.0.0.1 --port 8000
```

可信内网访问：

```bash
conda run --no-capture-output -n ehrm \
  ehrm-web --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

浏览器访问 `http://服务器地址:8000`。不要把端口映射到公网。

## 5. 前后端联调

终端一启动后端：

```bash
conda activate ehrm
ehrm-web --host 127.0.0.1 --port 8000 --reload
```

终端二启动 Vite：

```bash
conda activate ehrm
cd frontend
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。Vite 会代理 `/api` 和任务 WebSocket 到
FastAPI。`--reload` 和 Vite 开发服务器只能用于本地开发。

## 6. 数据目录

源码运行时数据统一位于项目根目录的 `runtime/`：

```text
runtime/
├── data/                  # 账号数据库、偏好和桌面浏览器资料
├── web-browser-profiles/  # Web 账号独立浏览器资料
├── uploads/               # 导入和解析源文件
├── output/                # 业务结果
├── tasks/                 # 已落盘的任务结果
└── logs/                  # 运行日志
```

`runtime/data/auth.sqlite3*`、浏览器资料、上传文件和输出文件均可能包含敏感信息，
不得提交到 Git。迁移时应先停止服务，再整体备份 `runtime/`；内存中的运行任务不会
在另一台机器上续跑。

## 7. 常见问题

### 首页返回 503“Web 前端尚未构建”

重新执行 `npm ci` 和 `npm run build`，确认
`src/ehrm/web/static/index.html` 存在。

### `/api/v1/tasks/ws` 返回 404

确认环境已安装当前项目：

```bash
conda activate ehrm
python -m pip install -e .
```

### 任务重复执行或账号队列异常

检查是否同时运行了多个进程、多个计划任务，或者使用了多个 Uvicorn worker。每套
`runtime/` 只能由一个 E-HRM Web 服务实例管理。

### 服务正常但内网无法访问

确认监听地址为 `0.0.0.0`，端口没有被占用，并只在防火墙中对可信办公网段放行。

# Web 端开发与运行

Web 端采用 React、TypeScript、Ant Design 和 FastAPI。桌面 GUI 保留不变，Web 与 GUI 共用 `src/ehrm/modules` 下的业务代码和 `runtime` 数据。

## 并发边界

- 同一智慧人社账号：串行排队，页面显示前方任务数及排队原因。
- 不同智慧人社账号：后续业务接入时使用独立浏览器目录并行执行。
- 普通数据库/API 查询：直接并行，不占用浏览器队列。
- ERP 写入或批量提交：按 ERP 账号和单位资源串行。

当前协调器部署在 FastAPI 进程内，因此服务必须保持单实例、单 worker。不要使用 `uvicorn --workers 2` 或启动多个服务进程，否则账号锁将被拆分。

## 安装

安装 Python 后端依赖：

```bash
python -m pip install -e .
```

安装内容包含任务实时推送所需的 `websockets`。如果后端日志出现
`GET /api/v1/tasks/ws 404`，说明旧环境没有安装该依赖，请重新执行上述安装命令。

安装并构建前端：

```bash
cd frontend
npm ci
npm run build
cd ..
```

构建产物会写入 `src/ehrm/web/static`，由 FastAPI 直接提供。

## 正式运行

仅本机访问：

```bash
ehrm-web --host 127.0.0.1 --port 8000
```

可信内网访问：

```bash
ehrm-web --host 0.0.0.0 --port 8000
```

然后访问 `http://服务器地址:8000`。当前阶段尚未接入 Web 用户登录，绑定 `0.0.0.0` 时只能部署在受防火墙保护的可信内网，不能直接暴露到互联网。

## 前后端联调

终端一启动后端：

```bash
ehrm-web --host 127.0.0.1 --port 8000 --reload
```

终端二启动 Vite：

```bash
cd frontend
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。Vite 会代理 `/api` 和任务 WebSocket 到 FastAPI。

## 已接入页面

- 工作台：任务统计和并发策略。
- 权益单获取：Excel 导入、校验预览、分组打印、后台任务、安全停止与结果下载。
- 权益申请：NocoBase 列表、详情查询，可按申请人打印组直接发起权益单任务。
- 社保业务：退保、基础信息采集和参保入口框架。
- 任务中心：实时状态、排队说明、进度、错误详情和停止操作。
- 系统设置：维护三类外部系统账号、下载与任务、自动化节奏和模型参数，与桌面端共用数据。

退保、基础信息采集和参保的 Web 表单以及 Web 用户登录与权限控制将在后续阶段接入。在确认提交功能启用前，相关自动化仍保持“只录入、不提交”的安全边界。

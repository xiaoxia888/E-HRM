# Web 工作台开发说明

本文只面向本地开发和前后端联调。正式服务器安装与运行请使用：

- [macOS Web 服务器初始化与运行](MACOS_SETUP_AND_RUN.md)
- [Windows Web 服务器初始化、运行与打包](WINDOWS_SETUP_AND_RUN.md)

正式部署不要照抄本页的开发命令，也不要启动多个服务实例。

## 1. 开发环境

开发机使用包含后端、桌面组件和测试依赖的组合环境：

```bash
conda env create -f environment.yml
```

如果环境已存在：

```bash
conda env update -n ehrm -f environment.yml --prune
```

为避免 pyenv 或系统 Python 抢占命令，先解析环境绝对路径：

```bash
EHRM_PREFIX="$(conda env list | awk '$1 == "ehrm" {print $NF; exit}')"
export PATH="$EHRM_PREFIX/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/runtime/playwright-browsers"
"$EHRM_PREFIX/bin/python" -m playwright install chromium
```

## 2. 构建 Web 页面

```bash
"$EHRM_PREFIX/bin/npm" --prefix frontend ci
"$EHRM_PREFIX/bin/npm" --prefix frontend run build
```

构建产物位于 `src/ehrm/web/static/`。

## 3. 前后端联调

终端一：

```bash
export PATH="$EHRM_PREFIX/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/runtime/playwright-browsers"
"$EHRM_PREFIX/bin/ehrm-web" --host 127.0.0.1 --port 8000 --reload
```

终端二：

```bash
export PATH="$EHRM_PREFIX/bin:$PATH"
"$EHRM_PREFIX/bin/npm" --prefix frontend run dev
```

浏览器访问 `http://127.0.0.1:5173`。Vite 会代理 `/api` 和任务 WebSocket。
`--reload` 和 Vite 开发服务器仅用于开发。

## 4. 开发检查

```bash
"$EHRM_PREFIX/bin/python" -m pytest -q
"$EHRM_PREFIX/bin/npm" --prefix frontend test
"$EHRM_PREFIX/bin/npm" --prefix frontend run build
```

## 5. 运行边界

- 正式环境只能运行一个 E-HRM Web 实例和一个 worker；
- 当前 Web 工作台只能部署在可信内网；
- `runtime/` 包含账号、浏览器资料和业务文件，不得提交到 Git；
- Playwright 安装和 Web 服务启动必须使用同一个 Python 环境及同一个
  `PLAYWRIGHT_BROWSERS_PATH`。

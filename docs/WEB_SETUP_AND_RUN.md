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

### 权益申请办理

权益申请列表包括单位社保权益单、退工停保登记、用工参保登记。打开申请详情后，先选择智慧人社账号，点击对应操作，核对确认弹窗中的单位账号和登录方式再执行。打印权益单同样需要确认账号。

退保按钮会调用现有真实提交流程，包含真实性声明确认；退工日期使用业务页面默认值。执行期间在进度弹窗查看日志和逐人结果，可停止后续处理。关闭弹窗不代表停止任务，重新打开详情可查看进度或执行结果。

基础信息采集、参保登记本次只保留入口，确认后提示功能预留，不执行自动化，也不标记已办理。两种操作的状态相互独立。

办理状态和日志保存在 `runtime/data/application_operations.sqlite3`，不会修改 NocoBase 的 `status`。状态按申请、人员身份证和操作区分，不因更换登录账号而重置。已成功和结果待确认的人员禁止重复提交；部分成功后再次执行仅处理其他人员。服务器重启后，提交中的人员标记为待确认，未进入提交步骤的人员可以重新发起。待确认项必须先人工核对，不能通过反复点击来重试。此数据库无到期清理，应和任务、账号数据库一起备份。

### 部署约束

- 正式环境只能运行一个 E-HRM Web 实例和一个 worker；
- 当前 Web 工作台只能部署在可信内网；
- `runtime/` 包含账号、浏览器资料和业务文件，不得提交到 Git；
- Playwright 安装和 Web 服务启动必须使用同一个 Python 环境及同一个
  `PLAYWRIGHT_BROWSERS_PATH`。

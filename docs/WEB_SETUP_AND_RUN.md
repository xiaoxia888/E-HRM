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

### 工作台业务使用统计

工作台使用一块紧凑统计区域，横向分别展示权益单、社保业务、医保业务的累计、今日、所选期间次数及独立每日趋势图。三类共用最近 7/30/90 天及自选日期筛选（单次最多 366 天），每 30 秒自动更新，也可手动刷新。每日明细在弹窗中按日期同时列出三类次数。

每个确认创建的业务任务计 1 次，包括成功、失败、排队、取消和中断；任务状态更新不增加次数。权益单仅统计 `rights_statement.acquire`，社保业务统计已接入的 `application.termination:*` 退工停保，医保业务分别汇总 `application.medical_termination:*` 停保和 `application.medical_enrollment:*` 参保。权益单不重复计入社保业务，ERP 申请解析、ERP 上传及其他业务任务不计入这三类。尚未接入 Web 任务记录的社保采集、参保及桌面操作不会凭空补计。

按任务创建时间归属北京时间（`Asia/Shanghai`）的自然日，没有任务的日期补 0。累计基于 `runtime/data/tasks.sqlite3` 的全部保留任务，不受任务列表最近 500 条的限制；系统未保存任务记录的更早操作无法补计，每类累计数的提示显示首条记录日期。

接口为 `GET /api/v1/dashboard/business-usage`，可传 `days=30`，或同时传 `start_date` / `end_date`（`YYYY-MM-DD`）。日期筛选只影响期间合计、每日图表和明细，累计及今日次数保持各自口径。原 `GET /api/v1/dashboard/rights-usage` 仍返回权益单统计。统计查询不读取人员信息，也不调用智慧人社或 ERP。

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

# ERP 申请同步到 NocoBase

## 同步规则

E-HRM 定时获取 ERP 的“社保咨询”和“单位社保权益单”，同步到 `NCC_HumProblem`。只同步原始申请，不调用模型，不创建人员；独立解析接口不受影响。

| ERP 字段 | NocoBase 字段 |
| --- | --- |
| 原始记录 ID | `key_value` |
| ERP 申请编号 | `erp_code` |
| NocoBase 自动编号 | `code`（由 NocoBase 生成，同步不写入） |
| 标题 | `title` |
| 问题描述文本 | `problem_desc` |
| 申请日期 | `initiation_date` |
| 部门 | `dept_name` |
| 原始响应及规范化来源字段 | `erp_all_field_value` |

事务类型按原值映射：社保咨询 → `social_security_consult`；单位社保权益单 → `social_security_rights`。同步阶段不会自动改为参保或停保。

按 `key_value` 跨类型、跨日期查重。不存在时新增，NocoBase 自动生成 `id` 和 `code`；存在时比较来源的标题、描述和申请日期，来源改变或 `erp_code` 缺失/不符时更新。优先比较已保存的 ERP 快照，不因人工编辑而每次重复覆盖。旧记录会在下次同步命中该 ERP ID 时补齐 `erp_code`，不会因 NocoBase 自动编号不同而重新新增。同一 ERP ID 存在多条记录时报告错误，不随机选择、不删除。

新增发起人按用户 `nickname` 精确匹配。找不到或重名时 `initiator_id` 留空并提示；更新保留已有发起人。新增初始预计/实际耗时为 0，状态使用 NocoBase 默认值。更新不发送状态、处理方式、耗时与完成日期、人员、附件及系统审计字段。

## 使用

1. 自行启动 E-HRM。本功能和测试脚本不另外启动服务。
2. 在“系统设置 → 账户与连接”保存 ERP 账号和 NocoBase API 密钥。
3. 密钥需能查询全部待同步申请、查询用户，以及新增、更新申请。行级权限若隐藏已有记录可能导致重复新增，请确保查询权限覆盖完整同步范围。
4. 进入左侧独立菜单“定时任务”。默认已有一个 ERP 同步计划，自动执行关闭。
5. 点击“执行一次”，选日期后先点“只读预览”，在执行详情中查看步骤日志和逐条计划。
6. 确认后点击“开始同步”。不选日期时使用已保存的回查天数。
7. 点击“编辑”，设置 cron、回查天数和启用状态，并保存。可先预览后五次触发时间。

计划、执行记录和步骤日志持久化在 `runtime/data/scheduled_tasks.sqlite3`；执行本身继续复用现有任务中心和 ERP 账号队列。配置文件 `[nocobase.sync]` 只提供首次默认值，之后以工作台保存的数据库值为准。默认回查 2 天（含今天）。

调度引擎采用 APScheduler 3.x，业务执行仍由本平台的账号队列负责。服务关闭时不执行定时任务；重启后错过的 cron 触发合并为一次，不积累次数。上次未结束的执行记录标记“已中断”，不自动重跑该次写入。新的计划触发按正常查重规则处理。

定时、手动和预览重叠时，新增一条“已跳过”的触发记录，关联正在排队或执行的任务，不重复排队。同类同步计划间也不并行写入。手动执行不改变下一次计划时间。文件锁防止不同进程同时执行同步；调度器启动也加单实例锁，整个平台仍要求单实例、单 worker 部署。

关闭计划不取消已创建任务，当前任务可在任务中心停止。逐条写入，不回滚已经成功的记录；再次执行重新查重。不会定时删除数据或清理任务历史。

工作台下方提供执行记录服务端分页、按任务筛选；“查看日志”可查看排队、获取 ERP、逐条同步、完成或错误。步骤日志同样分页，不只保存最后一条进度。结果区分成功、部分失败、失败、已停止、已中断和已跳过。计划只允许选择已注册的业务类型，不支持任意脚本或 shell 命令。

## Cron 规则

使用五段 Unix cron：`分 时 日 月 星期`，时区固定 `Asia/Shanghai`。不支持 Quartz 六/七段、`?`、`L`、`W`、`#` 或 `@daily`。支持 `*`、范围、列表和步长；星期 0/7 表示周日，也可写 `mon`–`sun`。日与星期同时明确限定（均不以 `*` 开头）时，任一匹配即触发；有一项以 `*` 开头时两项都须匹配。程序将 Unix 星期编号转换为 APScheduler 名称，避免引擎数字星期含义差异。

| 表达式 | 触发时间 |
| --- | --- |
| `0 * * * *` | 每小时整点（首次默认） |
| `*/30 * * * *` | 每半小时 |
| `0 8 * * *` | 每天 08:00 |
| `0 8 * * mon` | 每周一 08:00 |

cron 决定什么时候执行；回查天数决定查询哪个申请日期范围，两者独立。参考 [APScheduler 用户指南](https://apscheduler.readthedocs.io/en/3.x/userguide.html)。

升级时安装新增的 APScheduler、tzlocal 和 tzdata 依赖，使用平台对应的初始化脚本即可，不要只复制前端文件。旧 `nocobase_sync.sqlite3` 间隔计划首次自动导入回查天数，但保持关闭并提示确认 cron；源数据库与旧任务历史保留，不再运行旧轮询定时器，也不再提供旧的间隔设置接口。

范围按 **ERP 申请日期** 查询，不是 NocoBase 创建日期或 ERP 更新日期。较早申请后来修改可能不在窗口内，需手动扩大日期范围；当前不保证历史更新无遗漏。

## 测试脚本

先自行启动服务，再只读预览：

```bash
python scripts/run_erp_nocobase_sync.py \
  --start-date 2026-09-28 --end-date 2026-09-29 --dry-run
```

确认后实际写入：

```bash
python scripts/run_erp_nocobase_sync.py \
  --start-date 2026-09-28 --end-date 2026-09-29
```

`--server http://127.0.0.1:8000` 指定 E-HRM 地址，`--timeout 600` 设置等待秒数。超时不会取消或重新提交；去任务中心查看。输出新增、更新、未变化、失败及逐条处理结果，不输出密钥。

## 接口

- `GET /api/v1/scheduled-tasks`：任务计划、最近触发和调度器状态。
- `GET /api/v1/scheduled-tasks/cron-preview?cron=...`：后五次触发时间。
- `POST /api/v1/scheduled-tasks`：新增已注册类型的计划。
- `PUT /api/v1/scheduled-tasks/{id}`：`name`、`task_type`、`cron`、`enabled`、`lookback_days`。
- `POST /api/v1/scheduled-tasks/{id}/run`：手动执行或预览，返回持久化执行记录。
- `GET /api/v1/scheduled-runs?job_id=...&page=1&page_size=20`：执行记录分页。
- `GET /api/v1/scheduled-runs/{id}`：单次执行详情。
- `GET /api/v1/scheduled-runs/{id}/logs?page=1&page_size=50`：步骤日志分页。
- `POST /api/v1/nocobase/sync`：可传 `start_date`、`end_date`、`dry_run`，返回任务编号；日期须同时填写。

新增/修改示例：`{"name":"ERP 同步","task_type":"erp_nocobase_sync","cron":"0 * * * *","enabled":false,"lookback_days":2}`。关闭的计划仍可手动执行。原同步脚本继续可用，它现在也会创建工作台执行记录。

写入使用 POST create/update，通过 `filterByTk` 定位更新，只发送来源字段，不带 `myBusinessRules` 或 `updateAssociationValues`。参考 [NocoBase 资源接口文档](https://docs.nocobase.com/cn/api/flow-engine/resource)，字段以本项目提供的请求样例为准。

若写入响应未保留 `erp_code` 或 `key_value`，校验会使任务报错并关闭全部同类同步计划，防止其他计划或后续周期反复新增。错误提供 NocoBase 记录 ID；写入可能已经发生，请先检查该记录和字段规则，再重新开启。NocoBase 的 `code` 与 ERP 编号不同是正常情况，不参与此校验。程序不自动修改线上表结构或唯一约束。没有数据库唯一约束时，本平台查重和锁不能阻止其他系统同时插入同一 ERP ID。

地址按提供的信息设置为 `http://cloud.njncc.com:443`，443 端口不代表 HTTPS。HTTP 不保护传输中的密钥和申请数据，正式部署应确认支持 HTTPS 后修改 `nocobase.site.base_url`。

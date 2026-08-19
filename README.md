# E-HRM 首版

当前版本实现了单位权益单自动化的通用骨架：

- Playwright 持久化浏览器会话；
- 自动填写账号密码，验证码由操作人员完成；
- 起止年月、险种、姓名查询模型；
- 查询、生成、下载页面对象；
- 统一异常编码、失败截图和日志；
- 下载文件重名保护及基础 PDF 校验；
- Playwright Codegen 录制入口。
- Excel 批量导入、完整校验和执行结果清单；
- 每人一个 PDF 与多人合并 PDF 两种模式；
- 一次性脚本由用户登录；桌面工作台在运行期间保持标签页登录状态。
- 桌面工作台测试入口，在程序生命周期内复用唯一浏览器标签页；
- 人员查询优先使用身份证作为社会保障号码，姓名仅作为非 Excel 调用的兜底。

实际智慧人社页面的 URL 和定位器尚未硬编码。需要录制一次真实流程后，将稳定定位器整理到 `config/settings.toml`。

## 1. 创建环境

前后端依赖分别锁定版本，但安装到同一个 `ehrm` Conda 环境。请在项目根目录依次执行：

```bash
conda env create -f environment.backend.yml
conda env update -n ehrm -f environment.frontend.yml
conda activate ehrm
playwright install chromium
```

版本文件职责：

- `environment.backend.yml`：Python 3.11.15 和后端运行环境；
- `environment.frontend.yml`：PySide6 + Qt Quick/QML 桌面前端；
- `environment.windows-build.yml`：未来仅在 Windows 打包机安装；
- `requirements/*.lock.txt`：各层精确的 Python 包版本。

开发机也可以使用包含后端、前端和测试依赖的组合环境：

```bash
conda env create -f environment.yml
conda activate ehrm
playwright install chromium
```

复制配置样例：

```bash
cp config/settings.example.toml config/settings.toml
```

`config/settings.toml`、浏览器资料目录、录制代码和下载文件均已加入 `.gitignore`。

## 2. 录制实际流程

建议录制，但录制结果只作为操作步骤和定位器的输入，不直接作为生产代码：

```bash
ehrm record --url "智慧人社登录页地址"
```

在打开的浏览器内依次完成：

1. **先在 Inspector 中暂停录制**，再输入账号密码并人工完成安全验证；
2. 进入“单位中心”；
3. 打开“单位权益单”；
4. 选择起止年月、险种，填写姓名；
5. 点击查询；
6. 选择结果并生成权益单；
7. 点击下载；
8. 关闭录制窗口。

登录成功后再恢复录制。否则 Codegen 可能把账号和密码以明文写入生成的 Python 文件。即使已经暂停录制，也要在提交录制材料前搜索并删除所有账号、密码、证件号码和 Cookie。

录制代码默认保存在 `artifacts/recorded_flow.py`，录制专用登录状态保存在 `data/codegen-profile/`。两者可能包含敏感信息，不要发送账号、密码、Cookie、身份证号或真实下载文件。提供录制材料前请先脱敏。

重点保留这些内容：

- 每一步对应的 `get_by_role`、`get_by_text` 或 `locator`；
- 登录后的 URL；
- 查询完成的稳定页面标志；
- “无数据”提示；
- 生成完成标志；
- 下载按钮是否触发浏览器下载，还是打开 PDF 新标签页。

## 3. 配置并运行

将录制得到的 URL 和定位器整理进 `config/settings.toml`，然后执行：

```bash
ehrm download \
  --start-month 2026-01 \
  --end-month 2026-06 \
  --insurance "养老保险" \
  --name "张三" \
  --output-dir ./downloads \
  --ask-password
```

用户可见的中文异常文案集中维护在 `config/error_messages.toml`。编码键属于系统协议，不应修改或删除；等号右侧中文可以按业务口径调整。程序启动时会校验每个 `ErrorCode` 都存在映射，缺项、未知编码或 TOML 格式错误都会在任务开始前报出配置错误。

也可以通过 `EHRM_USERNAME`、`EHRM_PASSWORD` 环境变量提供登录信息。不要把密码写入 TOML、命令参数或源码。

首次运行或登录状态过期时，程序会停在登录页面等待人工完成验证码；验证成功后继续执行。后续运行复用 `data/browser-profile/` 内的合法登录会话。

## 4. 桌面前端（Qt Quick/QML）

启动与原型一致的“信息化人力工作台”：

```bash
python scripts/run_gui.py
```

也可以使用安装后的命令：

```bash
ehrm-gui
```

当前桌面端包含：

- 下载带险种下拉选项和格式说明的 Excel 模板；
- 导入后校验必要字段、身份证、险种、日期和重复数据；
- 脱敏预览人员信息，显示查询条件组数和预计 PDF 数；
- “每人单独一份”和“相同查询条件合并”两种模式；
- 高级设置中的单批最多人数，默认 50；
- 执行前确认页，明确展示拆分条件、人数和文件数；
- 执行中可安全停止，保留已下载 PDF，并在结果 Excel 标记未处理人员；
- Playwright 在单一常驻线程的任务队列中运行，浏览器创建、连续任务和关闭始终位于同一 Python 执行上下文；
- 预留 ERP 上传、任务记录和系统设置模块入口。

界面层使用 Qt Quick/QML 组件化实现，Python 仅通过
`DesktopViewModel` 暴露状态和命令。自动化、Excel 校验和业务规则仍保持在
Python 服务层，便于后续扩展 ERP 页面或调整视觉样式。

默认保存到当前用户的 `Downloads` 目录，每次创建独立任务目录：

```text
权益单下载_YYYYMMDD_HHMMSS/
├── 原文件名_执行结果_YYYYMMDD_HHMMSS.xlsx
├── PDF/
│   └── 单位/部门或批量/权益单.pdf
└── _runs/result_YYYYMMDD_HHMMSS.json
```

浏览器资料、日志和失败截图保存在操作系统为本应用分配的用户数据目录，不写入程序安装目录。

## 5. Excel 命令行测试入口

输入文件第一行必须包含以下列，允许存在额外列：

```text
单位 | 部门 | 姓名 | 身份证 | 险种 | 开始时间 | 结束时间
```

身份证列必须设置为文本格式；时间支持 `YYYY-MM`、`YYYYMM`、Excel 日期等常见形式。建议先只校验并查看执行计划：

```bash
python scripts/run_excel_task.py \
  --input ./人员清单.xlsx \
  --mode individual \
  --output ./downloads \
  --dry-run
```

每人下载一个 PDF：

```bash
python scripts/run_excel_task.py \
  --input ./人员清单.xlsx \
  --mode individual \
  --output ./downloads
```

同单位、险种、起止年月的人员合并下载，每批最多50人：

```bash
python scripts/run_excel_task.py \
  --input ./人员清单.xlsx \
  --mode batch \
  --batch-size 50 \
  --output ./downloads
```

程序不修改输入 Excel。每次运行会在输出目录生成一份带时间戳的结果 Excel，保留原表内容和格式并追加“失败原因”列；查询或下载失败会精确写回对应原始行。`downloads/_runs/` 下仍会生成 JSON 结果清单，只记录 Excel 行号、状态、文件路径和错误，不复制身份证号码。

系统内部和 JSON 清单使用稳定异常编码流转，例如 `EMPLOYEE_NOT_FOUND`；终端、结果 Excel 和未来前端通过统一异常目录映射为“未查询到符合条件的人员”等中文含义，不直接向用户展示内部编码。

该网站登录状态与标签页绑定，默认不再进行跨进程静默会话检查。一次性脚本启动后由用户登录一次，并在当前 Excel 全部处理完毕前复用同一标签页；脚本退出后，下次启动通常需要重新登录。

### 桌面工作台测试入口

该网站登录状态与浏览器标签页绑定，关闭页面后通常无法跨进程恢复。桌面工作台在程序运行期间保存同一个 Playwright `Page`，可以登录一次后连续执行多个 Excel：

```bash
python scripts/run_workbench.py \
  --output ./downloads \
  --batch-size 50
```

启动后按提示依次输入 Excel 路径和模式。任务完成后浏览器不会关闭，可继续输入下一个 Excel；输入 `q` 后才彻底退出。若用户只是切换标签页或在自动化标签页进入其他页面，下个任务会在原标签页重新进入单位权益单。用户关闭原标签页、退出账号或官网会话过期时，程序会重新提示登录。

Excel 的身份证列保持必填。页面查询会将其填入“社会保障号码”输入框并清空姓名框，因此不会因为同名人员选择错误；代码层仍保留姓名查询兜底，但 Excel 导入不会产生身份证为空的任务。

每个新分组开始前会清空右侧历史人员，下载完成后不再清空，因此不会拖慢任务结束。险种、开始年月和结束年月以页面实际显示值为准；页面值已经符合当前 Excel 分组时才跳过选择，用户手动改动页面后也会自动纠正。每次身份证查询只检查左侧候选表格，并校验身份证匹配。预览会等待权益单正文标志出现，无法读取 canvas 正文时改用预览画面稳定性判断，再按 `preview_download_delay_ms` 延迟后点击下载；默认延迟为 1500 毫秒，可在 `config/settings.toml` 中调整为 1000 或 2000。

## 6. 当前适配边界

已根据录制结果适配 Ant Design 年月选择、险种下拉框、查询结果转移、预览弹窗和下载事件。姓名输入框与已选人员表格目前仍使用录制所得的相对定位器，第一次连接真实网站时可能需要在 `config/settings.toml` 中做一次小幅调整。

# ERP 参保、停保人员解析接口

这两个接口处理单条 ERP 申请。调用方提交已同步的申请编号、标题和问题描述；接口才会调用大模型提取人员，并查询 ERP 人员库补全身份证、公司、部门和员工编号。同步申请本身不触发人员解析，接口也不会执行参保或停保。

- 参保：`POST /api/v1/erp/enrollment/people-extraction`
- 停保：`POST /api/v1/erp/termination/people-extraction`

两者使用相同的请求格式：

```json
{
  "application_code": "RLSQ20260929-0001",
  "application_date": "2026-09-29",
  "title": "关于苏兆瑞停缴社保的申请",
  "description": "苏兆瑞，身份证号142725199612061613，请办理停保。",
  "erp_transaction_type": "社保咨询",
  "reasoning_mode": "off"
}
```

`application_code` 必填；`title` 和 `description` 至少填写一个。其余字段可留空。`reasoning_mode` 留空时使用当前模型的默认设置。

成功响应包含 `application_code`、`business_type`、`people`、`issues` 和 `needs_review`。每位人员的 `match_status` 为 `matched_by_identity`、`matched_by_name`、`not_found`、`ambiguous`、`name_mismatch`、`invalid_identity` 或 `lookup_failed`。`issues` 含问题编码、人员姓名和提示；有问题时 `needs_review=true`。查询到多名同名人员时，人员信息只保留姓名，身份证、公司、部门和员工编号均为空，并返回 `ERP_PERSON_AMBIGUOUS` 问题。原文明示的身份证在 ERP 人员库未命中时会保留，但不补充组织信息，并返回 `ERP_PERSON_NOT_FOUND` 问题。无法从原文识别具体姓名时返回空人员列表及 `AI_NO_PERSON_EXTRACTED` 问题。

大模型服务请求失败或返回不合规内容时，接口返回错误响应，不会把未验证的人员信息作为成功结果。调用方应展示错误信息，允许用户核对申请原文后重试。

## 按 ERP 申请编号联调

无需启动 E-HRM 服务，使用已配置好的 Python 环境直接运行：

```bash
python scripts/run_erp_social_analysis.py --code RLSQ20260929-0001
```

脚本会在 ERP 的「社保咨询」「单位社保权益单」中精确查找该编号，先运行业务分类，再解析参保、停保或权益单人员；结果会打印到终端。需要保留完整 JSON 时增加 `--output output/社保申请分析.json`。也可通过 `--model-profile` 和 `--reasoning-mode` 指定模型配置。脚本只读取与分析，不执行参保、停保或打印；如果分类不明确，保留 ERP 原始事务类型并提示人工复核，不猜测人员。

## 分类语义回归验证

分类依据申请最终希望取得的结果：获取已有缴费材料、建立参保关系或停止参保。标题和描述合并理解，允许口语和省略，不要求出现正式业务名称；真正目的不明确时保留 ERP 原始类型。生产提示词只维护通用判断规则，不追加具体申请案例，也不使用关键词强制覆盖模型分类。

分类响应中的 `evidence` 仅作为模型判断说明供人工查看，可以概述或引用，不要求与原文逐字匹配，也不作为分类成功的门槛；程序仍校验字段结构、文本类型和业务枚举。该说明并不是程序验证过的事实依据。人员解析中的姓名、身份证及其原文来源校验保持严格，不因分类说明规则放宽而改变。

独立回归测试覆盖口语开具、开始参保、停止参保，以及费用咨询、离职归档等容易混淆的边界。使用当前配置的真实模型验证：

```bash
EHRM_RUN_LIVE_AI_TESTS=1 python -m pytest -q tests/test_ai_business_classification_live.py
```

需要安装项目测试依赖并能访问所配置的模型服务。此测试只调用大模型，不登录 ERP、不启动浏览器、不提交业务；默认不设置该环境变量时跳过，以免普通测试意外调用外部模型。通过不表示所有自然语言申请都能正确分类；调整提示词或切换模型后应再次验证。

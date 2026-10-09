# NocoBase 人力事务表单 AI 解析按钮

此接入只解析和回填当前表单，不保存 NocoBase 记录，不办理权益单、参保或退保业务。E-HRM 本身没有登录功能，调用解析接口不使用 NocoBase API 密钥。现有 NocoBase API 密钥仅供 E-HRM 的后台同步等服务端功能使用。

## 配置按钮

1. 在 `NCC_HumProblem` 的新增或编辑表单工具栏添加「JS 操作」，名称建议为「AI 解析」。不要将它放在表格工具栏，因为那里可能没有 `ctx.form`。
2. 将 [nocobase_ai_form_action.js](../scripts/nocobase_ai_form_action.js) 的完整内容粘贴到 JS 操作编辑器。脚本默认调用 `http://192.168.31.65:8000/api/v1/nocobase/form-analysis`；地址变化时只修改脚本开头的 `ehrmAnalysisUrl`。
3. E-HRM 的 `config/settings.toml` 中 `nocobase.site.base_url` 必须与浏览器地址栏里 NocoBase 页面的来源（协议、域名、端口）一致，供跨域配置使用。修改配置后重启 E-HRM。
4. 打开一条测试表单，填写标题和事务/问题描述，点击「AI 解析」。类型不明确时显示原因且不修改表单；类型明确时展示人员与问题，确认后只回填事务类型及对应人员子表。已存在的人员行不会被覆盖；退保、参保的同一人员不会重复追加，权益单按人员、打印组、险种和起止月份判断重复，因此同一人不同打印需求会保留多行。最后由用户核对并手动提交表单。

接口接受 `application_code`、`application_date`、`title`、`description`、`erp_transaction_type`。参保人员的电话来自 ERP 人员库 `PB_Human.Phone`，缺失则为空；合同增加原因默认“新签”，合同起止日期默认分析当日及三年后，参保身份默认“企业职工”。户籍、户籍行政区划、月缴费工资、是否管理技术岗不自动填写。重名、姓名与身份证不符等问题会返回人工复核提示；不符的身份证不会回填。

## 浏览器连通性

按钮在使用者的浏览器中直接访问办公网 E-HRM，因此使用者电脑必须能打开 `http://192.168.31.65:8000/api/v1/health`。NocoBase 公网服务器无需访问 E-HRM 内网地址。

当前 NocoBase 来源配置为公网 HTTP 地址 `http://cloud.njncc.com:443`。现代 Chrome 对公网网页访问私有网段有额外的本地网络访问限制：即使 E-HRM CORS 预检通过，浏览器也可能在请求发出前拦截。若按钮报 `Failed to fetch` 或控制台出现 Local Network Access 错误，应优先使用安全的 NocoBase HTTPS 来源并在浏览器授权本地网络访问，或使用可在办公网以私有来源访问的 NocoBase 地址；不要把永久密钥写入按钮，也不要把 E-HRM 临时暴露到公网。是否能在当前浏览器工作，以真实页面联调为准。

## 本地验证

```bash
/opt/miniconda3/envs/ehrm/bin/python -m pytest -q tests/test_nocobase_form_analysis.py tests/test_web_business_people.py tests/test_erp_business_people.py tests/test_erp_person_database.py
node --test tests/nocobase_ai_form_action.test.cjs
```

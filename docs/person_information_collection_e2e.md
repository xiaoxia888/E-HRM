# 人员基础信息采集：仅录入测试

此入口复用系统设置中已保存的默认智慧人社单位账号完成登录，从大厅进入“人员基础信息采集”，并强校验办事地区为南京（`areaCode=320100`）。**不会点击业务提交按钮**。多行测试数据各占一个浏览器标签页，避免后续人员覆盖未提交的表单。

测试 Excel 仅支持 `.xlsx` / `.xlsm`，首行需包含以下列（顺序不限）：

| 身份证号 | 姓名 | 手机号 | 民族 | 户籍性质 | 省 | 市 | 区县 | 街道 | 社区村 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 18 位或 15 位 | 非空 | 11 位手机号 | 名称或编码，如 `汉族`/`01` | 网站选项名称或编号，如 `11` | 按下方规则填写 | | | | |

民族会在运行时读取 `#nation` 的实际下拉选项，可按名称或编码精确匹配，例如“汉族”或 `01`、“土家族”或 `15`。

户籍地行政区填写规则：

- 本省城镇、本省农村：填写省、市、区县、街道、社区村五级。
- 外省城镇、外省农村：只填写省、市、区县三级，街道和社区村留空。
- 香港特别行政区、澳门特别行政区、台湾、外国人：五个地址字段全部留空。

自动化会逐级读取智慧人社地址候选项。平台没有导入的区划名称、层级提前结束或导入路径没有填写到页面末级时，该人员会返回问题编码和问题信息，继续处理下一行。页面业务报错弹窗也会读取正文、关闭弹窗并写入该行结果。

先只检查文件和已保存的账号：

```bash
python -m ehrm.entrypoints.person_information_collection_e2e_cli --input /path/to/test.xlsx --check-input
```

实际打开浏览器并停在提交前，供人工核对：

```bash
python -m ehrm.entrypoints.person_information_collection_e2e_cli --input /path/to/test.xlsx --pause-after-fill
```

默认输出逐行结果至 `output/person-information-collection-e2e.xlsx`，当前页面截图至 `output/person-information-collection-e2e.png`。正式平台接入时调用 `PersonInformationService.prepare_with_page(page, items)`，传入 `PersonInformationItem` 对象数组；Excel 解析只存在于这个测试入口。

当前录制文件没有接口响应详情，因此页面就绪以正确业务 iframe、可操作输入框、加载遮罩消失和填写后回读判断。首次连接真实业务页面时，需核对户籍地址控件、户籍性质选项及额外必填字段；测试代码不具备自动提交能力。

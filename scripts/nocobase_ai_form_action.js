// 粘贴到 NCC_HumProblem 表单工具栏的 NocoBase「JS 操作」按钮。
// 只填充当前表单，不调用 NocoBase 保存/提交接口，也不携带 NocoBase API 密钥。
const ehrmAnalysisUrl = 'http://192.168.31.65:8000/api/v1/nocobase/form-analysis';
const form = ctx.form;
if (!form) {
  ctx.modal?.error?.({ title: '无法解析', content: '请将此按钮放在申请表单的工具栏中。' });
  return;
}

const current = form.getFieldsValue(true);
const text = (value) => String(value ?? '')
  .replace(/<\s*br\s*\/?\s*>/gi, '\n')
  .replace(/<\s*\/p\s*>/gi, '\n')
  .replace(/<[^>]*>/g, '')
  .replace(/&nbsp;/gi, ' ')
  .trim();
const title = text(current.title);
const description = text(current.problem_desc);
if (!title && !description) {
  ctx.modal?.warning?.({ title: '缺少申请内容', content: '请先填写标题或事务/问题描述。' });
  return;
}

const sourceTypes = {
  social_security_rights: '单位社保权益单',
  social_security_consult: '社保咨询',
  social_security_enrollment: '用工参保登记',
  social_security_termination: '退工停保登记',
};
const dateValue = current.initiation_date;
const applicationDate = dateValue
  ? (ctx.libs?.dayjs ? ctx.libs.dayjs(dateValue).format('YYYY-MM-DD') : String(dateValue).slice(0, 10))
  : '';
const sourceType = text(current.erp_all_field_value?.ProbType)
  || sourceTypes[current.prob_type] || '社保咨询';

let result;
try {
  const response = await fetch(ehrmAnalysisUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify({
      application_code: text(current.erp_code || current.code),
      application_date: applicationDate,
      title,
      description,
      erp_transaction_type: sourceType,
    }),
  });
  result = await response.json();
  if (!response.ok) {
    throw new Error(result?.message || `E-HRM 返回 HTTP ${response.status}`);
  }
} catch (error) {
  ctx.modal?.error?.({
    title: 'AI 解析失败',
    content: `${error?.message || error}。请确认办公网可访问 E-HRM；若浏览器拦截内网访问，请检查本地网络访问权限。`,
  });
  return;
}

if (!result?.classification?.classified) {
  ctx.modal?.warning?.({
    title: '无法确定事务类型',
    content: result?.classification?.reason || result?.issues?.[0]?.message || '请人工核对申请内容。',
  });
  return;
}

const values = result.form_values || {};
const relation = {
  social_security_rights: 'related_persons',
  social_security_termination: 'termination_person',
  social_security_enrollment: 'insurance_person',
}[values.prob_type];
if (!relation || !Array.isArray(values[relation])) {
  ctx.modal?.error?.({ title: 'AI 解析失败', content: 'E-HRM 返回的表单数据不完整，未修改当前表单。' });
  return;
}

const issues = Array.isArray(result.issues) ? result.issues : [];
const names = values[relation].map((person) => person.user_name || '未识别姓名').join('、') || '无人员';
const issueText = issues.length
  ? `\n待人工核对 ${issues.length} 项：${issues.slice(0, 5).map((item) => item.message).join('；')}`
  : '';
const confirmed = await ctx.modal.confirm({
  title: '确认回填 AI 解析结果',
  content: `事务类型：${result.business_type}。人员：${names}。${issueText}\n只会填入当前表单，不会自动保存或提交。`,
  okText: '填入当前表单',
  cancelText: '取消',
});
if (!confirmed) return;

const existing = Array.isArray(current[relation]) ? current[relation] : [];
const samePerson = (left, right) => {
  const leftId = text(left.id_card_no).toUpperCase();
  const rightId = text(right.id_card_no).toUpperCase();
  if (leftId && rightId) return leftId === rightId;
  return Boolean(text(left.user_name)) && text(left.user_name) === text(right.user_name);
};
const sameRow = (left, right) => {
  if (!samePerson(left, right)) return false;
  if (relation !== 'related_persons') return true;
  return ['print_group', 'insurance_type', 'start_month', 'end_month']
    .every((field) => text(left[field]).slice(0, 10) === text(right[field]).slice(0, 10));
};
const seen = [...existing];
const additions = values[relation].filter((person) => {
  if (seen.some((row) => sameRow(row, person))) return false;
  seen.push(person);
  return true;
}).map((person, index) => ({
  ...person,
  __is_new__: true,
  __index__: `${Date.now()}-${index}`,
}));
form.setFieldsValue({ prob_type: values.prob_type, [relation]: [...existing, ...additions] });
ctx.message?.success?.(`已填入 ${additions.length} 名人员，请核对后手动提交表单。`);
if (issues.length) ctx.message?.warning?.(`另有 ${issues.length} 项解析问题，请逐项核对。`);

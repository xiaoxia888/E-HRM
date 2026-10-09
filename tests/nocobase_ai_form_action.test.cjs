const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'scripts', 'nocobase_ai_form_action.js'), 'utf8',
);
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const action = new AsyncFunction('ctx', 'fetch', source);

function setup(result, confirmed = true, initial = {}) {
  const writes = [];
  const notices = [];
  let submitCount = 0;
  const ctx = {
    form: {
      getFieldsValue: () => ({
        code: 'RLSQ20260929-0003', title: '退保申请', problem_desc: '<p>张伟停保</p>',
        initiation_date: '2026-09-29', prob_type: 'social_security_consult', ...initial,
      }),
      setFieldsValue: (values) => writes.push(values),
      submit: () => { submitCount += 1; },
    },
    modal: {
      confirm: async (details) => { notices.push(details); return confirmed; },
      warning: (details) => notices.push(details),
      error: (details) => notices.push(details),
    },
    message: { success: (value) => notices.push(value), warning: (value) => notices.push(value) },
  };
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => result };
  };
  return { ctx, requests, writes, notices, fetchImpl, submitCount: () => submitCount };
}

test('unclear classification displays reason and leaves form unchanged', async () => {
  const state = setup({ classification: { classified: false, reason: '意图不明确' }, form_values: {}, issues: [] });
  await action(state.ctx, state.fetchImpl);
  assert.equal(state.writes.length, 0);
  assert.match(JSON.stringify(state.notices), /意图不明确/);
  assert.equal(state.requests[0].url, 'http://192.168.31.65:8000/api/v1/nocobase/form-analysis');
  assert.equal(state.requests[0].options.credentials, 'omit');
  assert.equal(state.requests[0].options.headers['Content-Type'], 'application/json');
  assert.equal(JSON.parse(state.requests[0].options.body).description, '张伟停保');
});

test('confirmed result appends new person without submitting or replacing old row', async () => {
  const result = {
    classification: { classified: true }, business_type: '退工停保登记',
    form_values: { prob_type: 'social_security_termination', termination_person: [
      { user_name: '张伟', id_card_no: '320482198706114614' },
    ] }, issues: [],
  };
  const existing = { id: 12, user_name: '赵佳男', id_card_no: '142725199612061613' };
  const state = setup(result, true, { termination_person: [existing] });
  await action(state.ctx, state.fetchImpl);
  assert.equal(state.writes.length, 1);
  const written = state.writes[0];
  assert.equal(written.prob_type, 'social_security_termination');
  assert.deepEqual(written.termination_person[0], existing);
  assert.equal(written.termination_person[1].user_name, '张伟');
  assert.equal(written.termination_person[1].__is_new__, true);
  assert.equal(state.submitCount(), 0);
});

test('cancelled review does not write any field', async () => {
  const state = setup({
    classification: { classified: true }, business_type: '用工参保登记',
    form_values: { prob_type: 'social_security_enrollment', insurance_person: [] }, issues: [],
  }, false);
  await action(state.ctx, state.fetchImpl);
  assert.equal(state.writes.length, 0);
});

test('rights keeps separate print periods for the same person and skips an exact duplicate', async () => {
  const first = {
    user_name: '董健', id_card_no: '341125199908201295', print_group: '组1',
    insurance_type: 'elderly_care', start_month: '2026-07-01', end_month: '2026-09-01',
  };
  const second = { ...first, print_group: '组2', start_month: '2026-10-01' };
  const result = {
    classification: { classified: true }, business_type: '单位社保权益单',
    form_values: { prob_type: 'social_security_rights', related_persons: [first, second] },
    issues: [],
  };
  const state = setup(result, true, { related_persons: [{ id: 7, ...first }] });
  await action(state.ctx, state.fetchImpl);

  assert.equal(state.writes[0].related_persons.length, 2);
  assert.equal(state.writes[0].related_persons[1].print_group, '组2');
});

test('a name-only existing row is not duplicated when AI resolves its identity', async () => {
  const result = {
    classification: { classified: true }, business_type: '退工停保登记',
    form_values: { prob_type: 'social_security_termination', termination_person: [
      { user_name: '张伟', id_card_no: '320482198706114614' },
    ] }, issues: [],
  };
  const state = setup(result, true, { termination_person: [
    { id: 7, user_name: '张伟', id_card_no: '' },
  ] });
  await action(state.ctx, state.fetchImpl);

  assert.equal(state.writes[0].termination_person.length, 1);
});

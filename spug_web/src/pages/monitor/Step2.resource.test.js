import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import {MemoryRouter} from 'react-router-dom';
import Step2 from './Step2';
import store from './store';
import {http} from 'libs';
import {resourceDefaults} from './resource';

jest.mock('mobx-react', () => ({observer: component => component}));
jest.mock('./store', () => ({record: {}, fetchRecords: jest.fn(), fetchOverviews: jest.fn()}));
jest.mock('../alarm/group/store', () => ({records: [{id: '1', name: 'ops'}]}));
jest.mock('libs', () => ({t: text => text, http: {get: jest.fn(), post: jest.fn()}}));

let root;
beforeEach(() => {
  window.matchMedia = window.matchMedia || (() => ({matches: false, addListener() {}, removeListener() {}}));
  root = document.createElement('div');
  document.body.appendChild(root);
  jest.clearAllMocks();
  http.get.mockResolvedValue([]);
  http.post.mockResolvedValue({});
  store.record = {type: '7', name: 'CPU', group: 'test', targets: [7, 8], extra: resourceDefaults(),
    notify_grp: ['1'], notify_mode: ['4']};
});
afterEach(() => {
  act(() => {ReactDOM.unmountComponentAtNode(root);});
  root.remove();
});

test('legacy monitor channels are explicitly marked as retired', async () => {
  store.record.notify_mode = ['1', '4'];
  await act(async () => {ReactDOM.render(<MemoryRouter><Step2/></MemoryRouter>, root);});
  expect(root.querySelector('.ant-alert-error').textContent).toContain('包含已下线的报警方式');
  expect(root.textContent).toContain('邮件');
  expect(root.textContent).toContain('钉钉');
  expect(root.textContent).toContain('企业微信');
  expect(root.textContent).toContain('飞书');
});

test.each([false, true])('resource submission reuses alert settings, editing=%s', async editing => {
  if (editing) Object.assign(store.record, {id: 12, rate: 15, threshold: 2, quiet: 60,
    extra: {...resourceDefaults('disk'), value: 91.5, mount: '/data'}});
  const expected = {...store.record, rate: editing ? 15 : 5, threshold: editing ? 2 : 3,
    quiet: editing ? 60 : 1440, ai_mode: ''};
  await act(async () => {ReactDOM.render(<MemoryRouter><Step2/></MemoryRouter>, root);});
  const disabledAi = Array.from(root.querySelectorAll('label')).find(x => x.textContent === '不启用');
  expect(disabledAi.querySelector('input').checked).toBe(true);
  const submit = Array.from(root.querySelectorAll('button')).find(x => x.textContent.replace(/\s/g, '') === '提交');
  expect(submit.disabled).toBe(false);
  await act(async () => {Simulate.click(submit);});
  expect(http.post).toHaveBeenCalledWith('/api/monitor/', expect.objectContaining(expected));
  expect(store.fetchRecords).toHaveBeenCalledTimes(1);
  expect(store.fetchOverviews).toHaveBeenCalledTimes(1);
});

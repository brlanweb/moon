import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {http} from 'libs';
import QueryPanel from './QueryPanel';


jest.mock('libs', () => ({
  hasPermission: () => true,
  http: require('../../libs/http').default,
  t: text => text,
}));

jest.mock('components', () => ({
  ACEditor: ({value, onChange, editorRef}) => {
    editorRef.current = {editor: {getSelectedText: () => '', focus: jest.fn()}};
    return (
      <textarea aria-label="database-command" value={value || ''}
                onChange={event => onChange(event.target.value)}/>
    );
  },
}));

const PRODUCTION_CONNECTION = {
  id: 7,
  name: '生产订单库',
  type: 'mysql',
  type_alias: 'MySQL',
  host: 'db.example.com',
  port: 3306,
  environment: 'production',
  read_only: false,
  connect_timeout: 30,
  query_timeout: 120,
};

let root;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function renderPanel(props = {}) {
  act(() => {
    ReactDOM.render(
      <QueryPanel
        connection={PRODUCTION_CONNECTION}
        activeDatabase="tenant_42"
        command="UPDATE orders SET status = 'paid' WHERE id = 42;"
        onCommandChange={jest.fn()}
        {...props}/>,
      root,
    );
  });
}

function button(text) {
  return Array.from(document.body.querySelectorAll('button'))
    .find(item => item.textContent.includes(text));
}

beforeEach(() => {
  Object.defineProperty(window, 'crypto', {configurable: true, value: require('crypto').webcrypto});
  jest.clearAllMocks();
  jest.useFakeTimers();
  requests = [];
  responses = [];
  http.defaults.adapter = async config => {
    requests.push(config);
    const next = responses.shift();
    if (next instanceof Error) {
      next.config = config;
      if (next.response) next.response.config = config;
      else next.request = {};
      throw next;
    }
    if (next && next.promise) return next.promise.catch(error => {
      error.config = config;
      error.request = {};
      throw error;
    });
    return {status: 200, headers: {}, config, data: next};
  };
  window.matchMedia = window.matchMedia || (() => ({matches: false, addListener() {}, removeListener() {}}));
  root = document.createElement('div');
  document.body.appendChild(root);
});

afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(root);
  });
  root.remove();
  jest.useRealTimers();
  document.body.querySelectorAll('.ant-modal-root').forEach(item => item.remove());
});


let requests;
let responses;
const envelope = data => ({data, error: ''});
async function tick() {
  act(() => jest.advanceTimersByTime(650));
  await flush();
}
function expectUnlocked() {
  expect(button('运行').classList.contains('ant-btn-loading')).toBe(false);
  expect(root.querySelector('.ant-select').classList.contains('ant-select-disabled')).toBe(false);
}
function expectLocked() {
  expect(button('运行').classList.contains('ant-btn-loading')).toBe(true);
  expect(root.querySelector('.ant-select').classList.contains('ant-select-disabled')).toBe(true);
}

test.each(['权限拒绝', '数据库连接不存在', '参数校验失败', '只读策略拒绝', '确认令牌过期', '注册表不可用'])(
  'structured pre-execution rejection unlocks without polling: %s', async message => {
    responses.push({data: '', error: message, execution_status: 'not_started'});
    renderPanel();
    act(() => button('运行').click());
    await flush();
    expectUnlocked();
    expect(root.textContent).toContain(message);
    await tick();
    expect(requests.map(r => r.url)).toEqual(['/api/database/execute/']);
  });

test('resolved not_started also unlocks without polling', async () => {
  responses.push(envelope({status: 'not_started', message: '请求未执行'}));
  renderPanel();
  act(() => button('运行').click());
  await flush();
  expectUnlocked();
  expect(root.querySelector('.ant-alert-error').textContent).toContain('请求未执行');
  await tick();
  expect(requests).toHaveLength(1);
});

test.each(['network', 'unknown'])('confirmation closes before %s execution and stop remains reachable for retry', async kind => {
  const query = deferred();
  responses.push(envelope({requires_confirmation: true, confirmation_token: 'immutable-token', statement_types: ['UPDATE']}), query);
  renderPanel();
  act(() => button('运行').click());
  await flush();
  const original = JSON.parse(requests[0].data);
  renderPanel({command: 'DELETE FROM other', activeDatabase: 'other'});
  act(() => button('确认执行').click());
  await flush();
  const wrap = document.querySelector('.ant-modal-wrap');
  expect(!wrap || getComputedStyle(wrap).display === 'none').toBe(true);
  expect(button('停止').disabled).toBe(false);
  expect(JSON.parse(requests[1].data)).toEqual({...original, confirmation_token: 'immutable-token'});
  if (kind === 'network') query.reject(new Error('Network Error'));
  else query.resolve({status: 200, headers: {}, config: requests[1], data: envelope({status: 'unknown', message: '结果未知'})});
  await flush();
  responses.push(envelope({status: 'cancelling', cancel_status: 'failed', cancel_error: '控制失败'}));
  act(() => button('停止').click());
  await flush();
  expectLocked();
  expect(button('停止').disabled).toBe(false);
  responses.push(envelope({status: 'cancelling'}));
  act(() => button('停止').click());
  await flush();
  expect(JSON.parse(requests[3].data)).toEqual({id: 7, execution_id: original.execution_id});
});

test('network loss polls and stays locked until a definite terminal state', async () => {
  responses.push(new Error('Network Error'), envelope({}), new Error('timeout'), envelope({status: 'cancelled'}));
  renderPanel();
  act(() => button('运行').click());
  await flush();
  expectLocked();
  await tick();
  expectLocked();
  await tick();
  expectLocked();
  await tick();
  expectUnlocked();
  expect(root.textContent).toContain('查询已中断');
});

test('explicit status rejection stops automatic polling without claiming execution ended', async () => {
  responses.push(new Error('Network Error'), {data: '', error: '权限拒绝', execution_status: 'unavailable'});
  renderPanel();
  act(() => button('运行').click());
  await flush();
  await tick();
  expectLocked();
  expect(button('停止').disabled).toBe(false);
  await tick();
  await tick();
  expect(requests).toHaveLength(2);
  expect(root.textContent).toContain('权限拒绝');
});

test('legacy HTTP consumers still reject with the original string', async () => {
  responses.push({data: '', error: '权限拒绝', execution_status: 'not_started'});
  await expect(http.post('/api/other/', {})).rejects.toBe('权限拒绝');
});


test.each(['network', 'unknown'])('stop can be retried when an already stopping query becomes %s', async kind => {
  const query = deferred();
  responses.push(query, envelope({status: 'cancelling'}));
  renderPanel();
  act(() => button('运行').click());
  await flush();
  act(() => button('停止').click());
  await flush();
  if (kind === 'network') query.reject(new Error('Network Error'));
  else query.resolve({status: 200, headers: {}, config: requests[0], data: envelope({status: 'unknown'})});
  await flush();
  expectLocked();
  expect(button('停止')).toBeDefined();
  expect(button('停止').classList.contains('ant-btn-loading')).toBe(false);
});

test.each([400, 401, 403, 404, 405, 413, 415, 422, 429])('HTTP %s admission rejection unlocks without polling', async status => {
  const error = new Error('HTTP rejection');
  error.response = {status, headers: {}, data: {error: 'rejected'}};
  responses.push(error);
  renderPanel();
  act(() => button('运行').click());
  await flush();
  expectUnlocked();
  await tick();
  expect(requests).toHaveLength(1);
});

test.each([401, 403, 500])('HTTP %s status rejection terminates automatic polling and keeps lock', async status => {
  const error = new Error('HTTP rejection');
  error.response = {status, headers: {}, data: {error: 'rejected'}};
  responses.push(new Error('Network Error'), error);
  renderPanel();
  act(() => button('运行').click());
  await flush();
  await tick();
  expectLocked();
  await tick();
  expect(requests).toHaveLength(2);
});

test('unclassified execute error response stays locked without an automatic poll loop', async () => {
  responses.push({data: '', error: 'Exception: internal failure'});
  renderPanel();
  act(() => button('运行').click());
  await flush();
  expectLocked();
  await tick();
  expect(requests).toHaveLength(1);
});


test('legacy HTTP network failures remain string rejections', async () => {
  responses.push(new Error('Network Error'));
  try {
    await http.get('/api/other/');
    throw new Error('expected rejection');
  } catch (error) {
    expect(typeof error).toBe('string');
    expect(error).toContain('Network Error');
  }
});


test.each([null, {data: null, error: ''}, {unexpected: true}])('malformed execute response %j is not mistaken for network loss', async response => {
  responses.push(response);
  renderPanel();
  act(() => button('运行').click());
  await flush();
  expectLocked();
  await tick();
  await tick();
  expect(requests).toHaveLength(1);
});

test('malformed status response terminates automatic recovery without unlocking', async () => {
  responses.push(new Error('Network Error'), envelope(null));
  renderPanel();
  act(() => button('运行').click());
  await flush();
  await tick();
  expectLocked();
  await tick();
  expect(requests).toHaveLength(2);
});

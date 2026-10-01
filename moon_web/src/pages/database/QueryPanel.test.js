import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {http} from 'libs';
import QueryPanel from './QueryPanel';


jest.mock('libs', () => ({
  hasPermission: () => true,
  http: {post: jest.fn()},
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
  const promise = new Promise(resolvePromise => {
    resolve = resolvePromise;
  });
  return {promise, resolve};
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
  window.matchMedia = window.matchMedia || (() => ({matches: false, addListener() {}, removeListener() {}}));
  root = document.createElement('div');
  document.body.appendChild(root);
});

afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(root);
  });
  root.remove();
  document.body.querySelectorAll('.ant-modal-root').forEach(item => item.remove());
});

test('shows a dangerous production confirmation without treating the challenge as a result', async () => {
  http.post.mockResolvedValue({
    requires_confirmation: true,
    confirmation_token: 'signed-token',
    statement_types: ['UPDATE'],
    execution_database: 'backend_default',
  });
  renderPanel();

  act(() => button('运行').click());
  await flush();

  expect(http.post).toHaveBeenCalledTimes(1);
  expect(http.post).toHaveBeenCalledWith('/api/database/execute/', {
    id: 7,
    execution_id: expect.any(String),
    command: "UPDATE orders SET status = 'paid' WHERE id = 42;",
    database: 'tenant_42',
  }, {timeout: 155000, executionProtocol: true});
  const modal = document.querySelector('.ant-modal');
  expect(modal).not.toBeNull();
  expect(modal.textContent).toContain('生产订单库');
  expect(modal.textContent).toContain('backend_default');
  expect(modal.textContent).not.toContain('执行数据库：tenant_42');
  expect(modal.textContent).toContain('UPDATE');
  expect(modal.querySelector('pre').textContent).toBe("UPDATE orders SET status = 'paid' WHERE id = 42;");
  expect(document.body.textContent).toContain('运行命令后在这里查看结果');

  await flush();
  expect(http.post).toHaveBeenCalledTimes(1);
});

test('cancelling a production challenge does not send a second request', async () => {
  http.post.mockResolvedValue({
    requires_confirmation: true,
    confirmation_token: 'signed-token',
    statement_types: ['UPDATE'],
  });
  renderPanel();

  act(() => button('运行').click());
  await flush();
  act(() => document.querySelector('.ant-modal-footer .ant-btn-default').click());
  await flush();

  expect(http.post).toHaveBeenCalledTimes(1);
  expect(document.querySelector('.ant-modal').style.display).toBe('none');
});

test('confirms by retrying the identical execution with the challenge token and renders its result', async () => {
  http.post
    .mockResolvedValueOnce({
      requires_confirmation: true,
      confirmation_token: 'signed-token',
      statement_types: ['UPDATE'],
    })
    .mockResolvedValueOnce({columns: [], rows: [], affected: 1, elapsed: 18, message: '执行成功'});
  renderPanel();

  act(() => button('运行').click());
  await flush();
  act(() => button('确认执行').click());
  await flush();

  expect(http.post).toHaveBeenCalledTimes(2);
  expect(http.post).toHaveBeenNthCalledWith(2, '/api/database/execute/', {
    id: 7,
    execution_id: expect.any(String),
    command: "UPDATE orders SET status = 'paid' WHERE id = 42;",
    database: 'tenant_42',
    confirmation_token: 'signed-token',
  }, {timeout: 155000, executionProtocol: true});
  expect(document.body.textContent).toContain('影响行数: 1');
});

test('shows loading while executing and ignores another click', async () => {
  const request = deferred();
  http.post.mockReturnValue(request.promise);
  renderPanel();

  act(() => button('运行').click());
  expect(button('运行').classList.contains('ant-btn-loading')).toBe(true);
  act(() => button('运行').click());
  expect(http.post).toHaveBeenCalledTimes(1);

  await act(async () => {
    request.resolve({columns: ['value'], rows: [[1]], affected: 0, elapsed: 3});
    await request.promise;
  });
});

test('shows production and read-only tags but omits them for a normal writable connection', () => {
  renderPanel({connection: {...PRODUCTION_CONNECTION, read_only: true}});
  const tags = Array.from(root.querySelectorAll('.ant-tag'));
  expect(tags.find(tag => tag.textContent === '生产').classList.contains('ant-tag-red')).toBe(true);
  expect(tags.some(tag => tag.textContent === '只读')).toBe(true);

  act(() => {
    ReactDOM.render(
      <QueryPanel
        connection={{...PRODUCTION_CONNECTION, environment: 'normal', read_only: false}}
        activeDatabase="tenant_42"
        command="SELECT 1;"
        onCommandChange={jest.fn()}/>,
      root,
    );
  });
  expect(Array.from(root.querySelectorAll('.ant-tag')).map(tag => tag.textContent))
    .toEqual(['MySQL']);
});

test.each([1, undefined])('keeps the legacy request timeout floor for query_timeout=%s', async queryTimeout => {
  http.post.mockResolvedValue({columns: ['value'], rows: [[1]], affected: 0, elapsed: 2});
  renderPanel({
    connection: {...PRODUCTION_CONNECTION, environment: 'normal', query_timeout: queryTimeout},
    command: 'SELECT 1;',
  });

  act(() => button('运行').click());
  await flush();

  expect(http.post).toHaveBeenCalledWith('/api/database/execute/', expect.any(Object), {timeout: 45000, executionProtocol: true});
});

test('keeps rendering ordinary query responses', async () => {
  http.post.mockResolvedValue({columns: ['id'], rows: [[42]], affected: 0, elapsed: 6});
  renderPanel({command: 'SELECT id FROM orders;'});

  act(() => button('运行').click());
  await flush();

  expect(document.body.textContent).toContain('42');
  expect(document.body.textContent).toContain('1 行');
  expect(document.querySelector('.ant-modal')).toBeNull();
});

test('stop only requests cancellation and keeps the execution locked until acknowledgement', async () => {
  const request = deferred();
  http.post.mockReturnValueOnce(request.promise).mockResolvedValue({status: 'cancelling'});
  renderPanel({command: 'SELECT SLEEP(10)'});
  act(() => button('运行').click());
  const payload = http.post.mock.calls[0][1];
  expect(payload.execution_id).toMatch(/^\d+\.[0-9a-f-]+$/);
  expect(button('停止')).toBeDefined();
  act(() => button('停止').click());
  await flush();
  expect(http.post).toHaveBeenLastCalledWith('/api/database/cancel/', {
    id: 7, execution_id: payload.execution_id,
  }, {executionProtocol: true});
  expect(button('正在中断')).toBeDefined();
  act(() => button('运行').click());
  expect(http.post).toHaveBeenCalledTimes(2);
  request.resolve({status: 'cancelled', columns: [], rows: [], affected: 0, elapsed: 1, message: '查询已中断'});
  await flush();
  expect(button('正在中断')).toBeUndefined();
  expect(document.body.textContent).toContain('查询已中断');
});

test('unsupported stop preserves running state and explains the failure', async () => {
  const request = deferred();
  http.post.mockReturnValueOnce(request.promise).mockResolvedValue({status: 'cancelling', cancel_status: 'unsupported'});
  renderPanel({command: 'SELECT 1'});
  act(() => button('运行').click());
  act(() => button('停止').click());
  await flush();
  expect(button('运行').classList.contains('ant-btn-loading')).toBe(true);
  expect(document.body.textContent).toContain('不支持精确安全取消');
  request.resolve({columns: [], rows: [], affected: 0, elapsed: 1});
  await flush();
});

test('locks the database during production confirmation and executes the original schema snapshot', async () => {
  http.post.mockResolvedValueOnce({requires_confirmation: true, confirmation_token: 'token',
    execution_database: 'app / tenant', statement_types: ['UPDATE']})
    .mockResolvedValueOnce({columns: [], rows: [], affected: 1});
  renderPanel({connection: {...PRODUCTION_CONNECTION, type: 'postgresql', database: 'app'},
    activeDatabase: 'tenant', databases: ['tenant', 'other']});
  act(() => button('运行').click());
  await flush();
  expect(root.querySelector('.ant-select').classList.contains('ant-select-disabled')).toBe(true);
  const first = http.post.mock.calls[0][1];
  act(() => button('确认执行').click());
  await flush();
  expect(http.post.mock.calls[1][1]).toEqual({...first, confirmation_token: 'token'});
  expect(first.database).toBe('tenant');
});

test('a late stop response cannot replace a completed execution with cancelling', async () => {
  const query = deferred();
  const cancellation = deferred();
  http.post.mockReturnValueOnce(query.promise).mockReturnValueOnce(cancellation.promise);
  renderPanel({command: 'SELECT 42'});
  act(() => button('运行').click());
  act(() => button('停止').click());
  query.resolve({columns: ['answer'], rows: [[42]], elapsed: 1});
  await flush();
  cancellation.resolve({status: 'cancelling'});
  await flush();
  expect(button('正在中断')).toBeUndefined();
  expect(button('运行').classList.contains('ant-btn-loading')).toBe(false);
  expect(root.textContent).toContain('42');
});

test('a failed stop request keeps the original execution running', async () => {
  const query = deferred();
  http.post.mockReturnValueOnce(query.promise).mockRejectedValueOnce('denied');
  renderPanel();
  act(() => button('运行').click());
  act(() => button('停止').click());
  await flush();
  expect(root.textContent).toContain('停止失败，查询仍在运行');
  expect(button('运行').classList.contains('ant-btn-loading')).toBe(true);
  query.resolve({columns: [], rows: [], elapsed: 1});
  await flush();
});

test('a definite policy rejection ends loading and shows the server failure', async () => {
  http.post.mockResolvedValue({status: 'failed', message: '只读连接不允许执行该命令'});
  renderPanel();
  act(() => button('运行').click());
  await flush();
  expect(button('运行').classList.contains('ant-btn-loading')).toBe(false);
  expect(root.textContent).toContain('只读连接不允许执行该命令');
});

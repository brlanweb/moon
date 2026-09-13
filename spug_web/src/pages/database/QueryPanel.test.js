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
    command: "UPDATE orders SET status = 'paid' WHERE id = 42;",
    database: 'tenant_42',
  }, {timeout: 155000});
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
    command: "UPDATE orders SET status = 'paid' WHERE id = 42;",
    database: 'tenant_42',
    confirmation_token: 'signed-token',
  }, {timeout: 155000});
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

  expect(http.post).toHaveBeenCalledWith('/api/database/execute/', expect.any(Object), {timeout: 45000});
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

import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import {message} from 'antd';
import {http} from 'libs';
import ConnectionForm from './ConnectionForm';

jest.mock('libs', () => ({
  http: {post: jest.fn()},
  t: text => text,
}));

let root;

function button(text) {
  return Array.from(document.body.querySelectorAll('button')).find(item => item.textContent.includes(text));
}

function change(id, value) {
  Simulate.change(document.getElementById(id), {target: {value}});
}

async function flush() {
  await act(async () => {
    await new Promise(resolve => setImmediate(resolve));
  });
}

function renderForm(record = {}, props = {}) {
  act(() => {
    ReactDOM.render(
      <ConnectionForm record={record} visible onClose={jest.fn()} onSaved={jest.fn()} {...props}/>,
      root,
    );
  });
}

function clickControl(control) {
  const element = typeof control === 'string' ? document.getElementById(control) : control;
  act(() => element.click());
}

beforeEach(() => {
  jest.clearAllMocks();
  window.matchMedia = window.matchMedia || (() => ({matches: false, addListener() {}, removeListener() {}}));
  http.post.mockResolvedValue({});
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

test('imports a connection URI into real form controls without submitting the raw URI', async () => {
  const success = jest.spyOn(message, 'success').mockImplementation(() => {});
  try {
    renderForm();
    act(() => button('导入连接 URI').click());
    act(() => change('connection_uri', 'postgres://report%40user:p%2Fass@[2001:db8::8]/sales%2Farchive?ssl=require'));
    act(() => button('解析并填充').click());

    expect(document.querySelector('input[value="postgresql"]').checked).toBe(true);
    expect(document.getElementById('host').value).toBe('2001:db8::8');
    expect(document.getElementById('port').value).toBe('5432');
    expect(document.getElementById('username').value).toBe('report@user');
    expect(document.getElementById('password').value).toBe('p/ass');
    expect(document.getElementById('database').value).toBe('sales/archive');
    expect(document.getElementById('use_ssl').getAttribute('aria-checked')).toBe('true');
    expect(success).toHaveBeenCalledWith('连接 URI 已导入');

    act(() => change('name', '报表库'));
    act(() => button('保存连接').click());
    await flush();

    expect(http.post).toHaveBeenCalledWith('/api/database/connection/', expect.objectContaining({
      type: 'postgresql',
      host: '2001:db8::8',
      port: 5432,
      username: 'report@user',
      password: 'p/ass',
      database: 'sales/archive',
      use_ssl: true,
    }));
    expect(http.post.mock.calls[0][1]).not.toHaveProperty('connection_uri');
  } finally {
    success.mockRestore();
  }
});

test('masks the URI and clears it when the import area is collapsed', () => {
  renderForm();
  act(() => button('导入连接 URI').click());
  expect(document.getElementById('connection_uri').type).toBe('password');
  act(() => change('connection_uri', 'postgresql://user:secret@db.example.com/app'));
  act(() => button('导入连接 URI').click());
  act(() => button('导入连接 URI').click());
  expect(document.getElementById('connection_uri').value).toBe('');
});

test('clears the URI when the outer modal closes and reopens', () => {
  const props = {onClose: jest.fn(), onSaved: jest.fn()};
  renderForm({}, props);
  act(() => button('导入连接 URI').click());
  act(() => change('connection_uri', 'postgresql://user:secret@db.example.com/app'));
  act(() => document.querySelector('.ant-modal-close').click());
  expect(props.onClose).toHaveBeenCalledTimes(1);
  act(() => button('导入连接 URI').click());
  expect(document.getElementById('connection_uri').value).toBe('');

  act(() => change('connection_uri', 'postgresql://user:new-secret@db.example.com/app'));
  act(() => {
    ReactDOM.render(<ConnectionForm record={{}} visible={false} {...props}/>, root);
  });
  act(() => {
    ReactDOM.render(<ConnectionForm record={{}} visible {...props}/>, root);
  });
  act(() => button('导入连接 URI').click());
  expect(document.getElementById('connection_uri').value).toBe('');
});

test('keeps an invalid URI visible so the user can correct it', () => {
  const error = jest.spyOn(message, 'error').mockImplementation(() => {});
  try {
    renderForm();
    act(() => button('导入连接 URI').click());
    act(() => change('connection_uri', 'postgresql://user%ZZ@db.example.com/app'));
    act(() => button('解析并填充').click());
    expect(document.getElementById('connection_uri').value).toBe('postgresql://user%ZZ@db.example.com/app');
    expect(error).toHaveBeenCalledWith('连接 URI 编码无效');
  } finally {
    error.mockRestore();
  }
});

test('submits governance defaults for a new connection from collapsed advanced settings', async () => {
  renderForm();
  expect(button('高级设置').getAttribute('aria-expanded')).toBe('false');
  expect(document.getElementById('advanced_settings').hidden).toBe(true);

  act(() => button('高级设置').click());
  expect(document.getElementById('connect_timeout').value).toBe('10');
  expect(document.getElementById('query_timeout').value).toBe('30');
  expect(document.getElementById('idle_timeout').value).toBe('30');
  expect(document.getElementById('read_only').getAttribute('aria-checked')).toBe('false');
  expect(document.querySelector('input[value="normal"]').checked).toBe(true);

  act(() => change('name', '本地数据库'));
  act(() => button('保存连接').click());
  await flush();

  expect(http.post).toHaveBeenCalledWith('/api/database/connection/', expect.objectContaining({
    connect_timeout: 10,
    query_timeout: 30,
    idle_timeout: 30,
    read_only: false,
    environment: 'normal',
  }));
});

test('submits the exact payload after changing every governance control', async () => {
  renderForm();
  act(() => button('高级设置').click());
  act(() => change('name', '生产只读库'));
  act(() => change('connect_timeout', '25'));
  act(() => change('query_timeout', '180'));
  act(() => change('idle_timeout', '0'));
  clickControl('read_only');
  clickControl(document.querySelector('input[value="production"]'));
  act(() => button('保存连接').click());
  await flush();

  expect(http.post).toHaveBeenCalledWith('/api/database/connection/', {
    type: 'mysql',
    name: '生产只读库',
    database: undefined,
    host: '127.0.0.1',
    port: 3306,
    username: undefined,
    password: undefined,
    use_ssl: false,
    connect_timeout: 25,
    query_timeout: 180,
    idle_timeout: 0,
    read_only: true,
    environment: 'production',
    id: undefined,
  });
});

test('shows saved governance values and supplies defaults for legacy records', () => {
  renderForm({
    id: 7,
    name: '生产分析库',
    type: 'clickhouse',
    host: 'db.example.com',
    port: 8123,
    connect_timeout: 20,
    query_timeout: 120,
    idle_timeout: 0,
    read_only: true,
    environment: 'production',
  });
  act(() => button('高级设置').click());
  expect(document.getElementById('connect_timeout').value).toBe('20');
  expect(document.getElementById('query_timeout').value).toBe('120');
  expect(document.getElementById('idle_timeout').value).toBe('0');
  expect(document.getElementById('read_only').getAttribute('aria-checked')).toBe('true');
  expect(document.querySelector('input[value="production"]').checked).toBe(true);

  act(() => {
    ReactDOM.render(
      <ConnectionForm
        record={{id: 8, name: '旧连接', type: 'mysql', host: 'db.example.com', port: 3306}}
        visible
        onClose={jest.fn()}
        onSaved={jest.fn()}/>,
      root,
    );
  });
  act(() => button('高级设置').click());
  expect(document.getElementById('connect_timeout').value).toBe('10');
  expect(document.getElementById('query_timeout').value).toBe('30');
  expect(document.getElementById('idle_timeout').value).toBe('30');
  expect(document.getElementById('read_only').getAttribute('aria-checked')).toBe('false');
  expect(document.querySelector('input[value="normal"]').checked).toBe(true);
});

test('saves an edited connection with echoed governance values through the real controls', async () => {
  renderForm({
    id: 7,
    name: '生产分析库',
    type: 'clickhouse',
    host: 'db.example.com',
    port: 8123,
    database: 'analytics',
    username: 'analyst',
    use_ssl: true,
    connect_timeout: 20,
    query_timeout: 120,
    idle_timeout: 15,
    read_only: true,
    environment: 'production',
  });
  act(() => button('高级设置').click());
  act(() => change('connect_timeout', '30'));
  act(() => change('query_timeout', '240'));
  act(() => change('idle_timeout', '45'));
  clickControl('read_only');
  clickControl(document.querySelector('input[value="normal"]'));
  act(() => button('保存连接').click());
  await flush();

  expect(http.post).toHaveBeenCalledWith('/api/database/connection/', {
    id: 7,
    name: '生产分析库',
    type: 'clickhouse',
    host: 'db.example.com',
    port: 8123,
    database: 'analytics',
    username: 'analyst',
    password: '',
    use_ssl: true,
    connect_timeout: 30,
    query_timeout: 240,
    idle_timeout: 45,
    read_only: false,
    environment: 'normal',
  });
});

test('keeps advanced validation active after the settings are collapsed again', async () => {
  renderForm();
  act(() => button('高级设置').click());
  act(() => change('connect_timeout', ''));
  act(() => button('高级设置').click());
  act(() => change('name', '越界连接'));
  act(() => button('保存连接').click());
  await flush();

  expect(http.post).not.toHaveBeenCalled();
});

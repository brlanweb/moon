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

function renderForm(record = {}) {
  act(() => {
    ReactDOM.render(
      <ConnectionForm record={record} visible onClose={jest.fn()} onSaved={jest.fn()}/>,
      root,
    );
  });
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

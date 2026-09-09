import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import {Router} from 'react-router-dom';
import {createMemoryHistory} from 'history';
import {Modal, message} from 'antd';
import {hasPermission, http} from 'libs';
import DockerConsole, {resolveSection} from './index';

jest.mock('libs', () => ({
  t: (text, ...values) => values.reduce((result, value) => result.replace('{}', value), text),
  hasPermission: jest.fn(() => true),
  http: {get: jest.fn(), post: jest.fn()}, X_TOKEN: 'test-token',
}));
jest.mock('components', () => ({
  ACEditor: ({value, onChange}) => <textarea aria-label="compose" value={value} onChange={event => onChange(event.target.value)}/>,
}));
jest.mock('antd', () => {
  const React = require('react');
  const actual = jest.requireActual('antd');
  const Select = ({value, onChange, options, children, placeholder, ...props}) => {
    const items = options || React.Children.toArray(children).map(child => ({value: child.props.value, label: child.props.children}));
    return <select aria-label={props['aria-label'] || placeholder} value={value === undefined ? '' : value}
                   onChange={event => onChange(items.find(item => String(item.value) === event.target.value)?.value)}>
      <option value="">{placeholder}</option>
      {items.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
    </select>;
  };
  Select.Option = () => null;
  return {...actual, Select};
});

const project = {
  name: 'web', workdir: '/opt/web', config_file: '/opt/web/compose.yaml',
  config_files: ['/opt/web/compose.yaml'],
  containers: [{name: 'web-app-1', service: 'app', image: 'nginx', state: 'running', ports: []}],
};
const standalone = [
  {name: 'independent', image: 'redis', state: 'running', ports: []},
  {name: 'old-container', image: 'redis', state: 'exited', ports: []},
];
let root;
let history;
let streams;
let confirm;
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

async function render(props = {}) {
  await act(async () => {
    ReactDOM.render(<Router history={history}><DockerConsole {...props}/></Router>, root);
    await flush();
  });
}
async function host(value = 1) {
  await act(async () => {
    Simulate.change(root.querySelector('select[aria-label="选择服务器"]'), {target: {value: String(value)}});
    await flush();
  });
}
async function click(text) {
  const button = Array.from(root.querySelectorAll('button')).find(item => item.textContent.includes(text));
  expect(button).toBeDefined();
  await act(async () => { Simulate.click(button); await flush(); });
}
async function confirmAction() {
  await act(async () => { await confirm.mock.calls[confirm.mock.calls.length - 1][0].onOk(); });
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  streams = [];
  window.matchMedia = () => ({matches: false, addListener() {}, removeListener() {}});
  global.EventSource = jest.fn(function(url) {
    this.url = url;
    this.close = jest.fn();
    streams.push(this);
  });
  history = createMemoryHistory({initialEntries: ['/docker/projects'], getUserConfirmation: (_, callback) => callback(false)});
  hasPermission.mockReturnValue(true);
  http.get.mockImplementation(url => Promise.resolve(url === '/api/host/' ? [
    {id: 1, name: 'node-a', hostname: '10.0.0.1'},
    {id: 2, name: 'node-b', hostname: '10.0.0.2'},
  ] : {content: 'services: {}'}));
  http.post.mockImplementation((url, body) => {
    if (url === '/api/docker/discover/') return Promise.resolve({projects: [project], standalone});
    if (url === '/api/docker/resource/' && body.action === 'list') {
      return Promise.resolve({items: [{id: `${body.kind}-id`, name: `${body.kind}-item`}]});
    }
    return Promise.resolve({output: 'log output'});
  });
  confirm = jest.spyOn(Modal, 'confirm').mockReturnValue({destroy: jest.fn()});
  jest.spyOn(message, 'success').mockImplementation(() => {});
  root = document.createElement('div');
  document.body.appendChild(root);
});
afterEach(() => {
  act(() => { ReactDOM.unmountComponentAtNode(root); message.destroy(); });
  root.remove();
  jest.restoreAllMocks();
  delete global.EventSource;
});

test.each([
  [undefined, '/docker', 'projects'], [undefined, '/docker/projects', 'projects'],
  [undefined, '/docker/images/', 'images'], [undefined, '/docker/networks', 'networks'],
  [undefined, '/docker/volumes', 'volumes'], ['images', '/docker/projects', 'images'],
  ['project', '', 'projects'], ['storage', '', 'volumes'], [undefined, '/docker/unknown', 'projects'],
])('resolves section %s and path %s to %s', (section, path, expected) => {
  expect(resolveSection(section, path)).toBe(expected);
});

test.each([
  ['images', '镜像管理'], ['networks', '网络管理'], ['volumes', '存储管理'],
])('%s opens its own resource first screen and preserves remove and prune', async (section, title) => {
  await render({section});
  expect(root.querySelector('h2').textContent).toContain(title);
  expect(root.textContent).toContain('请先选择服务器');
  expect(root.textContent).not.toContain('独立容器');
  expect(root.textContent).not.toContain('返回项目');
  expect(http.post).not.toHaveBeenCalled();
  await host();
  expect(root.textContent).toContain(`${section}-item`);
  expect(http.post).toHaveBeenCalledWith('/api/docker/resource/', {host_id: 1, kind: section, action: 'list'}, {timeout: 70000});
  expect(http.post.mock.calls.some(([url]) => url === '/api/docker/discover/')).toBe(false);
  expect(http.get.mock.calls.some(([url]) => url === '/api/docker/config/')).toBe(false);
  await act(async () => { Simulate.click(root.querySelector('tbody button')); });
  await confirmAction();
  expect(http.post).toHaveBeenCalledWith('/api/docker/resource/', {
    host_id: 1, kind: section, action: 'remove',
    target: section === 'images' ? `${section}-id` : `${section}-item`, force: section === 'images',
  }, {timeout: 320000});
  await click('清理未使用');
  await confirmAction();
  expect(http.post).toHaveBeenCalledWith('/api/docker/resource/', {host_id: 1, kind: section, action: 'prune'}, {timeout: 320000});
});

test('path props and React Router location props route without extra integration wrappers', async () => {
  await render({path: '/docker/images'});
  expect(root.querySelector('h2').textContent).toContain('镜像管理');
  await render({location: {pathname: '/docker/networks'}});
  expect(root.querySelector('h2').textContent).toContain('网络管理');
  await render({match: {path: '/docker/volumes'}});
  expect(root.querySelector('h2').textContent).toContain('存储管理');
});

test('switching resource section or host discards pending list results', async () => {
  let resolveImages;
  http.post.mockImplementation((url, body) => body.kind === 'images'
    ? new Promise(resolve => { resolveImages = resolve; })
    : Promise.resolve({items: [{id: String(body.host_id), name: `networks-host-${body.host_id}`}]}));
  await render({section: 'images'});
  await host();
  await render({section: 'networks'});
  await act(async () => { resolveImages({items: [{id: 'old', name: 'stale-image'}]}); await flush(); });
  expect(root.textContent).toContain('networks-host-1');
  expect(root.textContent).not.toContain('stale-image');
  await host(2);
  expect(root.textContent).toContain('networks-host-2');
  expect(root.textContent).not.toContain('networks-host-1');
});

test('resource deletion permissions and built-in network protection remain enforced', async () => {
  http.post.mockResolvedValue({items: [{id: 'builtin', name: 'bridge'}, {id: 'custom', name: 'custom'}]});
  await render({section: 'networks'});
  await host();
  const buttons = root.querySelectorAll('tbody button');
  expect(buttons[0].disabled).toBe(true);
  expect(buttons[1].disabled).toBe(false);
  hasPermission.mockReturnValue(false);
  await render({section: 'networks'});
  expect(root.querySelectorAll('tbody button')[1].disabled).toBe(true);
  expect(Array.from(root.querySelectorAll('button')).find(item => item.textContent.includes('清理未使用')).disabled).toBe(true);
});

test('project page retains compose actions, editor and standalone container operations', async () => {
  await render({section: 'projects'});
  expect(http.post).not.toHaveBeenCalled();
  await host();
  expect(root.textContent).toContain('web-app-1');
  expect(root.querySelector('textarea').value).toBe('services: {}');
  for (const label of ['拉取并发布', '全部重建', '重启项目', '停止项目']) await click(label);
  for (const action of ['publish', 'rebuild', 'restart', 'stop']) {
    expect(http.post).toHaveBeenCalledWith('/api/docker/action/', expect.objectContaining({action, host_id: 1, project: 'web'}), {timeout: 920000});
  }
  await click('独立容器');
  expect(root.textContent).toContain('independent');
  const row = Array.from(root.querySelectorAll('tbody tr')).find(item => item.textContent.includes('independent'));
  await act(async () => { Simulate.click(row.querySelectorAll('button')[0]); await flush(); });
  expect(http.post).toHaveBeenCalledWith('/api/docker/container/', expect.objectContaining({action: 'logs', name: 'independent'}), {timeout: 320000});
  expect(root.textContent).toContain('log output');
  await click('实时跟随');
  expect(streams.some(stream => stream.url.includes('/api/docker/logs/'))).toBe(true);
  await click('清理已停止');
  await confirmAction();
  expect(http.post).toHaveBeenCalledWith('/api/docker/container/', {host_id: 1, name: 'old-container', action: 'remove'}, {timeout: 320000});
  await render({section: 'images'});
  expect(streams.every(stream => stream.close.mock.calls.length > 0)).toBe(true);
  expect(root.textContent).not.toContain('独立容器');
});

test('project discovery completing after route change cannot load compose or revive streams', async () => {
  let finish;
  http.post.mockImplementation((url) => url === '/api/docker/discover/'
    ? new Promise(resolve => { finish = resolve; }) : Promise.resolve({items: []}));
  await render({section: 'projects'});
  await host();
  await render({section: 'volumes'});
  await act(async () => { finish({projects: [project], standalone}); await flush(); });
  expect(http.get.mock.calls.some(([url]) => url === '/api/docker/config/')).toBe(false);
  expect(streams).toHaveLength(0);
  expect(root.querySelector('h2').textContent).toContain('存储管理');
});

test('standalone containers remain reachable without any compose projects', async () => {
  http.post.mockResolvedValue({projects: [], standalone});
  await render({section: 'projects'});
  await host();
  await click('查看 2 个独立容器');
  expect(root.textContent).toContain('independent');
  expect(root.textContent).toContain('old-container');
  await click('返回项目');
  expect(root.textContent).toContain('该服务器没有 Compose 项目');
});

test('standalone start, stop, restart and delete keep their API contracts', async () => {
  await render({section: 'projects'});
  await host();
  await click('独立容器');
  const rowButtons = name => Array.from(root.querySelectorAll('tbody tr'))
    .find(item => item.textContent.includes(name)).querySelectorAll('button');
  await act(async () => { Simulate.click(rowButtons('old-container')[1]); await flush(); });
  expect(http.post).toHaveBeenCalledWith('/api/docker/container/', expect.objectContaining({name: 'old-container', action: 'start'}), {timeout: 320000});
  await act(async () => { Simulate.click(rowButtons('independent')[1]); });
  await confirmAction();
  await act(async () => { Simulate.click(rowButtons('independent')[2]); await flush(); });
  await act(async () => { Simulate.click(rowButtons('independent')[3]); });
  await confirmAction();
  for (const action of ['stop', 'restart', 'remove']) {
    expect(http.post).toHaveBeenCalledWith('/api/docker/container/', expect.objectContaining({name: 'independent', action}), {timeout: 320000});
  }
});

test('project creation remains available and deletion still calls compose removal', async () => {
  await render({section: 'projects'});
  await host();
  await act(async () => { Simulate.click(root.querySelector('button[title="新建项目"]')); });
  expect(document.querySelector('.ant-modal-title').textContent).toBe('新建项目');
  expect(document.querySelector('.ant-modal').textContent).toContain('保存并启动');
  await click('删除项目');
  await confirmAction();
  expect(http.post).toHaveBeenCalledWith('/api/docker/remove/', {
    host_id: 1, project: 'web', config_file: '/opt/web/compose.yaml', delete_files: false,
  }, {timeout: 620000});
});

test('unsaved compose changes block route navigation and can still be saved', async () => {
  await render();
  await host();
  await act(async () => { Simulate.change(root.querySelector('textarea'), {target: {value: 'services: {web: {}}'}}); });
  act(() => { history.push('/docker/images'); });
  expect(history.location.pathname).toBe('/docker/projects');
  await click('保存配置');
  expect(http.post).toHaveBeenCalledWith('/api/docker/config/', expect.objectContaining({content: 'services: {web: {}}'}));
  act(() => { history.push('/docker/images'); });
  expect(history.location.pathname).toBe('/docker/images');
});

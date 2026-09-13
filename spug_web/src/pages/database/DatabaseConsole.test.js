import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import {message} from 'antd';
import {http} from 'libs';
import DatabaseConsole from './index';


jest.mock('libs', () => ({
  hasPermission: permission => ['database.connection.view', 'database.query.do'].includes(permission),
  http: {get: jest.fn(), post: jest.fn(), delete: jest.fn()},
  includes: (values, search) => values.some(value => String(value).includes(search)),
  t: (text, value) => value === undefined ? text : text.replace('{}', value),
}));

jest.mock('antd', () => {
  const actual = jest.requireActual('antd');
  const ReactModule = require('react');
  const Dropdown = ({children, menu}) => ReactModule.createElement(
    'span',
    null,
    children,
    menu.items.map(item => ReactModule.createElement(
      'button',
      {
        className: 'ant-dropdown-menu-item',
        key: item.key,
        onClick: event => menu.onClick({key: item.key, domEvent: event}),
        type: 'button',
      },
      item.label,
    )),
  );
  return {...actual, Dropdown};
});

jest.mock('components', () => ({
  ACEditor: ({value, onChange}) => (
    <textarea aria-label="database-command" value={value || ''}
              onChange={event => onChange(event.target.value)}/>
  ),
  NotFound: () => <div>not found</div>,
}));

jest.mock('components/MoonBrand', () => () => <span>Moon</span>);

const CONNECTIONS = [
  {
    id: 1,
    name: '主库',
    type: 'mysql',
    type_alias: 'MySQL',
    host: 'db-primary',
    port: 3306,
    idle_timeout: 1,
  },
  {
    id: 2,
    name: '报表库',
    type: 'postgresql',
    type_alias: 'PostgreSQL',
    host: 'db-report',
    port: 5432,
    idle_timeout: 1,
  },
];

const METADATA = {
  groups: [{name: 'public', items: ['orders']}],
  truncated: false,
};

let root;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return {promise, resolve, reject};
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function findText(selector, text) {
  return Array.from(document.body.querySelectorAll(selector))
    .find(item => item.textContent.trim() === text || item.textContent.includes(text));
}

async function renderConsole(connections = CONNECTIONS) {
  http.get.mockImplementation(url => {
    if (url === '/api/database/connection/') return Promise.resolve(connections);
    if (url === '/api/database/metadata/') return Promise.resolve(METADATA);
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
  await act(async () => {
    ReactDOM.render(<DatabaseConsole/>, root);
  });
  await flush();
}

async function openConnection(name) {
  const title = findText('.ant-tree-title', name);
  await act(async () => {
    title.closest('.ant-tree-node-content-wrapper').click();
  });
  await flush();
}

async function openConnectionMenu(name) {
  const title = findText('.ant-tree-title', name);
  const trigger = title.querySelector('.anticon-more').closest('span');
  act(() => trigger.click());
  await flush();
  return title.querySelector('.ant-dropdown-menu-item');
}

async function disconnect(name) {
  const item = await openConnectionMenu(name);
  act(() => item.click());
  await flush();
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.useRealTimers();
  http.post.mockResolvedValue({});
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
});

test('offers disconnect without edit or delete permission and fully clears a loaded connection', async () => {
  await renderConsole();
  await openConnection('主库');
  await openConnection('报表库');

  expect(findText('.ant-tabs-tab', '报表库')).not.toBeUndefined();
  expect(Array.from(document.body.querySelectorAll('.ant-tree-title'))
    .filter(item => item.textContent.trim() === 'public')).toHaveLength(2);
  act(() => Simulate.change(document.querySelector('.ant-tabs-tabpane-active textarea'), {
    target: {value: 'SELECT * FROM audit_log;'},
  }));
  const disconnectItem = await openConnectionMenu('报表库');
  expect(disconnectItem).not.toBeNull();
  expect(document.body.textContent).not.toContain('编辑');
  expect(document.body.textContent).not.toContain('删除');
  act(() => disconnectItem.click());
  await flush();

  expect(findText('.ant-tabs-tab', '报表库')).toBeUndefined();
  expect(findText('.ant-tabs-tab-active', '主库')).not.toBeUndefined();
  expect(Array.from(document.body.querySelectorAll('.ant-tree-title'))
    .filter(item => item.textContent.trim() === 'public')).toHaveLength(1);

  await openConnection('报表库');
  expect(document.querySelector('.ant-tabs-tabpane-active textarea').value).toBe('SELECT version();');
  expect(http.get.mock.calls.filter(([url]) => url === '/api/database/metadata/')).toHaveLength(3);
});

test('closing a tab keeps metadata cached while disconnecting clears it', async () => {
  await renderConsole();
  await openConnection('主库');

  act(() => document.querySelector('.ant-tabs-tab-remove').click());
  await flush();
  await openConnection('主库');
  expect(http.get.mock.calls.filter(([url]) => url === '/api/database/metadata/')).toHaveLength(1);

  await disconnect('主库');
  await openConnection('主库');
  expect(http.get.mock.calls.filter(([url]) => url === '/api/database/metadata/')).toHaveLength(2);
});

test('manual disconnect invalidates pending metadata before a new explicit open', async () => {
  const staleRequest = deferred();
  const freshRequest = deferred();
  await renderConsole();
  http.get.mockImplementationOnce(() => Promise.resolve(METADATA))
    .mockImplementationOnce(() => staleRequest.promise)
    .mockImplementationOnce(() => freshRequest.promise);
  await openConnection('主库');

  act(() => findText('button', '刷新目录').click());
  await disconnect('主库');
  act(() => findText('.ant-tree-title', '主库').closest('.ant-tree-node-content-wrapper').click());

  await act(async () => {
    staleRequest.resolve({groups: [{name: 'stale', items: ['old_table']}], truncated: false});
    await Promise.resolve();
  });
  expect(findText('.ant-tabs-tab', '主库')).toBeUndefined();
  expect(findText('.ant-tree-title', 'stale')).toBeUndefined();

  await act(async () => {
    freshRequest.resolve({groups: [{name: 'fresh', items: ['new_table']}], truncated: false});
    await Promise.resolve();
  });
  await flush();
  expect(findText('.ant-tabs-tab', '主库')).not.toBeUndefined();
  expect(findText('.ant-tree-title', 'fresh')).not.toBeUndefined();
  expect(findText('.ant-tree-title', 'stale')).toBeUndefined();
});

test('automatic disconnect invalidates pending metadata response', async () => {
  jest.useFakeTimers();
  const now = jest.spyOn(Date, 'now').mockReturnValue(0);
  const pendingRequest = deferred();
  const info = jest.spyOn(message, 'info').mockImplementation(() => {});
  try {
    await renderConsole();
    http.get.mockImplementationOnce(() => Promise.resolve(METADATA))
      .mockImplementationOnce(() => pendingRequest.promise);
    await openConnection('主库');
    act(() => findText('button', '刷新目录').click());

    now.mockReturnValue(60000);
    act(() => jest.advanceTimersByTime(60000));
    await flush();
    expect(findText('.ant-tabs-tab', '主库')).toBeUndefined();
    expect(document.querySelector('.ant-spin-spinning')).toBeNull();

    await act(async () => {
      pendingRequest.resolve({groups: [{name: 'stale', items: ['old_table']}], truncated: false});
      await Promise.resolve();
    });
    expect(findText('.ant-tabs-tab', '主库')).toBeUndefined();
    expect(findText('.ant-tree-title', 'stale')).toBeUndefined();
  } finally {
    now.mockRestore();
    info.mockRestore();
  }
});

test('manual disconnect removes the connection from idle tracking', async () => {
  jest.useFakeTimers();
  const now = jest.spyOn(Date, 'now').mockReturnValue(0);
  const info = jest.spyOn(message, 'info').mockImplementation(() => {});
  try {
    await renderConsole();
    await openConnection('主库');
    await disconnect('主库');

    now.mockReturnValue(120000);
    act(() => jest.advanceTimersByTime(120000));
    await flush();

    expect(info).not.toHaveBeenCalled();
  } finally {
    now.mockRestore();
    info.mockRestore();
  }
});

test('disconnects an idle connection on the 15 second check and reports it', async () => {
  jest.useFakeTimers();
  const now = jest.spyOn(Date, 'now').mockReturnValue(0);
  const info = jest.spyOn(message, 'info').mockImplementation(() => {});
  try {
    await renderConsole();
    await openConnection('主库');

    now.mockReturnValue(60000);
    act(() => jest.advanceTimersByTime(60000));
    await flush();

    expect(findText('.ant-tabs-tab', '主库')).toBeUndefined();
    expect(info).toHaveBeenCalledWith('连接【主库】因空闲已断开');
  } finally {
    now.mockRestore();
    info.mockRestore();
  }
});

test('editing SQL refreshes activity before the idle check', async () => {
  jest.useFakeTimers();
  const now = jest.spyOn(Date, 'now').mockReturnValue(0);
  const info = jest.spyOn(message, 'info').mockImplementation(() => {});
  try {
    await renderConsole();
    await openConnection('主库');

    now.mockReturnValue(45000);
    act(() => jest.advanceTimersByTime(45000));
    act(() => Simulate.change(document.querySelector('textarea[aria-label="database-command"]'), {
      target: {value: 'SELECT 1;'},
    }));
    now.mockReturnValue(90000);
    act(() => jest.advanceTimersByTime(45000));
    await flush();

    expect(findText('.ant-tabs-tab', '主库')).not.toBeUndefined();
    expect(info).not.toHaveBeenCalled();
  } finally {
    now.mockRestore();
    info.mockRestore();
  }
});

test('switching tabs refreshes only the selected connection activity', async () => {
  jest.useFakeTimers();
  const now = jest.spyOn(Date, 'now').mockReturnValue(0);
  const info = jest.spyOn(message, 'info').mockImplementation(() => {});
  try {
    await renderConsole();
    await openConnection('主库');
    await openConnection('报表库');

    now.mockReturnValue(45000);
    act(() => findText('.ant-tabs-tab', '主库').click());
    now.mockReturnValue(90000);
    act(() => jest.advanceTimersByTime(45000));
    await flush();

    expect(findText('.ant-tabs-tab', '主库')).not.toBeUndefined();
    expect(findText('.ant-tabs-tab', '报表库')).toBeUndefined();
  } finally {
    now.mockRestore();
    info.mockRestore();
  }
});

test('closing the active tab refreshes the automatically selected neighbor', async () => {
  jest.useFakeTimers();
  const now = jest.spyOn(Date, 'now').mockReturnValue(0);
  const info = jest.spyOn(message, 'info').mockImplementation(() => {});
  try {
    await renderConsole();
    await openConnection('主库');
    await openConnection('报表库');

    now.mockReturnValue(45000);
    act(() => jest.advanceTimersByTime(45000));
    act(() => document.querySelector('.ant-tabs-tab-active .ant-tabs-tab-remove').click());
    await flush();

    now.mockReturnValue(90000);
    act(() => jest.advanceTimersByTime(45000));
    await flush();
    expect(findText('.ant-tabs-tab', '主库')).not.toBeUndefined();
  } finally {
    now.mockRestore();
    info.mockRestore();
  }
});

test('disconnecting the active tab refreshes the automatically selected neighbor', async () => {
  jest.useFakeTimers();
  const now = jest.spyOn(Date, 'now').mockReturnValue(0);
  const info = jest.spyOn(message, 'info').mockImplementation(() => {});
  try {
    await renderConsole();
    await openConnection('主库');
    await openConnection('报表库');

    now.mockReturnValue(45000);
    act(() => jest.advanceTimersByTime(45000));
    await disconnect('报表库');

    now.mockReturnValue(90000);
    act(() => jest.advanceTimersByTime(45000));
    await flush();
    expect(findText('.ant-tabs-tab', '主库')).not.toBeUndefined();
  } finally {
    now.mockRestore();
    info.mockRestore();
  }
});

test('clicking run refreshes query activity', async () => {
  jest.useFakeTimers();
  const now = jest.spyOn(Date, 'now').mockReturnValue(0);
  const info = jest.spyOn(message, 'info').mockImplementation(() => {});
  try {
    await renderConsole();
    await openConnection('主库');

    now.mockReturnValue(45000);
    act(() => findText('.ant-tabs-tabpane-active button', '运行').click());
    await flush();
    now.mockReturnValue(90000);
    act(() => jest.advanceTimersByTime(45000));
    await flush();

    expect(findText('.ant-tabs-tab', '主库')).not.toBeUndefined();
    expect(http.post).toHaveBeenCalledWith('/api/database/execute/', {
      id: 1,
      command: 'SELECT VERSION();',
    }, {timeout: 45000});
  } finally {
    now.mockRestore();
    info.mockRestore();
  }
});

test('idle timeout zero never disconnects automatically and cleans up the timer', async () => {
  jest.useFakeTimers();
  const clearIntervalSpy = jest.spyOn(global, 'clearInterval');
  const info = jest.spyOn(message, 'info').mockImplementation(() => {});
  try {
    await renderConsole([{...CONNECTIONS[0], idle_timeout: 0}]);
    await openConnection('主库');

    act(() => jest.advanceTimersByTime(24 * 60 * 60 * 1000));
    await flush();

    expect(findText('.ant-tabs-tab', '主库')).not.toBeUndefined();
    expect(info).not.toHaveBeenCalled();
    act(() => {
      ReactDOM.unmountComponentAtNode(root);
    });
    expect(clearIntervalSpy).toHaveBeenCalled();
  } finally {
    clearIntervalSpy.mockRestore();
    info.mockRestore();
  }
});

import React from 'react';
import {act} from 'react-dom/test-utils';
import ReactDOM from 'react-dom';
import http from 'libs/http';
import McpAdmin from './index';

jest.mock('libs/http');
jest.mock('components', () => ({
  AuthDiv: ({children, auth}) => <div data-auth={auth}>{children}</div>,
  AuthButton: props => <button>{props.children}</button>,
  Breadcrumb: ({children}) => <div>{children}</div>,
  TableCard: ({columns, dataSource, actions}) => <div>{actions}{dataSource.map(item => <div key={item.id}>{columns.map((column, index) => <span key={index}>{column.render ? column.render(item[column.dataIndex], item) : item[column.dataIndex]}</span>)}</div>)}</div>,
  Action: ({children}) => <div>{children}</div>,
}));

beforeAll(() => {
  const components = require('components');
  components.Breadcrumb.Item = ({children}) => <span>{children}</span>;
  components.Action.Button = ({danger, auth, icon, ...props}) => <button {...props}/>;
});

test('loads token and audit records under mcp permission', async () => {
  http.get
    .mockResolvedValueOnce({tokens: [{id: 1, name: 'CI', status: 'active', token_prefix: 'moon_abc', username: 'ops', host_ids: [2], expires_at: '2026-09-10T00:00:00'}], hosts: []})
    .mockResolvedValueOnce({records: [{id: 9, operation: 'list_servers', status: 'success', operator: 'ops', created_at: '2026-09-09T00:00:00'}], total: 1});
  const root = document.createElement('div');
  await act(async () => {
    ReactDOM.render(<McpAdmin/>, root);
  });
  await act(async () => {
    await new Promise(resolve => setImmediate(resolve));
  });
  expect(root.querySelector('[data-auth]').getAttribute('data-auth')).toBe('system.mcp.view');
  expect(root.textContent).toContain('CI');
  expect(root.textContent).toContain('操作日志');
  expect(http.get).toHaveBeenCalledWith('/api/mcp-admin/tokens/');
  expect(http.get).toHaveBeenCalledWith('/api/mcp-admin/logs/', {params: {
    page: 1, page_size: 20, status: undefined, operation: undefined, token_id: undefined,
  }});
});

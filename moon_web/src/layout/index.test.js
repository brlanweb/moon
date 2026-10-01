import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {Router} from 'react-router-dom';
import {createMemoryHistory} from 'history';
import ConsoleLayout from './index';

jest.mock('libs', () => ({hasPermission: () => true, t: text => text}));
jest.mock('components', () => ({NotFound: () => <div>Not found</div>}));
jest.mock('../routes', () => ({__esModule: true, default: [], getDefaultPath: () => '/host'}));
jest.mock('./PageTitle', () => () => null);
jest.mock('./Sider', () => ({collapsed}) => <aside data-collapsed={String(collapsed)}>Navigation</aside>);
jest.mock('./Header', () => ({collapsed, toggle}) => <button onClick={toggle} aria-expanded={!collapsed}>Toggle</button>);
jest.mock('antd', () => {
  const Layout = ({children}) => <section>{children}</section>;
  Layout.Content = ({children}) => <main>{children}</main>;
  return {Layout, Drawer: ({open, onClose, children}) => open ? <div role="dialog"><button onClick={onClose}>Close</button>{children}</div> : null};
});

let root, history, listener, media;
const originalMatchMedia = window.matchMedia;

beforeEach(() => {
  media = {
    matches: false,
    addEventListener: jest.fn((name, callback) => { listener = callback; }),
    removeEventListener: jest.fn(),
  };
  window.matchMedia = jest.fn(() => media);
  root = document.createElement('div');
  document.body.appendChild(root);
  history = createMemoryHistory({initialEntries: ['/host']});
});

afterEach(() => {
  act(() => { ReactDOM.unmountComponentAtNode(root); });
  expect(media.removeEventListener).toHaveBeenCalledWith('change', listener);
  root.remove();
  window.matchMedia = originalMatchMedia;
});

function render(mobile) {
  media.matches = mobile;
  act(() => { ReactDOM.render(<Router history={history}><ConsoleLayout/></Router>, root); });
}

function toggle() {
  act(() => { root.querySelector('button').click(); });
}

test('desktop navigation preserves its collapse control', () => {
  render(false);
  expect(root.querySelector('aside').dataset.collapsed).toBe('false');
  toggle();
  expect(root.querySelector('aside').dataset.collapsed).toBe('true');
  expect(root.querySelector('[role="dialog"]')).toBeNull();
});

test('mobile opens navigation in a drawer without a persistent sidebar', () => {
  render(true);
  expect(root.querySelector('aside')).toBeNull();
  toggle();
  expect(root.querySelector('[role="dialog"] aside')).not.toBeNull();
  expect(root.querySelector('main aside')).toBeNull();
  act(() => { root.querySelector('[role="dialog"] button').click(); });
  expect(root.querySelector('aside')).toBeNull();
});

test('selecting a route closes the mobile drawer', () => {
  render(true);
  toggle();
  act(() => { history.push('/monitor'); });
  expect(root.querySelector('[role="dialog"]')).toBeNull();
});

test('crossing the breakpoint closes the drawer and restores desktop navigation', () => {
  render(false);
  act(() => { listener({matches: true}); });
  expect(root.querySelector('aside')).toBeNull();
  toggle();
  act(() => { listener({matches: false}); });
  expect(root.querySelector('[role="dialog"]')).toBeNull();
  expect(root.querySelector('aside')).not.toBeNull();
  act(() => { listener({matches: true}); });
  expect(root.querySelector('aside')).toBeNull();
});

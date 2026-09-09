import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import {Modal, notification} from 'antd';
import Login from './index';
import {http} from 'libs';
import history from 'libs/history';

jest.mock('libs', () => ({
  t: (text, value) => text.replace('{}', value), langMode: 'zh', setLanguage: jest.fn(),
  http: {post: jest.fn()}, updatePermissions: jest.fn()
}));
jest.mock('libs/history', () => ({location: {}, push: jest.fn()}));
jest.mock('../../routes', () => ({getDefaultPath: () => '/home'}));
jest.mock('pages/config/environment/store', () => ({}));
jest.mock('pages/config/app/store', () => ({}));
jest.mock('pages/deploy/request/store', () => ({}));
jest.mock('pages/exec/task/store', () => ({}));
jest.mock('pages/host/store', () => ({}));

let root;
const flush = () => new Promise(resolve => setTimeout(resolve, 100));
async function fill(name, value) {
  await act(async () => {
    Simulate.change(root.querySelector(`input[name="${name}"]`), {target: {value}});
  });
}
async function submit() {
  await act(async () => {
    Simulate.submit(root.querySelector('form'));
    await flush();
  });
}
beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  history.location = {};
  window.matchMedia = () => ({matches: false, addListener() {}, removeListener() {}});
  root = document.createElement('div');
  document.body.appendChild(root);
  act(() => { ReactDOM.render(<Login/>, root); });
});
afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(root);
    Modal.destroyAll();
    notification.destroy();
  });
  root.remove();
});

test('login exposes Moon identity and accessible autofill fields', () => {
  expect(root.querySelector('img[alt="Moon"]')).not.toBeNull();
  expect(document.title).toContain('Moon');
  expect(root.querySelector('input[name="username"]').getAttribute('autocomplete')).toBe('username');
  expect(root.querySelector('input[name="password"]').getAttribute('autocomplete')).toBe('current-password');
});

test('empty credentials stay on the page with inline validation', async () => {
  await submit();
  expect(http.post).not.toHaveBeenCalled();
  expect(root.textContent).toContain('请输入账户');
  expect(root.querySelectorAll('.ant-form-item-has-error').length).toBe(2);
});

test('valid form submission stores the session and returns to the requested page', async () => {
  history.location = {state: {from: '/host'}};
  http.post.mockResolvedValue({id: 7, access_token: 'test-session', nickname: 'Operator', is_supper: false, permissions: [], has_real_ip: true});
  await fill('username', 'operator');
  await fill('password', 'test-password');
  await submit();
  expect(http.post).toHaveBeenCalledWith('/api/account/login/', {username: 'operator', password: 'test-password', type: 'default'});
  expect(localStorage.getItem('token')).toBe('test-session');
  expect(history.push).toHaveBeenCalledWith('/host');
});

test('missing real IP shows a non-blocking warning and logs in without confirmation', async () => {
  history.location = {state: {from: '/host'}};
  http.post.mockResolvedValue({id: 7, access_token: 'ip-warning-session', nickname: 'Operator', is_supper: false, permissions: [], has_real_ip: false});
  await fill('username', 'operator');
  await fill('password', 'test-password');
  await submit();
  expect(localStorage.getItem('token')).toBe('ip-warning-session');
  expect(history.push).toHaveBeenCalledWith('/host');
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  const warning = document.querySelector('.ant-notification-notice');
  expect(warning).not.toBeNull();
  expect(warning.textContent).toContain('未能获取到访问者的真实IP');
  expect(warning.querySelector('a[href="https://spug.cc/docs/practice/"]')).not.toBeNull();
  act(() => { ReactDOM.unmountComponentAtNode(root); });
  expect(document.querySelector('.ant-notification-notice')).not.toBeNull();
});

test('MFA displays a code field and submits the entered code', async () => {
  http.post.mockResolvedValueOnce({required_mfa: true, has_real_ip: false});
  await fill('username', 'operator');
  await fill('password', 'test-password');
  await submit();
  expect(root.querySelector('input[name="captcha"]')).not.toBeNull();
  expect(root.textContent).toContain('秒后重新获取');
  expect(localStorage.getItem('token')).toBeNull();
  expect(history.push).not.toHaveBeenCalled();
  expect(document.querySelector('.ant-notification-notice')).toBeNull();
  http.post.mockResolvedValueOnce({id: 7, access_token: 'mfa-session', nickname: 'Operator', is_supper: false, permissions: [], has_real_ip: true});
  await fill('captcha', '123456');
  await submit();
  expect(http.post).toHaveBeenLastCalledWith('/api/account/login/', {username: 'operator', password: 'test-password', captcha: '123456', type: 'default'});
  expect(localStorage.getItem('token')).toBe('mfa-session');
});

test('a rejected request enables retry without losing credentials', async () => {
  http.post.mockRejectedValue(new Error('Invalid credentials'));
  await fill('username', 'operator');
  await fill('password', 'test-password');
  await submit();
  expect(root.querySelector('.ant-btn-loading')).toBeNull();
  expect(root.querySelector('input[name="username"]').value).toBe('operator');
  expect(localStorage.getItem('token')).toBeNull();
});

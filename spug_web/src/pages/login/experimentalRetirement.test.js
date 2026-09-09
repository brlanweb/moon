import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import * as antd from 'antd';
import fs from 'fs';
import path from 'path';
import {transformSync} from '@babel/core';

// Exercise the experimental client's login logic with the installed test runtime.
const source = fs.readFileSync(path.resolve(__dirname, '../../../../spug_web2/src/pages/login/index.jsx'), 'utf8');
const {code} = transformSync(`import React from 'react';\n${source}`, {
  configFile: false, babelrc: false,
  presets: ['@babel/preset-react'], plugins: ['@babel/plugin-transform-modules-commonjs']
});
const http = {post: jest.fn()};
const app = {updateSession: jest.fn()};
const navigate = jest.fn();
const compiled = {exports: {}};
const icons = new Proxy({}, {get: () => () => null});
new Function('require', 'module', 'exports', code)((name) => {
  if (name === 'react') return React;
  if (name === 'antd') return antd;
  if (name === 'react-router-dom') return {useNavigate: () => navigate};
  if (name === 'react-icons/ai') return icons;
  if (name === '@/libs') return {http, app};
  if (name.endsWith('.css')) return {};
  if (name.endsWith('.png')) return 'test-logo';
  throw new Error(`Unexpected dependency: ${name}`);
}, compiled, compiled.exports);
const Login = compiled.exports.default;
let root;

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  window.matchMedia = () => ({matches: false, addListener() {}, removeListener() {}});
  jest.spyOn(antd.message, 'error').mockImplementation(() => {});
  root = document.createElement('div');
  document.body.appendChild(root);
  act(() => { ReactDOM.render(<Login/>, root); });
});
afterEach(() => {
  act(() => { ReactDOM.unmountComponentAtNode(root); });
  root.remove();
  jest.restoreAllMocks();
});
async function submit() {
  act(() => {
    Simulate.change(root.querySelector('input[placeholder="请输入账户"]'), {target: {value: 'operator'}});
    Simulate.change(root.querySelector('input[placeholder="请输入密码"]'), {target: {value: 'test-password'}});
  });
  await act(async () => {
    Simulate.click(root.querySelector('.ant-btn-primary'));
    await new Promise(resolve => setTimeout(resolve, 50));
  });
}

test('experimental login exposes neither directory nor code controls', () => {
  expect(root.textContent).not.toContain('LDAP');
  expect(root.textContent).not.toContain('获取验证码');
  expect(root.querySelector('input[placeholder="请输入验证码"]')).toBeNull();
});

test('experimental login submits only local credentials and clears stale directory preference', async () => {
  localStorage.setItem('login_type', 'ldap');
  const session = {access_token: 'test-session', has_real_ip: true};
  http.post.mockResolvedValueOnce(session);
  await submit();
  expect(http.post).toHaveBeenCalledWith('/api/account/login/', {
    username: 'operator', password: 'test-password', type: 'default'
  });
  expect(app.updateSession).toHaveBeenCalledWith(session);
  expect(localStorage.getItem('login_type')).toBeNull();
  expect(navigate).toHaveBeenCalledWith('/home', {replace: true});
});

test('experimental login refuses retired MFA response without creating a session', async () => {
  http.post.mockResolvedValueOnce({required_mfa: true, has_real_ip: false});
  await submit();
  expect(app.updateSession).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
  expect(antd.message.error).toHaveBeenCalled();
  expect(root.querySelector('.ant-btn-loading')).toBeNull();
  expect(root.querySelector('input[placeholder="请输入验证码"]')).toBeNull();
});

test('experimental login allows retry after authentication error', async () => {
  http.post.mockRejectedValueOnce(new Error('retired factor blocks login'));
  await submit();
  expect(app.updateSession).not.toHaveBeenCalled();
  expect(root.querySelector('.ant-btn-loading')).toBeNull();
});

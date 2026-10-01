import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import Agent from './index';
import store from './store';

jest.mock('mobx-react', () => ({observer: component => component}));
jest.mock('libs', () => ({t: x => x, hasPermission: () => true}));
jest.mock('./Metrics', () => props => <div data-metrics-inline={String(props.inline)}/>);
jest.mock('./store', () => ({
  sessions: [], sessionList: [], hosts: [], mode: 'chat', current: null,
  fetchSessions: jest.fn(), fetchHosts: jest.fn(), reset: jest.fn(),
  startNewSession: jest.fn(), removeSession: jest.fn(), send: jest.fn(), stop: jest.fn(),
}));
jest.mock('components', () => {
  const React = require('react');
  const Wrapper = ({children}) => React.createElement('div', null, children);
  Wrapper.Item = Wrapper;
  return {AuthDiv: Wrapper, Breadcrumb: Wrapper};
});
let root;
beforeEach(() => {
  jest.clearAllMocks();
  window.matchMedia = window.matchMedia || (() => ({matches: false, addListener() {}, removeListener() {}}));
  root = document.createElement('div');
  document.body.appendChild(root);
  store.current = {id: 1, title: 'Test conversation', records: []};
  store.sessions = [store.current];
  store.sessionList = store.sessions;
  store.mode = 'chat';
  store.hostId = undefined;
  store.sending = false;
  store.stopping = false;
  store.canStop = false;
  store.currentHost = null;
  store.stop.mockResolvedValue();
  store.pending = null;
  store.removeSession.mockReturnValue(new Promise(() => {}));
  store.send.mockReturnValue(new Promise(() => {}));
});
afterEach(() => {
  act(() => { ReactDOM.unmountComponentAtNode(root); });
  root.remove();
});
function render() { act(() => { ReactDOM.render(<Agent/>, root); }); }

test('chat mode hides the irrelevant server picker', () => {
  render();
  expect(root.querySelector('.ant-segmented')).not.toBeNull();
  expect(root.querySelector('[aria-label="目标服务器"]')).toBeNull();
  expect(root.querySelector('[aria-label="发送"]').disabled).toBe(true);
  store.mode = 'agent';
  render();
  expect(root.querySelector('[aria-label="目标服务器"]')).not.toBeNull();
});

test('deletion uses a local confirmation without a modal mask or waiting spinner', async () => {
  render();
  act(() => { Simulate.click(root.querySelector('[aria-label="删除对话 Test conversation"]')); });
  expect(document.querySelector('.ant-popover')).not.toBeNull();
  expect(document.querySelector('.ant-modal-mask')).toBeNull();
  const confirm = document.querySelector('.ant-popover .ant-btn-primary');
  await act(async () => { Simulate.click(confirm); });
  expect(store.removeSession).toHaveBeenCalledWith(1);
  expect(document.querySelector('.ant-popover .ant-btn-loading')).toBeNull();
});

test('Chinese IME confirmation does not send prematurely', () => {
  render();
  const input = root.querySelector('textarea');
  act(() => { Simulate.change(input, {target: {value: '检查服务'}}); });
  act(() => { Simulate.keyDown(input, {key: 'Enter', keyCode: 229, nativeEvent: {isComposing: true}}); });
  expect(store.send).not.toHaveBeenCalled();
  act(() => { Simulate.keyDown(input, {key: 'Enter', nativeEvent: {isComposing: false}}); });
  expect(store.send).toHaveBeenCalledWith('检查服务');
});

test('server metrics share the title header', () => {
  store.mode = 'agent';
  store.currentHost = {id: 7, name: 'server', hostname: 'localhost'};
  render();
  expect(root.querySelector('header [data-metrics-inline="true"]')).not.toBeNull();
});

test('streaming replaces send with a stop button', async () => {
  store.sending = store.canStop = true;
  render();
  const stop = root.querySelector('[aria-label="停止生成"]');
  expect(stop.disabled).toBe(false);
  expect(root.querySelector('[aria-label="发送"]')).toBeNull();
  await act(async () => { Simulate.click(stop); });
  expect(store.stop).toHaveBeenCalledTimes(1);
  store.stopping = true;
  render();
  expect(root.querySelector('[aria-label="停止生成"]').disabled).toBe(true);
});

test('approval blocks new messages and keeps the command confirmation visible', () => {
  store.pending = {command: 'systemctl restart service', reason: 'approval'};
  render();
  expect(root.querySelector('textarea').disabled).toBe(true);
  expect(root.textContent).toContain('需要你确认后才会执行');
  expect(root.querySelector('[aria-label="删除对话 Test conversation"]').disabled).toBe(true);
  expect(root.querySelector('.ant-segmented-disabled')).not.toBeNull();
});

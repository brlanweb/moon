import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import Step1 from './Step1';
import store from './store';
import {http} from 'libs';
import {Modal} from 'antd';
import {resourceDefaults} from './resource';

jest.mock('mobx-react', () => ({observer: component => component}));
jest.mock('./store', () => ({record: {}, groups: ['test'], page: 0}));
jest.mock('libs', () => ({t: text => text, http: {post: jest.fn()}, cleanCommand: v => v}));
jest.mock('../exec/task/TemplateSelector', () => () => null);
jest.mock('pages/host/Selector', () => () => null);
jest.mock('./DockerTarget', () => () => null);
jest.mock('components', () => ({LinkButton: () => null, ACEditor: () => null}));
jest.mock('antd', () => {
  const React = require('react');
  const Form = props => <div>{props.children}</div>;
  Form.Item = props => <label>{props.label}{props.children}</label>;
  const Input = props => <input value={typeof props.value === 'string' ? props.value : ''} onChange={props.onChange}/>;
  Input.TextArea = Input;
  const Select = props => <select value={props.value || ''} multiple={props.mode === 'tags'}
    onChange={e => props.onChange(e.target.value)}>{props.children}</select>;
  Select.Option = props => <option value={props.value}>{props.children}</option>;
  return {
    Form, Input, Select,
    InputNumber: props => <span><input aria-label={props['aria-label']} type="number" value={props.value == null ? '' : props.value}
      min={props.min} max={props.max} onChange={e => props.onChange(e.target.value === '' ? null : Number(e.target.value))}/>{props.addonAfter}</span>,
    Button: props => <button disabled={props.disabled} onClick={props.onClick}>{props.children}</button>,
    Modal: {success: jest.fn(), warning: jest.fn()}, message: {error: jest.fn()},
  };
});

let root;
const render = () => act(() => {ReactDOM.render(<Step1/>, root);});
const button = text => Array.from(root.querySelectorAll('button')).find(x => x.textContent === text);
const select = label => Array.from(root.querySelectorAll('label')).find(x => x.textContent.startsWith(label)).querySelector('select');
beforeEach(() => {
  root = document.createElement('div');
  document.body.appendChild(root);
  store.record = {type: '7', name: 'test', group: 'test', targets: [7, 8], extra: resourceDefaults()};
  store.page = 0;
  jest.clearAllMocks();
});
afterEach(() => {
  act(() => {ReactDOM.unmountComponentAtNode(root);});
  root.remove();
});

test('metric selection sets percentage and temperature defaults and optional disk mount', () => {
  render();
  expect(root.querySelector('[aria-label="资源阈值"]').value).toBe('80');
  act(() => Simulate.change(select('资源指标'), {target: {value: 'temperature'}}));
  render();
  expect(store.record.extra).toEqual(resourceDefaults('temperature'));
  expect(root.querySelector('[aria-label="资源阈值"]').max).toBe('250');
  expect(root.textContent).toContain('\u00b0C');
  act(() => Simulate.change(select('资源指标'), {target: {value: 'disk'}}));
  render();
  const mount = Array.from(root.querySelectorAll('label')).find(x => x.textContent.startsWith('磁盘挂载点')).querySelector('input');
  act(() => Simulate.change(mount, {target: {value: '/data'}}));
  expect(store.record.extra).toEqual({...resourceDefaults('disk'), mount: '/data'});
  act(() => Simulate.change(select('资源指标'), {target: {value: 'memory'}}));
  render();
  expect(store.record.extra).toEqual(resourceDefaults('memory'));
  expect(root.textContent).not.toContain('磁盘挂载点');
});

test('clearing the threshold disables next and test, while zero remains valid', () => {
  render();
  act(() => Simulate.change(root.querySelector('[aria-label="资源阈值"]'), {target: {value: ''}}));
  render();
  expect(button('下一步').disabled).toBe(true);
  expect(button('执行测试').disabled).toBe(true);
  act(() => Simulate.change(root.querySelector('[aria-label="资源阈值"]'), {target: {value: '0'}}));
  render();
  expect(button('下一步').disabled).toBe(false);
  act(() => Simulate.click(button('下一步')));
  expect(store.page).toBe(1);
});

test.each([true, false])('test keeps the existing request contract and renders success=%s', async is_success => {
  http.post.mockResolvedValue({is_success, message: 'result'});
  render();
  await act(async () => {Simulate.click(button('执行测试'));});
  expect(http.post).toHaveBeenCalledWith('/api/monitor/test/', {
    type: '7', targets: [7, 8], extra: resourceDefaults(),
  }, {timeout: 120000});
  expect(is_success ? Modal.success : Modal.warning).toHaveBeenCalledWith({content: 'result'});
  expect(root.textContent).toContain('仅测试第一台监控主机');
});

test('switching an existing monitor to resource clears targets and disables inherited AI repair', () => {
  store.record = {type: '6', name: 'test', group: 'test', targets: [7], extra: {}, ai_mode: 'repair'};
  render();
  act(() => Simulate.change(select('监控类型'), {target: {value: '7'}}));
  expect(store.record).toMatchObject({type: '7', targets: [], extra: resourceDefaults(), ai_mode: ''});
});

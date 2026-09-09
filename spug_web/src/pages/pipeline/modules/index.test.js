import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import ModuleConfig from './index';
import {NODES} from '../data';

jest.mock('libs', () => ({t: text => text}));
jest.mock('./SSHExec', () => () => null);
jest.mock('./Build', () => () => null);
jest.mock('./Parameter', () => () => null);
jest.mock('./DataUpload', () => () => null);
jest.mock('./DataTransfer', () => () => null);
jest.mock('./PushWebhook', () => props => <div data-channel={props.node.module}/>);

let root;
beforeEach(() => {root = document.createElement('div');});
afterEach(() => {act(() => {ReactDOM.unmountComponentAtNode(root);});});

test('retired push module is not selectable', () => {
  const modules = NODES.map(node => node.module);
  expect(modules).not.toContain('push_spug');
  expect(modules).toEqual(expect.arrayContaining(['push_dd', 'push_fs', 'push_wx']));
});

test('legacy nodes show a retired warning and clear the stale save handler', () => {
  const setHandler = jest.fn();
  act(() => {ReactDOM.render(<ModuleConfig node={{module: 'push_spug'}} setHandler={setHandler}/>, root);});
  expect(root.textContent).toContain('已移除或不受支持');
  expect(setHandler).toHaveBeenCalledWith(undefined);
});

test.each(['push_dd', 'push_fs', 'push_wx'])('direct channel %s keeps its editor', module => {
  act(() => {ReactDOM.render(<ModuleConfig node={{module}} setHandler={jest.fn()}/>, root);});
  expect(root.querySelector('[data-channel]').getAttribute('data-channel')).toBe(module);
});

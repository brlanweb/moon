import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import Step1 from './Step1';
import store from './store';

jest.mock('mobx-react', () => ({observer: component => component}));
jest.mock('./store', () => ({record: {}, groups: []}));
jest.mock('libs', () => ({t: text => text, http: {}, cleanCommand: v => v}));
jest.mock('../exec/task/TemplateSelector', () => () => null);
jest.mock('pages/host/Selector', () => () => null);
jest.mock('./DockerTarget', () => {
  const React = require('react');
  return props => React.createElement('span', {'data-docker-host': String(props.hostId)});
});
jest.mock('components', () => {
  const React = require('react');
  return {
    LinkButton: props => React.createElement('button', null, props.children),
    ACEditor: props => {
      if (typeof props.value !== 'string') throw new TypeError('Ace requires string');
      return React.createElement('textarea', {'data-script': true, value: props.value, readOnly: true});
    },
  };
});

let root;
beforeEach(() => {
  window.matchMedia = window.matchMedia || (() => ({matches: false, addListener() {}, removeListener() {}}));
  root = document.createElement('div');
  document.body.appendChild(root);
});
afterEach(() => {
  ReactDOM.unmountComponentAtNode(root);
  root.remove();
});

test('Docker container selection does not send an object to the script editor', () => {
  store.record = {type: '6', name: 'test', group: 'test', targets: [7], extra: null};
  act(() => ReactDOM.render(<Step1/>, root));
  store.record.extra = {version: 1, kind: 'standalone_container', container: 'worker'};
  act(() => ReactDOM.render(<Step1/>, root));
  expect(root.querySelector('[data-script]')).toBeNull();
  expect(root.querySelector('[data-docker-host]').getAttribute('data-docker-host')).toBe('7');
});

test('site monitor never mounts Docker discovery with its URL as a host ID', () => {
  store.record = {type: '1', name: 'test', group: 'test', targets: ['https://example.com'], extra: ''};
  act(() => ReactDOM.render(<Step1/>, root));
  expect(root.querySelector('[data-docker-host]')).toBeNull();
});

test('custom script monitor still mounts its text editor', () => {
  store.record = {type: '4', name: 'test', group: 'test', targets: [7], extra: 'exit 0'};
  act(() => ReactDOM.render(<Step1/>, root));
  expect(root.querySelector('[data-script]').value).toBe('exit 0');
});

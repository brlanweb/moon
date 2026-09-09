import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import MonitorIndex from './index';
import ResourceIndex from './ResourceIndex';
import store from './store';

jest.mock('mobx-react', () => ({observer: component => component}));
jest.mock('libs', () => ({t: text => text}));
jest.mock('./store', () => ({formVisible: false}));
jest.mock('./Form', () => () => null);
jest.mock('./Table', () => {
  const React = require('react');
  return ({resourceOnly}) => {
    const [initialScope] = React.useState(resourceOnly);
    return <div data-table={String(resourceOnly)} data-initial-scope={String(initialScope)}/>;
  };
});
jest.mock('./MonitorCard', () => {
  const React = require('react');
  return ({resourceOnly}) => <div data-overview={String(resourceOnly)}/>;
});
jest.mock('components', () => {
  const React = require('react');
  const Wrapper = props => <div>{props.children}</div>;
  const Breadcrumb = jest.requireActual('../../components/Breadcrumb').default;
  return {AuthDiv: Wrapper, Breadcrumb};
});

let root;
beforeEach(() => {
  root = document.createElement('div');
  store.formVisible = false;
});
afterEach(() => {act(() => {ReactDOM.unmountComponentAtNode(root);});});

test('ResourceIndex is a standalone resource-only entry', () => {
  act(() => {ReactDOM.render(<ResourceIndex/>, root);});
  expect(root.querySelector('[data-table]').dataset.table).toBe('true');
  expect(root.querySelector('[data-overview]').dataset.overview).toBe('true');
  expect(root.textContent).toContain('资源监控');
});

test('route fallback scopes both views and remounts cached table columns on navigation', () => {
  act(() => {ReactDOM.render(<MonitorIndex location={{pathname: '/monitor'}}/>, root);});
  expect(root.querySelector('[data-table]').dataset.table).toBe('false');
  expect(Array.from(root.querySelectorAll('.ant-breadcrumb-link'), item => item.textContent))
    .toEqual(['首页', '监控中心', '服务监控']);
  store.f_type = 'Site';
  act(() => {ReactDOM.render(<MonitorIndex location={{pathname: '/monitor/resource'}}/>, root);});
  expect(root.querySelector('[data-table]').dataset.initialScope).toBe('true');
  expect(root.querySelector('[data-overview]').dataset.overview).toBe('true');
  expect(store.f_type).toBeUndefined();
  act(() => {ReactDOM.render(<MonitorIndex location={{pathname: '/monitor'}}/>, root);});
  expect(root.querySelector('[data-table]').dataset.initialScope).toBe('false');
  expect(root.querySelector('[data-overview]').dataset.overview).toBe('false');
});

test('explicit resourceOnly prop overrides the pathname', () => {
  act(() => {ReactDOM.render(<MonitorIndex resourceOnly location={{pathname: '/monitor'}}/>, root);});
  expect(root.querySelector('[data-table]').dataset.table).toBe('true');
});

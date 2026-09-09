import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import Breadcrumb from './Breadcrumb';

let root;
beforeEach(() => {
  root = document.createElement('div');
  document.body.appendChild(root);
});
afterEach(() => {
  act(() => { ReactDOM.unmountComponentAtNode(root); });
  root.remove();
});
function render(children, props = {}) {
  act(() => {
    ReactDOM.render(<Breadcrumb extra={<button>Action</button>} {...props}>{children}</Breadcrumb>, root);
  });
}
function title() { return root.firstChild.lastChild.firstChild.textContent; }

test('ignores trailing false from a conditional breadcrumb', () => {
  render([
    <Breadcrumb.Item key="home">Home</Breadcrumb.Item>,
    <Breadcrumb.Item key="monitor">Monitoring</Breadcrumb.Item>,
    false,
  ]);
  expect(title()).toBe('Monitoring');
  expect(root.querySelectorAll('.ant-breadcrumb-link')).toHaveLength(2);
});

test.each([undefined, null, false, []])('accepts empty children (%p)', children => {
  render(children);
  expect(title()).toBe('');
});

test('normalizes nested arrays and ignores non-element placeholders', () => {
  render([
    [<Breadcrumb.Item key="home">Home</Breadcrumb.Item>, null],
    [false, <Breadcrumb.Item key="last">Last</Breadcrumb.Item>],
    undefined, 'placeholder', 0,
  ]);
  expect(title()).toBe('Last');
  expect(root.querySelectorAll('.ant-breadcrumb-link')).toHaveLength(2);
});

test('keeps an explicit title and a single linked breadcrumb', () => {
  render(<Breadcrumb.Item href="/monitor">Monitoring</Breadcrumb.Item>, {title: 'Custom'});
  expect(title()).toBe('Custom');
  expect(root.querySelector('a').getAttribute('href')).toBe('/monitor');
});

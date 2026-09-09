import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {Form} from 'antd';
import http from 'libs/http';
import CreateToken from './CreateToken';
import {showPlaintext} from './TokenTable';

jest.mock('libs/http', () => ({post: jest.fn()}));
jest.mock('./TokenTable', () => ({showPlaintext: jest.fn()}));
jest.mock('./store', () => ({hosts: [], createVisible: true, fetch: jest.fn(() => Promise.resolve())}));
jest.mock('antd', () => {
  const Form = ({children}) => <div>{children}</div>;
  Form.useForm = jest.fn();
  Form.Item = ({children}) => <div>{children}</div>;
  const Radio = {Group: ({children}) => <div>{children}</div>, Button: () => null};
  return {Form, Radio, Input: () => null, Select: () => null,
    Modal: ({onOk, children}) => <div><button onClick={onOk}>Create</button>{children}</div>,
    message: {success: jest.fn()}};
});

let root, validate;
beforeEach(() => {
  jest.clearAllMocks();
  validate = jest.fn();
  Form.useForm.mockReturnValue([{validateFields: validate}]);
  root = document.createElement('div');
  document.body.appendChild(root);
  act(() => { ReactDOM.render(<CreateToken/>, root); });
});
afterEach(() => {
  act(() => { ReactDOM.unmountComponentAtNode(root); });
  root.remove();
});

async function submit() {
  await act(async () => {
    root.querySelector('button').click();
    await new Promise(resolve => setImmediate(resolve));
  });
}

test('invalid form stays open without submitting or leaking a rejected promise', async () => {
  validate.mockRejectedValue({errorFields: [{name: ['name']}]});
  await submit();
  expect(http.post).not.toHaveBeenCalled();
  expect(showPlaintext).not.toHaveBeenCalled();
});

test('request rejection is handled without a second plaintext display', async () => {
  validate.mockResolvedValue({name: 'CI', days: 7, host_ids: [1]});
  http.post.mockRejectedValue(new Error('Synthetic request failure'));
  await submit();
  expect(http.post).toHaveBeenCalledTimes(1);
  expect(showPlaintext).not.toHaveBeenCalled();
});

test('completion after closing does not update an unmounted component', async () => {
  validate.mockResolvedValue({name: 'CI', days: 1, host_ids: [1]});
  let complete;
  http.post.mockReturnValue(new Promise(resolve => { complete = resolve; }));
  await submit();
  act(() => { ReactDOM.unmountComponentAtNode(root); });
  const error = jest.spyOn(console, 'error').mockImplementation(() => {});
  try {
    await act(async () => {
      complete({token: 'demo-once'});
      await new Promise(resolve => setImmediate(resolve));
    });
    expect(error).not.toHaveBeenCalled();
    expect(showPlaintext).toHaveBeenCalledTimes(1);
  } finally { error.mockRestore(); }
});

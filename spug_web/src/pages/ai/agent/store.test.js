import http from 'libs/http';
import fs from 'fs';
import path from 'path';
import {transformSync} from '@babel/core';

// CRA's Jest transformer does not inherit customize-cra's legacy decorators.
const source = fs.readFileSync(path.join(__dirname, 'store.js'), 'utf8');
const {code} = transformSync(source, {
  filename: 'store.js', babelrc: false, configFile: false,
  presets: ['babel-preset-react-app'],
  plugins: [['@babel/plugin-proposal-decorators', {legacy: true}]],
});
const storeModule = {exports: {}};
new Function('require', 'module', 'exports', code)(require, storeModule, storeModule.exports);
const {Store} = storeModule.exports;

jest.mock('libs/http', () => ({get: jest.fn(), post: jest.fn(), delete: jest.fn()}));
jest.mock('libs/functools', () => ({X_TOKEN: ''}));

function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return {promise, resolve, reject};
}
let store;
beforeEach(() => {
  jest.clearAllMocks();
  store = new Store();
  store.sessions = [{id: 1, title: 'one', status: 'idle'}, {id: 2, title: 'two', status: 'idle'}];
  store.current = {...store.sessions[0], records: []};
});

test('deletion immediately removes the row and clears current output', async () => {
  const request = deferred();
  http.delete.mockReturnValue(request.promise);
  store.streaming = 'old';
  const close = jest.fn();
  store.es = {close};
  const operation = store.removeSession(1);
  expect(store.sessions.map(x => x.id)).toEqual([2]);
  expect(store.current).toBeNull();
  expect(store.streaming).toBe('');
  expect(close).toHaveBeenCalledTimes(1);
  await store.removeSession(1);
  expect(http.delete).toHaveBeenCalledTimes(1);
  request.resolve();
  await operation;
});

test('failed deletion restores the row and selection without dropping new rows', async () => {
  const request = deferred();
  http.delete.mockReturnValue(request.promise);
  const operation = store.removeSession(1);
  store.sessions.push({id: 3});
  request.reject(new Error('offline'));
  await expect(operation).rejects.toThrow('offline');
  expect(store.sessions.map(x => x.id)).toEqual([1, 2, 3]);
  expect(store.current.id).toBe(1);
});

test('rollback never replaces a different conversation selected during deletion', async () => {
  const request = deferred();
  http.delete.mockReturnValue(request.promise);
  const operation = store.removeSession(1);
  http.get.mockResolvedValue({...store.sessions[0], records: []});
  await store.selectSession(store.sessions[0]);
  request.reject(new Error('offline'));
  await expect(operation).rejects.toThrow();
  expect(store.current.id).toBe(2);
});

test('deleting a different conversation leaves pending approval untouched', async () => {
  store.pending = {command: 'test'};
  http.delete.mockResolvedValue();
  await store.removeSession(2);
  expect(store.current.id).toBe(1);
  expect(store.pending.command).toBe('test');
});

test.each(['running', 'waiting'])('does not delete %s tasks', async status => {
  store.sessions[0].status = status;
  await store.removeSession(1);
  expect(http.delete).not.toHaveBeenCalled();
});

test('late detail response cannot resurrect a deleted conversation', async () => {
  const request = deferred();
  http.get.mockReturnValue(request.promise);
  http.delete.mockResolvedValue();
  const detail = store.fetchDetail(1);
  await store.removeSession(1);
  request.resolve({id: 1, records: []});
  expect(await detail).toBeNull();
  expect(store.current).toBeNull();
});

test('new conversation is a local draft and ignores late detail response', async () => {
  const request = deferred();
  http.get.mockReturnValue(request.promise);
  const detail = store.fetchDetail(1);
  store.mode = 'agent';
  store.hostId = 7;
  store.startNewSession();
  request.resolve({id: 1, mode: 'chat'});
  await detail;
  expect(http.post).not.toHaveBeenCalled();
  expect(store.current).toBeNull();
  expect(store.mode).toBe('agent');
  expect(store.hostId).toBe(7);
});

test('stop targets the active turn and keeps the stream until backend acknowledgement', async () => {
  store.current.turn = 4;
  store.sending = store.canStop = true;
  const close = jest.fn();
  store.es = {close};
  http.post.mockResolvedValue({stopping: true});
  await store.stop();
  await store.stop();
  expect(http.post).toHaveBeenCalledTimes(1);
  expect(http.post).toHaveBeenCalledWith('/api/ai/session/stop/', {id: 1, turn: 4});
  expect(store.stopping).toBe(true);
  expect(store.sending).toBe(true);
  expect(close).not.toHaveBeenCalled();
});

test('failed stop allows a retry without pretending generation has stopped', async () => {
  store.sending = store.canStop = true;
  http.post.mockRejectedValue(new Error('offline'));
  await expect(store.stop()).rejects.toThrow('offline');
  expect(store.stopping).toBe(false);
  expect(store.sending).toBe(true);
});

test('selection resolves safely when clicking the current session again', async () => {
  expect((await store.selectSession({id: 1})).id).toBe(1);
  expect(http.get).not.toHaveBeenCalled();
});

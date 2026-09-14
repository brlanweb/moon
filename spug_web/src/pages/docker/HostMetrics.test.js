import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {http} from 'libs';
import HostMetrics, {readMetricsCache} from './HostMetrics';

jest.mock('libs', () => ({http: {get: jest.fn()}, t: x => x}));
jest.mock('bizcharts', () => ({
  Chart: ({data, children}) => <div data-points={JSON.stringify(data)}>{children}</div>,
  Geom: () => null, Axis: () => null, Tooltip: () => null,
}));
let root;
let now;
const response = (host_id, cpu = 37) => ({host_id, server_time: now / 1000, sampled_at: now / 1000,
  history: [{ts: now / 1000, cpu, memory: 42, gpu: [], gpu_status: 'absent'}]});
const flush = async () => { for (let n = 0; n < 8; n++) await Promise.resolve(); };
const render = async id => act(async () => {ReactDOM.render(<HostMetrics hostId={id}/>, root); await flush();});
beforeEach(() => {
  jest.useFakeTimers();
  now = 100000000 + Math.random() * 100000;
  jest.spyOn(Date, 'now').mockImplementation(() => now);
  Object.defineProperty(document, 'hidden', {configurable: true, value: false});
  http.get.mockReset();
  root = document.createElement('div'); document.body.appendChild(root);
});
afterEach(() => {
  act(() => { ReactDOM.unmountComponentAtNode(root); }); root.remove();
  jest.restoreAllMocks(); jest.useRealTimers();
});

test('cache renders immediately on return, expires after 60s, no GPU is normal', async () => {
  http.get.mockResolvedValue(response(101));
  await render(101);
  expect(root.textContent).toContain('37%');
  expect(root.textContent).toContain('未检测到 GPU');
  act(() => { ReactDOM.unmountComponentAtNode(root); });
  http.get.mockImplementation(() => new Promise(() => {}));
  await render(101);
  expect(root.textContent).toContain('37%');
  now += 61000;
  act(() => jest.advanceTimersByTime(1000));
  expect(readMetricsCache(101)).toBeUndefined();
  expect(root.textContent).not.toContain('37%');
});

test('old host response cannot overwrite new host or populate its cache', async () => {
  let finish;
  http.get.mockImplementationOnce(() => new Promise(resolve => {finish = resolve;}));
  await render(102);
  http.get.mockResolvedValue(response(103, 88));
  await render(103);
  await act(async () => {finish(response(102, 12)); await flush();});
  expect(root.textContent).toContain('88%');
  expect(root.textContent).not.toContain('12%');
  expect(readMetricsCache(102)).toBeUndefined();
});

test('polling never overlaps and unmount clears timers', async () => {
  let finish;
  http.get.mockImplementation(() => new Promise(resolve => {finish = resolve;}));
  await render(104);
  act(() => jest.advanceTimersByTime(20000));
  expect(http.get).toHaveBeenCalledTimes(1);
  await act(async () => {finish(response(104)); await flush();});
  await act(async () => {jest.advanceTimersByTime(5000); await flush();});
  expect(http.get).toHaveBeenCalledTimes(2);
  act(() => { ReactDOM.unmountComponentAtNode(root); });
  await act(async () => {finish(response(104)); await flush();});
  expect(jest.getTimerCount()).toBe(0);
});

test('stale samples are labelled and missing values stay null', async () => {
  const data = response(106);
  data.history.unshift({...data.history[0], ts: data.sampled_at - 5, cpu: null});
  http.get.mockResolvedValue(data);
  await render(106);
  const cpu = JSON.parse(root.querySelector('[data-points]').getAttribute('data-points'));
  expect(cpu[0].value).toBeNull();
  now += 6000;
  act(() => jest.advanceTimersByTime(1000));
  expect(root.textContent).toContain('数据已过期');
});

test('hidden document pauses polling; returning refreshes', async () => {
  http.get.mockResolvedValue(response(105, null));
  await render(105);
  expect(root.textContent).toContain('采集中');
  Object.defineProperty(document, 'hidden', {configurable: true, value: true});
  act(() => { document.dispatchEvent(new Event('visibilitychange')); });
  act(() => jest.advanceTimersByTime(10000));
  expect(http.get).toHaveBeenCalledTimes(1);
  Object.defineProperty(document, 'hidden', {configurable: true, value: false});
  await act(async () => {document.dispatchEvent(new Event('visibilitychange')); await flush();});
  expect(http.get).toHaveBeenCalledTimes(2);
});

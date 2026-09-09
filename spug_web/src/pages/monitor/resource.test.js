import {resourceDefaults, validResource, resourceThreshold, resourceTargets} from './resource';

jest.mock('libs', () => ({t: text => text}));

test.each(['cpu', 'memory', 'disk', 'temperature'])('%s defaults match the resource API contract', metric => {
  const extra = resourceDefaults(metric);
  expect(extra).toEqual({metric, operator: 'gte', value: metric === 'temperature' ? 85 : 80, mount: ''});
  expect(validResource([1, 2], extra)).toBe(true);
});

test.each([null, undefined, NaN, Infinity, -Infinity, -1, 101, '80'])('rejects invalid percentage %s', value => {
  expect(validResource([1], {...resourceDefaults(), value})).toBeFalsy();
});

test.each([0, 100])('accepts percentage boundary %s', value => {
  expect(validResource([1], {...resourceDefaults(), value})).toBe(true);
});

test.each([0, 250])('accepts temperature boundary %s', value => {
  expect(validResource([1], {...resourceDefaults('temperature'), value})).toBe(true);
});

test('rejects invalid metrics, operators, mounts, temperatures and host IDs', () => {
  for (const targets of [[], [0], [-1], [1.5], ['1'], [Infinity], [true]]) {
    expect(validResource(targets, resourceDefaults())).toBeFalsy();
  }
  for (const extra of [null, {...resourceDefaults(), metric: 'load'}, {...resourceDefaults(), operator: 'gt'},
    {...resourceDefaults(), mount: 1}, {...resourceDefaults('temperature'), value: 251}]) {
    expect(validResource([1], extra)).toBeFalsy();
  }
});

test('formats threshold, optional disk mount, temperature unit and host names', () => {
  expect(resourceThreshold(resourceDefaults('cpu'))).toBe('CPU使用率 >= 80%');
  expect(resourceThreshold(resourceDefaults('disk'))).toBe('磁盘使用率 >= 80% (最高使用率)');
  expect(resourceThreshold({...resourceDefaults('disk'), mount: '/data'})).toBe('磁盘使用率 >= 80% (/data)');
  expect(resourceThreshold(resourceDefaults('temperature'))).toBe('温度 >= 85\u00b0C');
  expect(resourceTargets({targets: [1, 2], target_names: {'1': 'server(10.0.0.1)'}})).toBe('server(10.0.0.1), #2');
});

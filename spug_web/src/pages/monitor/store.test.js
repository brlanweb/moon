import fs from 'fs';
import path from 'path';
import {transformSync} from '@babel/core';

// Match the existing store tests: CRA Jest omits customize-cra's decorators.
const {code} = transformSync(fs.readFileSync(path.join(__dirname, 'store.js'), 'utf8'), {
  filename: 'store.js', babelrc: false, configFile: false,
  presets: ['babel-preset-react-app'],
  plugins: [['@babel/plugin-proposal-decorators', {legacy: true}]],
});
const storeModule = {exports: {}};
new Function('require', 'module', 'exports', code)(require, storeModule, storeModule.exports);
const store = storeModule.exports.default;

jest.mock('libs', () => ({t: text => text, http: {}, includes: (a, b) => a.includes(b)}));

beforeEach(() => {
  store.record = {};
  store.records = [
    {id: 1, name: 'site', type: '1', type_alias: 'Site', group: 'a', is_active: true},
    {id: 2, name: 'cpu', type: '7', type_alias: 'Resources', group: 'a', is_active: true},
    {id: 3, name: 'disk', type: '7', type_alias: 'Resources', group: 'b', is_active: false},
  ];
  store.overviews = [
    {id: '1_https://example.com', name: 'site', type: 'Site', group: 'a'},
    {id: '2_10', name: 'cpu', type: 'Resources', group: 'a'},
    {id: '2_11', name: 'cpu', type: 'Resources', group: 'a'},
    {id: '3_10', name: 'disk', type: 'Resources', group: 'b'},
  ];
  store.f_type = store.f_group = store.f_name = undefined;
  store.f_active = '';
});

test('resource and detection lists and overviews never overlap', () => {
  expect(store.recordsFor().map(x => x.id)).toEqual([1]);
  expect(store.recordsFor(true).map(x => x.id)).toEqual([2, 3]);
  expect(store.overviewsFor().map(x => x.id)).toEqual(['1_https://example.com']);
  expect(store.overviewsFor(true).map(x => x.id)).toEqual(['2_10', '2_11', '3_10']);
  expect(store.typesFor()).toEqual(['Site']);
  expect(store.typesFor(true)).toEqual(['Resources']);
});

test('overview waits for detection IDs rather than leaking resource entries', () => {
  store.records = [];
  expect(store.overviewsFor()).toEqual([]);
  expect(store.overviewsFor(true)).toEqual([]);
});

test('existing group, name, type and active filters still apply', () => {
  store.f_group = 'a';
  store.f_name = 'cpu';
  store.f_type = 'Resources';
  store.f_active = '1';
  expect(store.recordsFor(true).map(x => x.id)).toEqual([2]);
  expect(store.overviewsFor(true)).toHaveLength(2);
  expect(store.recordsFor()).toEqual([]);
});

test('resource creation defaults to CPU 80 percent with AI disabled', () => {
  store.record = {type: '6', targets: [1], ai_mode: 'repair'};
  store.showForm(undefined, true);
  expect(store.record).toMatchObject({type: '7', targets: [], ai_mode: '', extra: {metric: 'cpu', value: 80}});
  expect(store.page).toBe(0);
  expect(store.formVisible).toBe(true);
  store.showForm();
  expect(store.record).toEqual({type: '1', targets: []});
});

test('edit retains resource extra, targets and notification settings without mutating the row', () => {
  const record = {id: 2, type: '7', targets: [10, 11], extra: {metric: 'disk', operator: 'gte', value: 90, mount: '/data'},
    rate: 5, threshold: 2, quiet: 60, notify_grp: [1], notify_mode: ['4']};
  store.showForm(record, true);
  expect(store.record).toEqual(record);
  store.record.extra.value = 80;
  expect(record.extra.value).toBe(90);
});

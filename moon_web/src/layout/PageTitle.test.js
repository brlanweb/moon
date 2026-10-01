import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {Router} from 'react-router-dom';
import {createMemoryHistory} from 'history';
import PageTitle, {resolvePageTitle} from './PageTitle';

const routes = [
  {title: '容器管理', child: [{path: '/docker/projects', title: '项目管理'}, {path: '/docker/images', title: '镜像管理'}]},
  {path: '/host', title: '主机管理'},
  {title: '监控中心', child: [{path: '/monitor', title: '服务监控'}]},
  {title: '配置中心', child: [{path: '/config/setting/:type/:id'}]},
];

test('titles use the current leaf page and the Moon brand', () => {
  expect(resolvePageTitle(routes, '/docker/images')).toBe('镜像管理 | Moon');
  expect(resolvePageTitle(routes, '/config/setting/app/7')).toBe('配置中心 | Moon');
  expect(resolvePageTitle(routes, '/unknown')).toBeNull();
});

test('leaving a container page clears its title, including unknown routes', () => {
  const root = document.createElement('div');
  const history = createMemoryHistory({initialEntries: ['/docker/projects']});
  try {
    act(() => { ReactDOM.render(<Router history={history}><PageTitle routes={routes}/></Router>, root); });
    expect(document.title).toBe('项目管理 | Moon');
    act(() => { history.push('/host'); });
    expect(document.title).toBe('主机管理 | Moon');
    act(() => { history.push('/monitor'); });
    expect(document.title).toBe('服务监控 | Moon');
    act(() => { history.push('/unknown'); });
    expect(document.title).toBe('Moon');
  } finally {
    act(() => { ReactDOM.unmountComponentAtNode(root); });
  }
});

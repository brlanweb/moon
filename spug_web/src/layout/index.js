/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Switch, Route, Redirect, useLocation } from 'react-router-dom';
import { Layout, Drawer } from 'antd';
import { NotFound } from 'components';
import Sider from './Sider';
import Header from './Header';
import PageTitle from './PageTitle';
import routes, { getDefaultPath } from '../routes';
import { hasPermission, t } from 'libs';
import styles from './layout.module.less';

function initRoutes(Routes, routes) {
  for (let route of routes) {
    if (route.component) {
      if (!route.auth || hasPermission(route.auth)) {
        Routes.push(<Route exact key={route.path} path={route.path} component={route.component}/>)
      }
    } else if (route.child) {
      initRoutes(Routes, route.child)
    }
  }
}

export default function () {
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 768px)').matches);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [Routes, setRoutes] = useState([]);
  const {pathname} = useLocation();

  useEffect(() => {
    const query = window.matchMedia('(max-width: 768px)');
    const onChange = event => {
      setMobile(event.matches);
      setDrawerOpen(false);
    };
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  useEffect(() => { setDrawerOpen(false); }, [pathname]);

  useEffect(() => {
    const Routes = [];
    initRoutes(Routes, routes);
    setRoutes(Routes)
  }, [])

  return (
    <Layout>
      <PageTitle routes={routes}/>
      {mobile ? (
        <Drawer title={t('导航')} placement="left" width={208} open={drawerOpen}
                onClose={() => setDrawerOpen(false)} className={styles.mobileDrawer}
                bodyStyle={{padding: 0}}>
          <Sider collapsed={false}/>
        </Drawer>
      ) : <Sider collapsed={collapsed}/>}
      <Layout style={{height: '100vh', minWidth: 0}}>
        <Header collapsed={mobile ? !drawerOpen : collapsed}
                toggle={() => mobile ? setDrawerOpen(!drawerOpen) : setCollapsed(!collapsed)}/>
        <Layout.Content className={styles.content} id="spug-container">
          <Switch>
            <Redirect exact from="/home" to={getDefaultPath()}/>
            {Routes}
            <Route component={NotFound}/>
          </Switch>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}

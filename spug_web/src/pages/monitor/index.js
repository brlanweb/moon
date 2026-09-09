/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useEffect} from 'react';
import { observer } from 'mobx-react';
import { AuthDiv, Breadcrumb } from 'components';
import { t } from 'libs';
import ComTable from './Table';
import ComForm from './Form';
import MonitorCard from './MonitorCard';
import store from './store';

export default observer(function ({resourceOnly, location}) {
  const isResource = resourceOnly === undefined
    ? /^\/monitor\/resource\/?$/.test(location?.pathname || '')
    : resourceOnly;

  useEffect(() => {
    store.f_type = undefined;
    store.formVisible = false;
  }, [isResource]);

  return (
    <AuthDiv auth="monitor.monitor.view">
      <Breadcrumb>
        <Breadcrumb.Item>{t('首页')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('监控中心')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t(isResource ? '资源监控' : '服务监控')}</Breadcrumb.Item>
      </Breadcrumb>
      <MonitorCard key={`overview-${isResource}`} resourceOnly={isResource}/>
      <ComTable key={`table-${isResource}`} resourceOnly={isResource}/>
      {store.formVisible && <ComForm/>}
    </AuthDiv>
  )
})

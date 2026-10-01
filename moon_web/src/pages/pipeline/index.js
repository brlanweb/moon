import React from 'react';
import { observer } from 'mobx-react';
import { AuthDiv, Breadcrumb } from 'components';
import { t } from 'libs';
import Table from './Table';
import Console from './console';


function Index() {
  return (
    <AuthDiv auth="pipeline.pipeline.view">
        <Breadcrumb>
        <Breadcrumb.Item>{t('首页')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('流水线')}</Breadcrumb.Item>
      </Breadcrumb>
      <Table/>
      <Console/>
    </AuthDiv>
  )
}

export default observer(Index)

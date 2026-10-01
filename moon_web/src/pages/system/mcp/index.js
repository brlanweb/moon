import React, {useEffect} from 'react';
import {observer} from 'mobx-react';
import {Tabs} from 'antd';
import history from 'libs/history';
import {AuthDiv, Breadcrumb} from 'components';
import TokenTable from './TokenTable';
import AuditTable from './AuditTable';
import CreateToken from './CreateToken';
import store from './store';

export default observer(function McpAdmin() {
  useEffect(() => { store.fetch(); }, []);
  const initialTab = new URLSearchParams(history.location.search).get('tab') || 'tokens';
  return <AuthDiv auth="system.mcp.view">
    <Breadcrumb><Breadcrumb.Item>首页</Breadcrumb.Item><Breadcrumb.Item>系统管理</Breadcrumb.Item><Breadcrumb.Item>MCP 操作</Breadcrumb.Item></Breadcrumb>
    <Tabs defaultActiveKey={initialTab} items={[{key: 'tokens', label: '访问令牌', children: <TokenTable/>}, {key: 'logs', label: '操作日志', children: <AuditTable/>}]}/>
    {store.createVisible && <CreateToken/>}
  </AuthDiv>;
});

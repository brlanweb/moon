import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {Button, Descriptions, Drawer, Input, Select, Space, Tag} from 'antd';
import {EyeOutlined, SearchOutlined} from '@ant-design/icons';
import {TableCard} from 'components';
import store from './store';

export default observer(function AuditTable() {
  const [detail, setDetail] = useState();
  const refresh = () => { store.logPage = 1; return store.fetchLogs(); };
  const columns = [
    {title: '时间', dataIndex: 'created_at'}, {title: 'Token ID', dataIndex: 'token_id'},
    {title: '操作', dataIndex: 'operation'}, {title: '操作者', dataIndex: 'operator'},
    {title: 'IP', dataIndex: 'ip'}, {title: '目标主机', dataIndex: 'host_name'},
    {title: '状态', dataIndex: 'status', render: value => <Tag color={value === 'success' ? 'green' : 'red'}>{value}</Tag>},
    {title: '退出码', dataIndex: 'exit_code'}, {title: '耗时(ms)', dataIndex: 'duration_ms'},
    {title: '详情', render: (_, item) => <Button type="link" icon={<EyeOutlined/>} onClick={() => setDetail(item)}>查看</Button>},
  ];
  const actions = [<Space key="filters" wrap>
    <Input allowClear style={{width: 130}} placeholder="Token ID" value={store.logTokenId}
           onChange={event => store.logTokenId = event.target.value}/>
    <Select allowClear style={{width: 130}} placeholder="状态" value={store.logStatus} onChange={value => store.logStatus = value}
            options={['success', 'failed', 'rejected'].map(value => ({value, label: value}))}/>
    <Select allowClear style={{width: 180}} placeholder="操作" value={store.logOperation} onChange={value => store.logOperation = value}
            options={['authenticate', 'list_servers', 'check_connection', 'execute_script'].map(value => ({value, label: value}))}/>
    <Button icon={<SearchOutlined/>} onClick={refresh}>筛选</Button>
  </Space>];
  return <>
    <TableCard tKey="mcp-audit" rowKey="id" title="MCP 操作日志" loading={store.loading}
               dataSource={store.logs} columns={columns} actions={actions} onReload={store.fetchLogs}
               scroll={{x: 1200}} pagination={{current: store.logPage, pageSize: store.logPageSize,
                 total: store.logTotal, showSizeChanger: true,
                 onChange: (page, pageSize) => { store.logPage = page; store.logPageSize = pageSize; store.fetchLogs(); }}}/>
    <Drawer open={Boolean(detail)} width="min(720px, 100vw)" title="MCP 操作详情" onClose={() => setDetail(undefined)}>
      {detail && <><Descriptions column={2} bordered size="small">
        <Descriptions.Item label="Token ID">{detail.token_id || '-'}</Descriptions.Item>
        <Descriptions.Item label="操作者">{detail.operator || '-'}</Descriptions.Item>
        <Descriptions.Item label="状态">{detail.status}</Descriptions.Item>
        <Descriptions.Item label="退出码">{detail.exit_code === null ? '-' : detail.exit_code}</Descriptions.Item>
        <Descriptions.Item label="IP">{detail.ip || '-'}</Descriptions.Item>
        <Descriptions.Item label="主机">{detail.host_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="耗时">{detail.duration_ms} ms</Descriptions.Item>
        <Descriptions.Item label="失败原因">{detail.failure_reason || '-'}</Descriptions.Item>
      </Descriptions><h4>脱敏脚本</h4><pre style={{whiteSpace: 'pre-wrap', wordBreak: 'break-all'}}>{detail.script || '-'}</pre>
      <h4>输出</h4><pre style={{whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 360, overflow: 'auto'}}>{detail.output || '-'}</pre></>}
    </Drawer>
  </>;
});

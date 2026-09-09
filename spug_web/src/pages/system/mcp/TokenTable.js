import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {Form, Modal, Radio, Tag, message} from 'antd';
import {KeyOutlined, ReloadOutlined, StopOutlined} from '@ant-design/icons';
import {Action, AuthButton, TableCard} from 'components';
import http from 'libs/http';
import store from './store';

const statusMap = {
  active: ['green', '有效'], expired: ['orange', '已过期'], revoked: ['red', '已撤销']
};

export default observer(function TokenTable() {
  const [regenerateTarget, setRegenerateTarget] = useState();
  const [days, setDays] = useState(7);
  const [regenerating, setRegenerating] = useState(false);
  const revoke = item => Modal.confirm({
    title: '撤销令牌', content: `撤销后立即失效，确定撤销 ${item.name}？`,
    onOk: () => http.delete('/api/mcp-admin/tokens/', {params: {id: item.id}})
      .then(() => { message.success('令牌已撤销'); return store.fetchTokens(); })
  });
  const regenerate = async () => {
    if (regenerating) return;
    setRegenerating(true);
    try {
      const data = await http.post('/api/mcp-admin/tokens/regenerate/', {
        id: regenerateTarget.id, days
      });
      setRegenerateTarget(undefined);
      showPlaintext(data.token, '新令牌');
      await store.fetchTokens();
    } catch (_) {
      // The shared HTTP client displays request errors.
    } finally { setRegenerating(false); }
  };
  const columns = [
    {title: 'Token ID', dataIndex: 'id'}, {title: '名称', dataIndex: 'name'},
    {title: '操作者', dataIndex: 'username'}, {title: '标识', dataIndex: 'token_prefix'},
    {title: '状态', dataIndex: 'status', render: value => { const item = statusMap[value] || ['', value]; return <Tag color={item[0]}>{item[1]}</Tag>; }},
    {title: '到期时间', dataIndex: 'expires_at'},
    {title: '操作', render: (_, item) => <Action>
      <Action.Button auth="system.mcp.edit" onClick={() => { setDays(7); setRegenerateTarget(item); }}
                     disabled={item.status === 'revoked'} icon={<ReloadOutlined/>}>重新生成</Action.Button>
      <Action.Button auth="system.mcp.del" danger onClick={() => revoke(item)}
                     disabled={item.status !== 'active'} icon={<StopOutlined/>}>撤销</Action.Button>
    </Action>},
  ];
  return <>
    <TableCard tKey="mcp-token" rowKey="id" title="MCP 访问令牌" loading={store.loading}
               dataSource={store.tokens} columns={columns} onReload={store.fetchTokens} scroll={{x: 980}}
               actions={[<AuthButton key="create" auth="system.mcp.add" type="primary" icon={<KeyOutlined/>}
                                    onClick={() => store.createVisible = true}>创建令牌</AuthButton>]}/>
    <Modal open={Boolean(regenerateTarget)} title="重新生成令牌" okText="重新生成" confirmLoading={regenerating}
           cancelButtonProps={{disabled: regenerating}} maskClosable={!regenerating}
           onCancel={() => { if (!regenerating) setRegenerateTarget(undefined); }} onOk={regenerate}>
      <p>旧令牌会立即撤销，新令牌仅展示一次。</p>
      <Form.Item label="绝对有效期">
        <Radio.Group value={days} onChange={event => setDays(event.target.value)}>
          <Radio.Button value={1}>1 天</Radio.Button><Radio.Button value={7}>7 天</Radio.Button><Radio.Button value={30}>30 天</Radio.Button>
        </Radio.Group>
      </Form.Item>
    </Modal>
  </>;
});

export function showPlaintext(token, title = '令牌已创建') {
  Modal.info({title, width: 680, content: <><p>请立即保存，关闭后无法再次查看。</p><pre style={{whiteSpace: 'pre-wrap', wordBreak: 'break-all'}}>{token}</pre></>});
}

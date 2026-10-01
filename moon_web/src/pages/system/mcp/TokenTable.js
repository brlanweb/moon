import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {Form, Input, Modal, Radio, Tag, message} from 'antd';
import {DeleteOutlined, EditOutlined, KeyOutlined, ReloadOutlined} from '@ant-design/icons';
import {Action, AuthButton, TableCard} from 'components';
import http from 'libs/http';
import store from './store';
import {isSuperUser, levelOptions} from './level';

const levelMap = {super: ['red', '超管'], normal: ['blue', '普通']};

const statusMap = {
  active: ['green', '有效'], expired: ['orange', '已过期'], revoked: ['red', '已撤销']
};

export default observer(function TokenTable() {
  const [regenerateTarget, setRegenerateTarget] = useState();
  const [days, setDays] = useState(7);
  const [regenerating, setRegenerating] = useState(false);
  const [editTarget, setEditTarget] = useState();
  const [saving, setSaving] = useState(false);
  const [editForm] = Form.useForm();
  const isSuper = isSuperUser();
  const openEdit = item => setEditTarget(item);
  const saveEdit = async () => {
    if (saving) return;
    let values;
    try { values = await editForm.validateFields(); } catch (_) { return; }
    setSaving(true);
    try {
      await http.patch('/api/mcp-admin/tokens/', {id: editTarget.id, ...values});
      setEditTarget(undefined);
      message.success('令牌已更新');
      await store.fetchTokens();
    } catch (_) {
      // The shared HTTP client displays request errors.
    } finally { setSaving(false); }
  };
  const remove = item => Modal.confirm({
    title: '删除令牌', content: `删除后立即失效且无法恢复，确定删除 ${item.name}？`,
    onOk: () => http.delete('/api/mcp-admin/tokens/', {params: {id: item.id}})
      .then(() => { message.success('令牌已删除'); return store.fetchTokens(); })
  });
  const regenerate = async () => {
    if (regenerating) return;
    setRegenerating(true);
    try {
      const data = await http.post('/api/mcp-admin/tokens/regenerate/', {
        id: regenerateTarget.id, days
      });
      setRegenerateTarget(undefined);
      showPlaintext(data.token, '令牌已刷新');
      await store.fetchTokens();
    } catch (_) {
      // The shared HTTP client displays request errors.
    } finally { setRegenerating(false); }
  };
  const columns = [
    {title: 'Token ID', dataIndex: 'id'}, {title: '名称', dataIndex: 'name'},
    {title: '操作者', dataIndex: 'username'}, {title: '标识', dataIndex: 'token_prefix'},
    {title: '级别', dataIndex: 'level', render: value => { const item = levelMap[value] || levelMap.normal; return <Tag color={item[0]}>{item[1]}</Tag>; }},
    {title: '状态', dataIndex: 'status', render: value => { const item = statusMap[value] || ['', value]; return <Tag color={item[0]}>{item[1]}</Tag>; }},
    {title: '到期时间', dataIndex: 'expires_at'},
    {title: '操作', render: (_, item) => <Action>
      <Action.Button auth="system.mcp.edit" onClick={() => openEdit(item)}
                     disabled={item.status === 'revoked'} icon={<EditOutlined/>}>编辑</Action.Button>
      <Action.Button auth="system.mcp.edit" onClick={() => { setDays(7); setRegenerateTarget(item); }}
                     disabled={item.status === 'revoked'} icon={<ReloadOutlined/>}>刷新</Action.Button>
      <Action.Button auth="system.mcp.del" danger onClick={() => remove(item)}
                     icon={<DeleteOutlined/>}>删除</Action.Button>
    </Action>},
  ];
  return <>
    <TableCard tKey="mcp-token" rowKey="id" title="MCP 访问令牌" loading={store.loading}
               dataSource={store.tokens} columns={columns} onReload={store.fetchTokens} scroll={{x: 980}}
               actions={[<AuthButton key="create" auth="system.mcp.add" type="primary" icon={<KeyOutlined/>}
                                    onClick={() => store.createVisible = true}>创建令牌</AuthButton>]}/>
    <Modal open={Boolean(regenerateTarget)} title="刷新令牌" okText="刷新" confirmLoading={regenerating}
           cancelButtonProps={{disabled: regenerating}} maskClosable={!regenerating}
           onCancel={() => { if (!regenerating) setRegenerateTarget(undefined); }} onOk={regenerate}>
      <p>刷新后旧密钥立即失效，新密钥仅展示一次，令牌 ID 与审计记录保持不变。</p>
      <Form.Item label="绝对有效期">
        <Radio.Group value={days} onChange={event => setDays(event.target.value)}>
          <Radio.Button value={1}>1 天</Radio.Button><Radio.Button value={7}>7 天</Radio.Button><Radio.Button value={30}>30 天</Radio.Button><Radio.Button value={180}>6 个月</Radio.Button><Radio.Button value={365}>1 年</Radio.Button>
        </Radio.Group>
      </Form.Item>
    </Modal>
    {editTarget && <Modal open title="编辑令牌" okText="保存" confirmLoading={saving}
           cancelButtonProps={{disabled: saving}} maskClosable={!saving}
           onCancel={() => { if (!saving) setEditTarget(undefined); }} onOk={saveEdit}>
      <Form form={editForm} layout="vertical"
            initialValues={{name: editTarget.name, level: editTarget.level || 'normal'}}>
        <Form.Item name="name" label="名称" rules={[{required: true, message: '请输入名称'}]}><Input maxLength={100}/></Form.Item>
        <Form.Item name="level" label="Key 级别" rules={[{required: true}]}
                   extra={isSuper ? '修改即时生效，密钥与有效期不变。' : '仅超级管理员可授予超管 Key。'}>
          <Radio.Group options={levelOptions(isSuper)}/>
        </Form.Item>
      </Form>
    </Modal>}
  </>;
});

export function showPlaintext(token, title = '令牌已创建') {
  Modal.info({title, width: 680, content: <><p>请立即保存，关闭后无法再次查看。</p><pre style={{whiteSpace: 'pre-wrap', wordBreak: 'break-all'}}>{token}</pre></>});
}

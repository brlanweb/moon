import React, {useEffect, useRef, useState} from 'react';
import {observer} from 'mobx-react';
import {Form, Input, Modal, Radio, message} from 'antd';
import http from 'libs/http';
import store from './store';
import {isSuperUser, levelOptions} from './level';
import {showPlaintext} from './TokenTable';

export default observer(function CreateToken() {
  const [form] = Form.useForm();
  const isSuper = isSuperUser();
  const [loading, setLoading] = useState(false);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);
  const submit = async () => {
    let values;
    try { values = await form.validateFields(); }
    catch (_) { return; }
    if (!mounted.current) return;
    setLoading(true);
    try {
      const data = await http.post('/api/mcp-admin/tokens/', values);
      store.createVisible = false;
      message.success('令牌已创建');
      showPlaintext(data.token);
      await store.fetch();
    } catch (_) {
      // The shared HTTP client displays request errors.
    } finally { if (mounted.current) setLoading(false); }
  };
  return <Modal open title="创建 MCP 令牌" okText="创建" confirmLoading={loading}
                onCancel={() => store.createVisible = false} onOk={submit}>
    <Form form={form} layout="vertical" initialValues={{days: 7, level: 'normal'}}>
      <Form.Item name="name" label="名称" rules={[{required: true, message: '请输入名称'}]}><Input maxLength={100}/></Form.Item>
      <Form.Item name="days" label="绝对有效期" rules={[{required: true}]}><Radio.Group><Radio.Button value={1}>1 天</Radio.Button><Radio.Button value={7}>7 天</Radio.Button><Radio.Button value={30}>30 天</Radio.Button><Radio.Button value={180}>6 个月</Radio.Button><Radio.Button value={365}>1 年</Radio.Button></Radio.Group></Form.Item>
      <Form.Item name="level" label="Key 级别" rules={[{required: true}]}
                 extra={isSuper ? '超管 Key 不经任何命令拦截与目录限制，请仅授予可信 Agent。' : '仅超级管理员可创建超管 Key。'}>
        <Radio.Group options={levelOptions(isSuper)}/>
      </Form.Item>
      <p style={{color: '#888', margin: 0}}>令牌可访问 Moon 中全部已登记服务器（包括之后新增的服务器）。</p>
    </Form>
  </Modal>;
});

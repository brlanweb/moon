import React, {useEffect, useRef, useState} from 'react';
import {observer} from 'mobx-react';
import {Form, Input, Modal, Radio, Select, message} from 'antd';
import http from 'libs/http';
import store from './store';
import {showPlaintext} from './TokenTable';

export default observer(function CreateToken() {
  const [form] = Form.useForm();
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
    <Form form={form} layout="vertical" initialValues={{days: 7}}>
      <Form.Item name="name" label="名称" rules={[{required: true, message: '请输入名称'}]}><Input maxLength={100}/></Form.Item>
      <Form.Item name="days" label="绝对有效期" rules={[{required: true}]}><Radio.Group><Radio.Button value={1}>1 天</Radio.Button><Radio.Button value={7}>7 天</Radio.Button><Radio.Button value={30}>30 天</Radio.Button></Radio.Group></Form.Item>
      <Form.Item name="host_ids" label="授权服务器" rules={[{required: true, message: '请至少选择一台服务器'}]}>
        <Select mode="multiple" optionFilterProp="label" options={store.hosts.map(item => ({value: item.id, label: `${item.name} (${item.hostname})`}))}/>
      </Form.Item>
    </Form>
  </Modal>;
});

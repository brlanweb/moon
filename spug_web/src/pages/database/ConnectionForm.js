import React, { useEffect, useState } from 'react';
import {
  Button,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Row,
  Switch,
  message,
} from 'antd';
import {
  CheckCircleFilled,
  CloseCircleFilled,
  DatabaseOutlined,
  DownOutlined,
  ImportOutlined,
  LinkOutlined,
  RightOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import { http, t } from 'libs';
import {parseConnectionUri} from './connectionUri';
import styles from './index.module.less';


const PORTS = {
  mysql: 3306,
  mariadb: 3306,
  postgresql: 5432,
  clickhouse: 8123,
  redis: 6379,
};

const TYPES = [
  {value: 'mysql', label: 'MySQL'},
  {value: 'mariadb', label: 'MariaDB'},
  {value: 'postgresql', label: 'PostgreSQL'},
  {value: 'clickhouse', label: 'ClickHouse'},
  {value: 'redis', label: 'Redis'},
];

const GOVERNANCE_DEFAULTS = {
  connect_timeout: 10,
  query_timeout: 30,
  idle_timeout: 30,
  read_only: false,
  environment: 'normal',
};

function initialValues(record) {
  const values = record.id ? {...record, password: ''} : {
    type: 'mysql', host: '127.0.0.1', port: 3306, use_ssl: false,
  };
  Object.entries(GOVERNANCE_DEFAULTS).forEach(([key, fallback]) => {
    if (values[key] == null) values[key] = fallback;
  });
  return values;
}

export default function ConnectionForm({record, visible, onClose, onSaved}) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testState, setTestState] = useState();
  const [uriVisible, setUriVisible] = useState(false);
  const [connectionUri, setConnectionUri] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    setUriVisible(false);
    setConnectionUri('');
    if (visible) {
      setTestState(undefined);
      setAdvancedOpen(false);
      form.resetFields();
      form.setFieldsValue(initialValues(record));
    }
  }, [form, record, visible]);

  function payload() {
    return {...form.getFieldsValue(true), id: record.id};
  }

  function validate() {
    return form.validateFields().then(payload);
  }

  function handleTypeChange(type) {
    setTestState(undefined);
    form.setFieldsValue({port: PORTS[type], database: type === 'redis' ? '0' : ''});
  }

  function clearConnectionUri() {
    setConnectionUri('');
    setUriVisible(false);
  }

  function handleUriToggle() {
    if (uriVisible) {
      clearConnectionUri();
    } else {
      setUriVisible(true);
    }
  }

  function handleClose() {
    clearConnectionUri();
    onClose();
  }

  function handleUriImport() {
    try {
      form.setFieldsValue(parseConnectionUri(connectionUri));
      setTestState(undefined);
      clearConnectionUri();
      message.success(t('连接 URI 已导入'));
    } catch (error) {
      message.error(t(error.message));
    }
  }

  function handleTest() {
    validate().then(data => {
      setTesting(true);
      setTestState(undefined);
      http.post('/api/database/connection/check/', data)
        .then(res => {
          setTestState({success: true, elapsed: res.elapsed});
          message.success(t('连接成功'));
        }, () => setTestState({success: false}))
        .finally(() => setTesting(false));
    }, () => {});
  }

  function handleSave() {
    validate().then(data => {
      setSaving(true);
      http.post('/api/database/connection/', data)
        .then(() => {
          message.success(t('保存成功'));
          onSaved();
        })
        .finally(() => setSaving(false));
    }, () => {});
  }

  const title = (
    <div className={styles.modalTitle}>
      <span className={styles.modalTitleIcon}><DatabaseOutlined/></span>
      <div>
        <div>{record.id ? t('编辑数据库连接') : t('新建数据库连接')}</div>
        <span>{record.id ? record.name : t('配置连接参数')}</span>
      </div>
    </div>
  );

  const footer = (
    <div className={styles.modalFooter}>
      <div className={styles.testState}>
        {testState?.success && (
          <span className={styles.testSuccess}><CheckCircleFilled/> {t('连接正常')} · {testState.elapsed} ms</span>
        )}
        {testState && !testState.success && (
          <span className={styles.testError}><CloseCircleFilled/> {t('连接失败')}</span>
        )}
      </div>
      <div>
        <Button onClick={handleClose}>{t('取消')}</Button>
        <Button icon={<LinkOutlined/>} loading={testing} onClick={handleTest}>{t('测试连接')}</Button>
        <Button type="primary" icon={<SaveOutlined/>} loading={saving} onClick={handleSave}>{t('保存连接')}</Button>
      </div>
    </div>
  );

  return (
    <Modal
      open={visible}
      className={styles.connectionModal}
      title={title}
      width={760}
      maskClosable={false}
      centered
      onCancel={handleClose}
      footer={footer}>
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        onValuesChange={() => setTestState(undefined)}>
        <div className={styles.importSection}>
          <Button type="link" size="small" icon={<ImportOutlined/>}
                  onClick={handleUriToggle}>
            {t('导入连接 URI')}
          </Button>
          {uriVisible && (
            <div className={styles.uriImport}>
              <Input.Password
                id="connection_uri"
                value={connectionUri}
                autoComplete="off"
                placeholder="postgresql://user:password@host:5432/database"
                onChange={event => setConnectionUri(event.target.value)}
                onPressEnter={handleUriImport}/>
              <Button type="primary" ghost onClick={handleUriImport}>{t('解析并填充')}</Button>
            </div>
          )}
        </div>

        <div className={styles.formSection}>
          <div className={styles.formSectionTitle}>{t('数据库类型')}</div>
          <Form.Item name="type" rules={[{required: true}]}>
            <Radio.Group className={styles.typeSelector} onChange={event => handleTypeChange(event.target.value)}>
              {TYPES.map(item => (
                <Radio.Button key={item.value} value={item.value}>{item.label}</Radio.Button>
              ))}
            </Radio.Group>
          </Form.Item>
        </div>

        <div className={styles.formSection}>
          <div className={styles.formSectionTitle}>{t('连接信息')}</div>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="name" label={t('连接名称')}
                         rules={[{required: true, message: t('请输入连接名称')}]}>
                <Input maxLength={64} placeholder={t('例如：生产库')}/>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item noStyle shouldUpdate={(prev, next) => prev.type !== next.type}>
                {({getFieldValue}) => getFieldValue('type') === 'redis' ? (
                  <Form.Item name="database" label={t('数据库编号')}>
                    <Input placeholder="0"/>
                  </Form.Item>
                ) : (
                  <Form.Item name="database" label={t('默认数据库')}>
                    <Input placeholder={t('可选')}/>
                  </Form.Item>
                )}
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item name="host" label={t('主机地址')}
                         rules={[{required: true, message: t('请输入主机地址')}]}>
                <Input placeholder="127.0.0.1"/>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="port" label={t('端口')}
                         rules={[{required: true, message: t('请输入端口')}]}>
                <InputNumber min={1} max={65535} style={{width: '100%'}}/>
              </Form.Item>
            </Col>
          </Row>
        </div>

        <div className={styles.formSection}>
          <div className={styles.formSectionTitle}>{t('认证与安全')}</div>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="username" label={t('用户名')}>
                <Input autoComplete="off" placeholder={t('可选')}/>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="password" label={t('密码')}>
                <Input.Password autoComplete="new-password"
                                placeholder={record.id ? t('留空则保持原密码') : t('可选')}/>
              </Form.Item>
            </Col>
            <Col span={24}>
              <div className={styles.sslRow}>
                <div>
                  <strong>SSL/TLS</strong>
                  <span>{t('使用加密连接')}</span>
                </div>
                <Form.Item name="use_ssl" valuePropName="checked" noStyle>
                  <Switch/>
                </Form.Item>
              </div>
            </Col>
          </Row>
        </div>

        <div className={styles.advancedSection}>
          <Button type="text" className={styles.advancedToggle}
                  aria-expanded={advancedOpen}
                  aria-controls="advanced_settings"
                  icon={advancedOpen ? <DownOutlined/> : <RightOutlined/>}
                  onClick={() => setAdvancedOpen(current => !current)}>
            {t('高级设置')}
          </Button>
          <div id="advanced_settings" className={styles.advancedContent} hidden={!advancedOpen}>
            <Row gutter={16}>
              <Col span={8}>
                <Form.Item name="connect_timeout" label={t('连接超时（秒）')}
                           rules={[{required: true, type: 'number', min: 1, max: 120}]}>
                  <InputNumber min={1} max={120} style={{width: '100%'}}/>
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="query_timeout" label={t('查询超时（秒）')}
                           rules={[{required: true, type: 'number', min: 1, max: 3600}]}>
                  <InputNumber min={1} max={3600} style={{width: '100%'}}/>
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="idle_timeout" label={t('空闲超时（分钟，0 禁用）')}
                           rules={[{required: true, type: 'number', min: 0, max: 1440}]}>
                  <InputNumber min={0} max={1440} style={{width: '100%'}}/>
                </Form.Item>
              </Col>
              <Col span={12}>
                <div className={styles.settingRow}>
                  <div>
                    <strong>{t('只读连接')}</strong>
                    <span>{t('限制为只读查询')}</span>
                  </div>
                  <Form.Item name="read_only" valuePropName="checked" noStyle>
                    <Switch/>
                  </Form.Item>
                </div>
              </Col>
              <Col span={12}>
                <Form.Item name="environment" label={t('运行环境')}>
                  <Radio.Group className={styles.environmentSelector}>
                    <Radio.Button value="normal">{t('普通')}</Radio.Button>
                    <Radio.Button value="production">{t('生产')}</Radio.Button>
                  </Radio.Group>
                </Form.Item>
              </Col>
            </Row>
          </div>
        </div>
      </Form>
    </Modal>
  );
}

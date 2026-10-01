import React, { useEffect, useState } from 'react';
import { Modal, Form, Radio, Input, Alert, message } from 'antd';
import { buildRepoUrl, parseRepoUrl } from './repoAuth';
import { http, t } from 'libs';

function Repo(props) {
  const [form] = Form.useForm()
  const [key, setKey] = useState()

  useEffect(() => {
    http.post('/api/app/kit/key/', {key: 'public_key'})
      .then(res => setKey(res))
    form.setFieldsValue(parseRepoUrl(props.url))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleSubmit() {
    try {
      props.onOk(buildRepoUrl(form.getFieldsValue()))
    } catch (error) {
      return message.error(t(error.message))
    }
    props.onCancel()
  }

  function copyToClipBoard() {
    const el = document.createElement('input');
    el.value = key;
    document.body.appendChild(el);
    el.select();
    document.execCommand('copy');
    el.remove();
    message.success(t('已复制'))
  }

  return (
    <Modal
      open
      maskClosable={false}
      title={t('设置Git仓库')}
      onCancel={props.onCancel}
      onOk={handleSubmit}>
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item label={t('认证类型')} name="type" initialValue="token">
          <Radio.Group>
            <Radio.Button value="token">GitHub Token</Radio.Button>
            <Radio.Button value="password">{t('账户密码')}</Radio.Button>
            <Radio.Button value="key">{t('密钥')}</Radio.Button>
          </Radio.Group>
        </Form.Item>
        <Form.Item required label={t('仓库地址')} name="url">
          <Input placeholder={t('请输入')}/>
        </Form.Item>

        <Form.Item noStyle shouldUpdate>
          {({getFieldValue}) =>
            getFieldValue('type') === 'token' ? (
              <React.Fragment>
                <Alert type="info" showIcon message={t('GitHub不支持Git账户密码认证，请使用PAT访问令牌。细粒度令牌需选择目标仓库并授予Contents只读权限；组织仓库可能需要审批或SSO授权。')} style={{marginBottom: 16}}/>
                <Form.Item required label="Token (PAT)" name="token">
                  <Input.Password autoComplete="new-password" placeholder="github_pat_… / ghp_…"/>
                </Form.Item>
              </React.Fragment>
            ) : getFieldValue('type') === 'password' ? (
              <React.Fragment>
                <Form.Item required label={t('账户')} name="username">
                  <Input placeholder={t('请输入')}/>
                </Form.Item>
                <Form.Item required label={t('密码')} name="password" extra={t('GitHub请在此填写PAT而非登录密码，或切换到GitHub Token。')}>
                  <Input.Password autoComplete="new-password" placeholder={t('请输入')}/>
                </Form.Item>
              </React.Fragment>
            ) : (
              <Form.Item label={t('密钥')} extra={(
                <span>
                  {t('将Moon公钥添加到GitHub仓库Settings → Deploy keys（只读），仓库地址使用git@github.com:组织/仓库.git。不要在这里粘贴私钥。')}<br/>
                  {t('请复制该密钥，以Gitee为例可参考')}
                  <a target="_blank" rel="noopener noreferrer" href="https://gitee.com/help/articles/4191">{t('Gitee文档')}</a>
                  {t('进行后续配置。')}
              </span>
              )}>
                <span className="btn" onClick={copyToClipBoard}>{t('点击复制密钥')}</span>
              </Form.Item>
            )
          }
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default Repo

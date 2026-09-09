/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import {useState} from 'react';
import {useNavigate} from 'react-router-dom'
import {Form, Input, Button, Modal, message} from 'antd';
import {AiOutlineUser, AiOutlineLock, AiOutlineCopyright, AiOutlineGithub} from 'react-icons/ai'
import styles from './login.module.css';
import {http, app} from '@/libs';
import logo from '@/assets/spug-default.png';

export default function Login() {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  function handleSubmit() {
    const formData = form.getFieldsValue(['username', 'password']);
    setLoading(true);
    formData['type'] = 'default';
    http.post('/api/account/login/', formData)
      .then(data => {
        if (!data || !data.access_token) {
          setLoading(false);
          return message.error('登录响应不兼容，请刷新页面或联系管理员');
        }
        if (!data['has_real_ip']) {
          Modal.warning({
            title: '安全警告',
            className: styles.tips,
            content: <div>
              未能获取到访问者的真实IP，无法提供基于请求来源IP的合法性验证，详细信息请参考
              <a target="_blank"
                 href="https://spug.cc/docs/practice/"
                 rel="noopener noreferrer">官方文档</a>。
            </div>,
            onOk: () => doLogin(data)
          })
        } else {
          doLogin(data)
        }
      }, () => setLoading(false))
  }

  function doLogin(data) {
    localStorage.removeItem('login_type');
    app.updateSession(data)
    navigate('/home', {replace: true})
  }


  return (
    <div className={styles.container}>
      <div className={styles.titleContainer}>
        <div><img className={styles.logo} src={logo} alt="logo"/></div>
        <div className={styles.desc}>灵活、强大、易用的开源运维平台</div>
      </div>
      <div className={styles.formContainer}>
        <Form form={form}>
          <Form.Item name="username" className={styles.formItem}>
            <Input
              size="large"
              autoComplete="off"
              placeholder="请输入账户"
              prefix={<AiOutlineUser className={styles.icon}/>}/>
          </Form.Item>
          <Form.Item name="password" className={styles.formItem}>
            <Input.Password
              size="large"
              autoComplete="off"
              placeholder="请输入密码"
              onPressEnter={handleSubmit}
              prefix={<AiOutlineLock className={styles.icon}/>}/>
          </Form.Item>
        </Form>

        <Button
          block
          size="large"
          type="primary"
          className={styles.button}
          loading={loading}
          onClick={handleSubmit}>登录</Button>
      </div>

      <div className={styles.footerZone}>
        <div className={styles.linksZone}>
          <a className={styles.links} title="官网" href="https://spug.cc" target="_blank"
             rel="noopener noreferrer">官网</a>
          <a className={styles.links} title="Github" href="https://github.com/openspug/spug" target="_blank"
             rel="noopener noreferrer"><AiOutlineGithub/></a>
          <a title="文档" href="https://spug.cc/docs/about-spug/" target="_blank"
             rel="noopener noreferrer">文档</a>
        </div>
        <div style={{color: 'rgba(0, 0, 0, .45)'}}>Copyright <AiOutlineCopyright/> {new Date().getFullYear()} By OpenSpug
        </div>
      </div>
    </div>
  )
}

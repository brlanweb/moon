/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useState, useEffect, useRef} from 'react';
import {Form, Input, Button, Tabs, notification, Dropdown} from 'antd';
import {UserOutlined, LockOutlined, MailOutlined, GlobalOutlined, ArrowRightOutlined, GithubOutlined} from '@ant-design/icons';
import styles from './login.module.css';
import MoonBrand from 'components/MoonBrand';
import history from 'libs/history';
import {http, updatePermissions, t, langMode, setLanguage} from 'libs';
import envStore from 'pages/config/environment/store';
import appStore from 'pages/config/app/store';
import requestStore from 'pages/deploy/request/store';
import execStore from 'pages/exec/task/store';
import hostStore from 'pages/host/store';
import {getDefaultPath} from '../../routes';

export default function Login() {
  const [form] = Form.useForm();
  const [counter, setCounter] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loginType, setLoginType] = useState(() => localStorage.getItem('login_type') === 'ldap' ? 'ldap' : 'default');
  const [codeVisible, setCodeVisible] = useState(false);
  const [codeLoading, setCodeLoading] = useState(false);
  const busy = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    document.title = `${t('登录')} | Moon`;
    envStore.records = [];
    appStore.records = [];
    requestStore.records = [];
    requestStore.deploys = [];
    hostStore.rawRecords = [];
    execStore.hosts = [];
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!counter) return;
    const timer = setTimeout(() => setCounter(value => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [counter]);

  function doLogin(data) {
    localStorage.setItem('id', data.id);
    localStorage.setItem('token', data.access_token);
    localStorage.setItem('nickname', data.nickname);
    localStorage.setItem('is_supper', data.is_supper);
    localStorage.setItem('permissions', JSON.stringify(data.permissions));
    localStorage.setItem('login_type', loginType);
    updatePermissions();
    history.push(history.location.state && history.location.state.from ? history.location.state.from : getDefaultPath());
  }

  async function handleSubmit(values) {
    if (busy.current) return;
    busy.current = true;
    setLoading(true);
    try {
      const payload = {username: values.username, password: values.password, type: loginType};
      if (codeVisible) payload.captcha = values.captcha;
      const data = await http.post('/api/account/login/', payload);
      if (!mounted.current) return;
      if (data.required_mfa) {
        setCodeVisible(true);
        setCounter(30);
      } else {
        if (!data.has_real_ip) {
          notification.warning({
            key: 'login-real-ip-warning',
            message: t('安全警告'),
            description: <div>
              {t('未能获取到访问者的真实IP，无法提供基于请求来源IP的合法性验证，详细信息请参考')}
              <a target="_blank" href="https://spug.cc/docs/practice/" rel="noopener noreferrer">{t('上游文档')}</a>。
            </div>,
            duration: 6
          });
        }
        doLogin(data);
      }
    } catch (_) {
      // The shared HTTP client displays server and network errors.
    } finally {
      busy.current = false;
      if (mounted.current) setLoading(false);
    }
  }

  async function handleCaptcha() {
    if (busy.current || counter > 0) return;
    try {
      const values = await form.validateFields(['username', 'password']);
      if (busy.current) return;
      busy.current = true;
      setCodeLoading(true);
      await http.post('/api/account/login/', {...values, type: loginType});
      if (mounted.current) setCounter(30);
    } catch (_) {
      // Validation is inline; network errors are handled by the HTTP client.
    } finally {
      busy.current = false;
      if (mounted.current) setCodeLoading(false);
    }
  }

  function resetChallenge() {
    setCodeVisible(false);
    setCounter(0);
    form.setFieldsValue({captcha: undefined});
  }

  const languageMenu = {
    selectedKeys: [langMode],
    items: [
      {key: 'zh', label: '简体中文', onClick: () => setLanguage('zh')},
      {key: 'en', label: 'English', onClick: () => setLanguage('en')}
    ]
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <MoonBrand/>
        <Dropdown menu={languageMenu} placement="bottomRight" trigger={['click']}>
          <button className={styles.language} type="button" aria-label={t('切换语言')}>
            <GlobalOutlined/><span>{langMode === 'zh' ? '简体中文' : 'English'}</span>
          </button>
        </Dropdown>
      </header>
      <main className={styles.main}>
        <section className={styles.visual} aria-label="Moon">
          <div className={styles.visualHeading}>
            <div className={styles.kicker}>MOON / OPERATIONS</div>
            <h2>Moon<span className={styles.titleDot}>.</span></h2>
            <p>{t('运维控制台')}</p>
          </div>
          <img className={styles.moon} src={`${process.env.PUBLIC_URL || ''}/moon-surface.jpg`} alt=""/>
          <div className={styles.visualFooter}><span>01 / MOON</span><span>{t('统一运维 · 有序掌控')}</span></div>
        </section>
        <section className={styles.formSection} aria-labelledby="login-heading">
          <div className={styles.formContainer}>
            <div className={styles.formEyebrow}><span/> MOON CONSOLE</div>
            <h1 id="login-heading">{t('欢迎回来')}</h1>
            <p className={styles.desc}>{t('登录 Moon 运维控制台')}</p>
            <Tabs activeKey={loginType} className={styles.tabs}
              onChange={value => {setLoginType(value); resetChallenge();}}
              items={[
                {key: 'default', label: t('普通登录'), disabled: loading || codeLoading},
                {key: 'ldap', label: t('LDAP登录'), disabled: loading || codeLoading}
              ]}/>
            <Form form={form} layout="vertical" onFinish={handleSubmit} requiredMark={false}
              onValuesChange={changed => {if (codeVisible && ('username' in changed || 'password' in changed)) resetChallenge();}}>
              <Form.Item name="username" label={t('账户')} className={styles.formItem}
                rules={[{required: true, whitespace: true, message: t('请输入账户')}] }>
                <Input name="username" size="large" autoComplete="username" spellCheck={false}
                  disabled={loading || codeLoading} placeholder={t('请输入账户')}
                  prefix={<UserOutlined className={styles.icon}/>}/>
              </Form.Item>
              <Form.Item name="password" label={t('密码')} className={styles.formItem}
                rules={[{required: true, message: t('请输入密码')}] }>
                <Input.Password name="password" size="large" autoComplete="current-password"
                  disabled={loading || codeLoading} placeholder={t('请输入密码')}
                  prefix={<LockOutlined className={styles.icon}/>}/>
              </Form.Item>
              {codeVisible && <div className={styles.challenge} aria-live="polite">
                <div className={styles.challengeTitle}>{t('身份验证')}</div>
                <div className={styles.codeRow}>
                  <Form.Item name="captcha" label={t('验证码')} className={styles.codeField} preserve={false}
                    rules={[{required: true, whitespace: true, message: t('请输入验证码')}] }>
                    <Input name="captcha" size="large" autoComplete="one-time-code" inputMode="numeric"
                      disabled={loading || codeLoading} placeholder={t('请输入验证码')}
                      prefix={<MailOutlined className={styles.icon}/>}/>
                  </Form.Item>
                  <Button className={styles.codeButton} htmlType="button" disabled={counter > 0 || loading}
                    loading={codeLoading} onClick={handleCaptcha}>
                    {counter > 0 ? t('{} 秒后重新获取', counter) : t('获取验证码')}
                  </Button>
                </div>
              </div>}
              <Button block size="large" type="primary" htmlType="submit" className={styles.button}
                loading={loading} disabled={codeLoading}>
                {t('登录控制台')}<ArrowRightOutlined/>
              </Button>
            </Form>
            <div className={styles.formFoot}><LockOutlined/>{t('账户身份验证')}</div>
          </div>
        </section>
      </main>
      <footer className={styles.footer}>
        <span>Moon <span className={styles.footerYear}>/ {new Date().getFullYear()}</span><span className={styles.attribution}>Copyright &copy; {new Date().getFullYear()} OpenSpug</span></span>
        <div className={styles.links}>
          <a href="https://github.com/openspug/spug" target="_blank" rel="noopener noreferrer"><GithubOutlined/>{t('上游源码')}</a>
          <a href="https://spug.cc/docs/about-spug/" target="_blank" rel="noopener noreferrer">{t('上游文档')}<ArrowRightOutlined/></a>
        </div>
      </footer>
    </div>
  );
}

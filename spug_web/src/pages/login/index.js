/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useState, useEffect, useRef} from 'react';
import {Form, Input, Button, notification, Dropdown} from 'antd';
import {UserOutlined, LockOutlined, GlobalOutlined, ArrowRightOutlined, GithubOutlined} from '@ant-design/icons';
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
  const [loading, setLoading] = useState(false);
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

  function doLogin(data) {
    localStorage.setItem('id', data.id);
    localStorage.setItem('token', data.access_token);
    localStorage.setItem('nickname', data.nickname);
    localStorage.setItem('is_supper', data.is_supper);
    localStorage.setItem('permissions', JSON.stringify(data.permissions));
    localStorage.removeItem('login_type');
    updatePermissions();
    history.push(history.location.state && history.location.state.from ? history.location.state.from : getDefaultPath());
  }

  async function handleSubmit(values) {
    if (busy.current) return;
    busy.current = true;
    setLoading(true);
    try {
      const payload = {username: values.username, password: values.password, type: 'default'};
      const data = await http.post('/api/account/login/', payload);
      if (!mounted.current) return;
      if (!data.access_token) {
        notification.error({message: t('登录服务不兼容，请联系管理员完成升级')});
        return;
      }
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
    } catch (_) {
      // The shared HTTP client displays server and network errors.
    } finally {
      busy.current = false;
      if (mounted.current) setLoading(false);
    }
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
            <Form form={form} layout="vertical" onFinish={handleSubmit} requiredMark={false}>
              <Form.Item name="username" label={t('账户')} className={styles.formItem}
                rules={[{required: true, whitespace: true, message: t('请输入账户')}] }>
                <Input name="username" size="large" autoComplete="username" spellCheck={false}
                  disabled={loading} placeholder={t('请输入账户')}
                  prefix={<UserOutlined className={styles.icon}/>}/>
              </Form.Item>
              <Form.Item name="password" label={t('密码')} className={styles.formItem}
                rules={[{required: true, message: t('请输入密码')}] }>
                <Input.Password name="password" size="large" autoComplete="current-password"
                  disabled={loading} placeholder={t('请输入密码')}
                  prefix={<LockOutlined className={styles.icon}/>}/>
              </Form.Item>
              <Button block size="large" type="primary" htmlType="submit" className={styles.button}
                loading={loading}>
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
          <a href="https://github.com/brlanweb/moon" target="_blank" rel="noopener noreferrer"><GithubOutlined/>{t('项目源码')}</a>
          <a href="https://spug.cc/docs/about-spug/" target="_blank" rel="noopener noreferrer">{t('上游文档')}<ArrowRightOutlined/></a>
        </div>
      </footer>
    </div>
  );
}

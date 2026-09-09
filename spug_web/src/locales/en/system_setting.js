/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
const dict = {
  // Menu / shared
  '首页': 'Home',
  '安全设置': 'Security Settings',
  '密钥设置': 'SSH Key Settings',
  '报警服务设置': 'Alert Service Settings',
  '开放服务设置': 'Open Service Settings',
  '关于': 'About',
  '保存设置': 'Save Settings',
  '确认': 'Confirm',
  '设置成功': 'Saved successfully',

  // AlarmSetting.js
  '测试邮件已发送，请检查收件箱和垃圾邮件': 'Test email sent. Check your inbox and spam folder.',
  '请完成邮件服务配置': 'Please complete the email service configuration',
  '邮件服务': 'Email Service',
  '用于通过邮件方式发送报警信息': 'Used to send alert notifications via email',
  '内置': 'Built-in',
  '自定义': 'Custom',
  '邮件服务器': 'SMTP Server',
  '例如：smtp.exmail.qq.com': 'e.g. smtp.exmail.qq.com',
  '例如：465': 'e.g. 465',
  '邮箱账号': 'Email Account',
  '例如：dev@exmail.com': 'e.g. dev@exmail.com',
  '密码/授权码': 'Password / Auth Code',
  '请输入对应的密码或授权码': 'Password or SMTP authorization code',
  '发件人昵称': 'Sender Name',
  '请输入发件人昵称': 'Sender display name',
  '测试邮件服务': 'Test Email Service',

  // KeySetting.js
  '密钥修改确认': 'Confirm key change',
  '请谨慎修改密钥对，修改密钥对可能会让现有的主机都无法进行验证，影响与主机相关的各项功能！': 'Be careful: changing the key pair may break authentication for all existing hosts and affect every host-related feature!',
  // The three entries below form one sentence around a highlighted span, keep the spaces.
  '修改密钥对需要': 'Changes to the key pair ',
  '重启服务后生效': 'take effect after the service is restarted',
  '，已添加的主机可能需要重新进行编辑验证后才可以正常连接。': ', and hosts already added may need to be edited and re-verified before they can connect again.',
  '在这里你可以上传并使用已有的密钥对，没有上传密钥的情况下，Moon会在首次添加主机时自动生成密钥对。': 'You can upload an existing key pair here. If none is uploaded, Moon will generate one automatically when the first host is added.',
  '公钥': 'Public Key',
  '一般位于 ~/.ssh/id_rsa.pub': 'Usually located at ~/.ssh/id_rsa.pub',
  '请输入公钥': 'Enter the public key',
  '私钥': 'Private Key',
  '一般位于 ~/.ssh/id_rsa': 'Usually located at ~/.ssh/id_rsa',
  '请输入私钥内容': 'Enter the private key content',

  // About.js
  '发现上游新版本 {}': 'New upstream version {} available',
  '上游升级说明': 'Upstream upgrade guide',
  '上游版本已是最新': 'Upstream version is up to date',
  '知道了': 'Got it',
  '操作系统': 'Operating System',
  'Python版本': 'Python Version',
  'Django版本': 'Django Version',
  'Moon API版本': 'Moon API Version',
  'Moon Web版本': 'Moon Web Version',
  '上游项目': 'Upstream Project',
  '上游更新日志': 'Upstream Changelog',
  'Moon API版本与Web版本不匹配，请尝试刷新浏览器后再次查看。': 'The Moon API version does not match the web version. Try refreshing your browser and check again.',

  // OpenService.js
  '访问凭据': 'Access Token',
  '该自定义凭据用于访问平台的开放服务，例如：配置中心的配置获取API等，其他开放服务请查询官方文档。': 'This custom token is used to access the platform\'s open services, such as the configuration API of the Config Center. See the official documentation for other open services.',
  '请输入自定义凭证': 'Enter a custom token',

  '登录名': 'Login Name',
  '测试连接': 'Test Connection',

  // SecuritySetting.js
  '访问IP校验': 'Client IP Verification',
  // Followed inline by the "Why is the real IP not detected?" link, keep the trailing space.
  '建议开启，校验是否获取了真实的访问者IP，防止因为增加的反向代理层导致基于IP的安全策略失效，当校验失败时会在登录时弹窗提醒。如果你在内网部署且仅在内网使用可以关闭该特性。': 'Recommended. Verifies that the real client IP is obtained, so IP-based security policies are not defeated by an extra reverse proxy layer. A popup will warn you at login when the check fails. If Moon is deployed and used only on an internal network, you can turn this off. ',
  '为什么没有获取到真实IP？': 'Why is the real IP not detected?',
  '登录IP绑定': 'Login IP Binding',
  '强烈建议开启，当开启后会把登录凭证与IP进行绑定，当该登录凭证通过其他IP访问时将自动失效。如非必要，切勿关闭该特性！': 'Strongly recommended. When enabled, the login session is bound to the client IP and is invalidated automatically if used from another IP. Do not turn this off unless you really have to!',
};

export default dict;

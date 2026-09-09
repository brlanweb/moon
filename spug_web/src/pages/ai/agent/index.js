/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useRef, useState } from 'react';
import { observer } from 'mobx-react';
import { Input, Button, Segmented, Select, Empty, Popconfirm, Spin, Tooltip, message } from 'antd';
import { PlusOutlined, DeleteOutlined, SendOutlined, ExclamationCircleOutlined,
  MessageOutlined, RobotOutlined, SearchOutlined, HistoryOutlined, MenuFoldOutlined,
  MenuUnfoldOutlined, CloudServerOutlined, StopOutlined } from '@ant-design/icons';
import { AuthDiv, Breadcrumb } from 'components';
import { hasPermission, t } from 'libs';
import Metrics from './Metrics';
import Message, { groupRecords } from './Message';
import store from './store';
import styles from './index.module.less';

export default observer(function () {
  const [text, setText] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const bodyRef = useRef(null);
  const followOutput = useRef(true);
  const previousSession = useRef(null);

  useEffect(() => {
    store.fetchSessions();
    store.fetchHosts();
    return () => store.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const sessionId = store.current && store.current.id;
    if (previousSession.current !== sessionId) {
      followOutput.current = true;
      previousSession.current = sessionId;
    }
    if (bodyRef.current && followOutput.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  });

  function handleSend() {
    const question = text.trim();
    if (!question || store.sending || store.pending || !hasPermission('ai.agent.do')) return;
    if (store.mode === 'agent' && !store.hostId) {
      return message.error(t('Agent 模式请先选择服务器'))
    }
    followOutput.current = true;
    setText('');
    store.send(question).catch(() => setText(question))
  }

  function handleKeyDown(e) {
    // Enter 发送，Shift+Enter 换行
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!store.sending) handleSend()
    }
  }

  function handleDelete(item) {
    // 不返回 Promise 给 Popconfirm，避免确认按钮等待接口转圈。
    store.removeSession(item.id).catch(() => {});
  }

  const current = store.current;
  const groups = current ? groupRecords(current.records) : [];
  const host = store.currentHost;
  const locked = store.sending || !!store.pending;
  return (
    <AuthDiv auth="ai.agent.view">
      <Breadcrumb>
        <Breadcrumb.Item>{t('首页')}</Breadcrumb.Item>
        <Breadcrumb.Item>{t('智能体')}</Breadcrumb.Item>
      </Breadcrumb>
      <div className={`${styles.container} ${historyOpen ? styles.historyOpen : ''}`}>
        <aside className={styles.sider} aria-label={t('历史会话')}>
          <div className={styles.siderHeader}>
            <div className={styles.siderHeading}>
              <span><HistoryOutlined/> {t('历史会话')}</span>
              <Tooltip title={t('新建会话')}>
                <Button type="text" icon={<PlusOutlined/>} aria-label={t('新建会话')}
                        disabled={!hasPermission('ai.agent.do')}
                        onClick={() => { store.startNewSession(); setText(''); setHistoryOpen(false); }}/>
              </Tooltip>
            </div>
            <Input allowClear prefix={<SearchOutlined/>} placeholder={t('搜索历史会话')}
                   value={store.f_word} onChange={e => store.f_word = e.target.value}/>
          </div>
          <div className={styles.siderList}>
            <Spin spinning={store.isFetching && !store.sessions.length}>
              {store.sessionList.map(item => {
                const busy = ['running', 'waiting'].includes(item.status) ||
                  (current && current.id === item.id && locked);
                return (
                  <div key={item.id}
                       className={`${styles.sessionItem} ${current && current.id === item.id ? styles.sessionActive : ''}`}>
                    <button type="button" className={styles.sessionSelect}
                            aria-current={current && current.id === item.id ? 'true' : undefined}
                            onClick={() => {
                              setHistoryOpen(false);
                              store.selectSession(item).catch(() => {});
                            }}>
                      <span className={styles.sessionTitle}>{item.title}</span>
                      <span className={styles.sessionMeta}>
                        {item.mode === 'chat' ? <MessageOutlined/> : <RobotOutlined/>}
                        <span>{item.host_name || (item.mode === 'chat' ? t('问答') : 'Agent')}</span>
                        {item.source === 'monitor' && <span>{t('告警')}</span>}
                      </span>
                    </button>
                    {hasPermission('ai.agent.del') && (
                      <Popconfirm title={t('删除此对话？')} placement="rightTop"
                                  disabled={busy} okText={t('删除')} cancelText={t('取消')}
                                  okButtonProps={{danger: true}} onConfirm={() => handleDelete(item)}>
                        <Button type="text" size="small" className={styles.sessionDel}
                                icon={<DeleteOutlined/>} disabled={busy}
                                aria-label={`${t('删除对话')} ${item.title}`}
                                title={busy ? t('任务结束后可删除') : t('删除对话')}/>
                      </Popconfirm>
                    )}
                  </div>
                )
              })}
              {!store.sessionList.length && !store.isFetching && (
                <div className={styles.historyEmpty}>
                  {store.f_word ? t('没有匹配的会话') : t('暂无历史会话')}
                </div>
              )}
            </Spin>
          </div>
        </aside>

        <div className={styles.main}>
          <header className={styles.chatHeader}>
            <Tooltip title={t('历史会话')}>
              <Button type="text" className={styles.historyToggle}
                      aria-label={t('历史会话')} aria-expanded={historyOpen}
                      icon={historyOpen ? <MenuFoldOutlined/> : <MenuUnfoldOutlined/>}
                      onClick={() => setHistoryOpen(!historyOpen)}/>
            </Tooltip>
            <div className={styles.chatHeading}>
              <h2>{current ? current.title : t('新对话')}</h2>
              <span>{store.mode === 'chat' ? <MessageOutlined/> : <RobotOutlined/>}
                {store.mode === 'chat' ? t('问答') : 'Agent'}
                {host && store.mode === 'agent' ? ` · ${host.name}` : ''}
              </span>
            </div>
            {store.mode === 'agent' && host && (
              <Metrics inline hostId={host.id} hostName={`${host.name}（${host.hostname}）`}/>
            )}
            {store.stopping && <span className={styles.stopStatus} role="status">{t('停止中')}</span>}
            <Tooltip title={t('新建会话')}>
              <Button type="text" icon={<PlusOutlined/>} aria-label={t('新建会话')}
                      disabled={!hasPermission('ai.agent.do')}
                      onClick={() => { store.startNewSession(); setText(''); }}/>
            </Tooltip>
          </header>
          <div className={styles.messages} ref={bodyRef} onScroll={e => {
            const el = e.currentTarget;
            followOutput.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}>
            <div className={styles.messageContent}>
              {groups.length === 0 && !store.streaming ? (
                <div className={styles.empty}>
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('开始一次新的对话')}/>
                </div>
              ) : groups.map((group, idx) => (
                <Message key={idx} group={group} live={store.sending && idx === groups.length - 1}/>
              ))}
              {store.streaming && (
                <div className={styles.msgRow}>
                  <div className={`${styles.bubble} ${styles.bubbleAI}`}>
                    {store.streaming}<span className={styles.caret}/>
                  </div>
                </div>
              )}
              {store.pending && (
                <div className={styles.msgRow}>
                  <div className={styles.confirmCard}>
                    <div className={styles.confirmTitle}>
                      <ExclamationCircleOutlined style={{color: '#faad14', marginRight: 6}}/>
                      {t('需要你确认后才会执行')}
                    </div>
                    <div className={styles.confirmReason}>{store.pending.reason}</div>
                    <pre className={styles.code}>{store.pending.command}</pre>
                    <div className={styles.confirmActions}>
                      <Button size="small" disabled={!hasPermission('ai.agent.do')}
                              onClick={() => store.confirm(false).catch(() => {})}>{t('拒绝')}</Button>
                      <Button size="small" danger type="primary" disabled={!hasPermission('ai.agent.do')}
                              onClick={() => store.confirm(true).catch(() => {})}>{t('确认执行')}</Button>
                    </div>
                  </div>
                </div>
              )}
              {store.sending && !store.streaming && !store.pending && (
                <div className={styles.thinking} role="status">
                  <Spin size="small"/> {t('思考中...')}
                </div>
              )}
            </div>
          </div>

          <div className={styles.inputArea}>
            <div className={styles.composer}>
              <Input.TextArea autoSize={{minRows: 2, maxRows: 6}} bordered={false}
                value={text} disabled={locked || !hasPermission('ai.agent.do')}
                onChange={e => setText(e.target.value)} onKeyDown={handleKeyDown}
                aria-label={t('消息')}
                placeholder={store.mode === 'agent' ? t('描述服务器任务…') : t('输入你的问题…')}/>
              <div className={styles.toolbar}>
                <Segmented className={styles.modeSwitch} value={store.mode} disabled={locked}
                  onChange={v => store.mode = v}
                  options={[
                    {value: 'chat', icon: <MessageOutlined/>, label: t('问答')},
                    {value: 'agent', icon: <RobotOutlined/>, label: 'Agent'},
                  ]}/>
                {store.mode === 'agent' && (
                  <div className={styles.hostPicker}>
                    <CloudServerOutlined/>
                    <Select allowClear showSearch bordered={false} optionFilterProp="children"
                      value={store.hostId} disabled={locked} aria-label={t('目标服务器')}
                      placeholder={t('选择服务器')} onChange={v => store.hostId = v}>
                      {store.hosts.map(item => (
                        <Select.Option key={item.id} value={item.id}>
                          {item.name}（{item.hostname}）
                        </Select.Option>
                      ))}
                    </Select>
                  </div>
                )}
                {store.sending && store.canStop ? (
                  <Tooltip title={store.stopping ? t('正在停止，等待当前操作结束') : t('停止生成')}>
                    <Button className={styles.sendButton} icon={<StopOutlined/>} aria-label={t('停止生成')}
                      danger disabled={store.stopping || !hasPermission('ai.agent.do')}
                      onClick={() => store.stop().catch(() => {})}/>
                  </Tooltip>
                ) : (
                  <Tooltip title={t('发送')}>
                    <Button type="primary" className={styles.sendButton} icon={<SendOutlined/>}
                      aria-label={t('发送')} disabled={!text.trim() || locked || !hasPermission('ai.agent.do') ||
                        (store.mode === 'agent' && !store.hostId)} onClick={handleSend}/>
                  </Tooltip>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </AuthDiv>
  );
})

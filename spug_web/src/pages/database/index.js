import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Dropdown, Empty, Input, Modal, Space, Spin, Tabs, Tree, message } from 'antd';
import {
  DatabaseOutlined,
  DeleteOutlined,
  DisconnectOutlined,
  EditOutlined,
  MoreOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  TableOutlined,
} from '@ant-design/icons';
import { NotFound } from 'components';
import { hasPermission, http, includes, t } from 'libs';
import MoonBrand from 'components/MoonBrand';
import ConnectionForm from './ConnectionForm';
import QueryPanel from './QueryPanel';
import styles from './index.module.less';


function typeClass(type) {
  if (type === 'redis') return styles.typeDotRedis;
  if (type === 'clickhouse') return styles.typeDotClickhouse;
  return '';
}

function quoteName(type, value) {
  if (type === 'mysql' || type === 'mariadb' || type === 'clickhouse') {
    return `\`${String(value).replace(/`/g, '``')}\``;
  }
  return `"${String(value).replace(/"/g, '""')}"`;
}

export default function DatabaseConsole() {
  const [connections, setConnections] = useState([]);
  const [metadata, setMetadata] = useState({});
  const [fetching, setFetching] = useState(true);
  const [connectingId, setConnectingId] = useState();
  const [search, setSearch] = useState('');
  const [tabs, setTabs] = useState([]);
  const [activeId, setActiveId] = useState();
  const [expandedKeys, setExpandedKeys] = useState([]);
  const [commands, setCommands] = useState({});
  const [formVisible, setFormVisible] = useState(false);
  const [record, setRecord] = useState({});
  const connectionsRef = useRef(connections);
  const tabsRef = useRef(tabs);
  const activeIdRef = useRef(activeId);
  const lastActivityRef = useRef({});
  const requestGenerationRef = useRef({});

  connectionsRef.current = connections;
  tabsRef.current = tabs;
  activeIdRef.current = activeId;

  useEffect(() => {
    document.title = 'Moon database console';
    fetchConnections();
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now();
      connectionsRef.current.forEach(item => {
        const timeout = Number(item.idle_timeout);
        const lastActivity = lastActivityRef.current[item.id];
        if (timeout > 0 && lastActivity !== undefined && now - lastActivity >= timeout * 60 * 1000) {
          disconnectConnection(item.id);
          message.info(t('连接【{}】因空闲已断开', item.name));
        }
      });
    }, 15000);
    return () => clearInterval(timer);
  }, []);

  function markActivity(id) {
    lastActivityRef.current[id] = Date.now();
  }

  function nextRequestGeneration(id) {
    const generation = (requestGenerationRef.current[id] || 0) + 1;
    requestGenerationRef.current[id] = generation;
    return generation;
  }

  function tabStateAfterClose(id) {
    const currentTabs = tabsRef.current;
    const index = currentTabs.indexOf(id);
    const nextTabs = currentTabs.filter(item => item !== id);
    const nextActive = activeIdRef.current === id ? nextTabs[index] || nextTabs[index - 1] : activeIdRef.current;
    return {nextTabs, nextActive};
  }

  function disconnectConnection(id) {
    nextRequestGeneration(id);
    const {nextTabs, nextActive} = tabStateAfterClose(id);
    const activeChanged = activeIdRef.current === id;
    tabsRef.current = nextTabs;
    activeIdRef.current = nextActive;
    delete lastActivityRef.current[id];
    if (activeChanged && nextActive !== undefined) markActivity(nextActive);
    setTabs(nextTabs);
    setActiveId(nextActive);
    setConnectingId(current => current === id ? undefined : current);
    setMetadata(current => {
      const next = {...current};
      delete next[id];
      return next;
    });
    setCommands(current => {
      const next = {...current};
      delete next[id];
      return next;
    });
    setExpandedKeys(current => current.filter(key => {
      const value = String(key);
      return value !== `connection-${id}` &&
        !value.startsWith(`group-${id}-`) &&
        !value.startsWith(`item-${id}-`);
    }));
  }

  function fetchConnections() {
    setFetching(true);
    return http.get('/api/database/connection/')
      .then(setConnections)
      .finally(() => setFetching(false));
  }

  function openForm(item = {}) {
    setRecord(item);
    setFormVisible(true);
  }

  function removeConnection(item) {
    Modal.confirm({
      title: t('删除数据库连接'),
      content: t('确定删除连接【{}】？', item.name),
      okButtonProps: {danger: true},
      onOk: () => http.delete('/api/database/connection/', {params: {id: item.id}}).then(() => {
        message.success(t('删除成功'));
        setTabs(current => current.filter(id => id !== item.id));
        setActiveId(current => current === item.id ? undefined : current);
        fetchConnections();
      }),
    });
  }

  function connectionMenu(item) {
    const items = [];
    if (metadata[item.id] || tabs.includes(item.id)) {
      items.push({key: 'disconnect', icon: <DisconnectOutlined/>, label: t('断开连接')});
    }
    if (hasPermission('database.connection.edit')) {
      items.push({key: 'edit', icon: <EditOutlined/>, label: t('编辑')});
    }
    if (hasPermission('database.connection.del')) {
      items.push({key: 'delete', danger: true, icon: <DeleteOutlined/>, label: t('删除')});
    }
    return {
      items,
      onClick: ({key, domEvent}) => {
        domEvent.stopPropagation();
        if (key === 'disconnect') disconnectConnection(item.id);
        if (key === 'edit') openForm(item);
        if (key === 'delete') removeConnection(item);
      },
    };
  }

  function openConnection(item, refresh = false) {
    if (!item) return;
    const nodeKey = `connection-${item.id}`;
    const activate = () => {
      markActivity(item.id);
      setTabs(current => current.includes(item.id) ? current : [...current, item.id]);
      setActiveId(item.id);
      setExpandedKeys(current => current.includes(nodeKey) ? current : [...current, nodeKey]);
    };
    if (metadata[item.id] && !refresh) {
      activate();
      return;
    }
    const generation = nextRequestGeneration(item.id);
    setConnectingId(item.id);
    http.get('/api/database/metadata/', {params: {id: item.id}})
      .then(data => {
        if (requestGenerationRef.current[item.id] !== generation) return;
        setMetadata(current => ({...current, [item.id]: data}));
        activate();
        if (data.truncated) message.warning(t('对象较多，目录仅展示前 5000 项'));
      })
      .finally(() => {
        if (requestGenerationRef.current[item.id] === generation) {
          setConnectingId(current => current === item.id ? undefined : current);
        }
      });
  }

  function selectNode(_, info) {
    const node = info.node;
    const item = connections.find(connection => connection.id === node.connectionId);
    if (!item) return;
    if (node.kind === 'connection') {
      openConnection(item);
      return;
    }
    if (node.kind === 'table') {
      openConnection(item);
      let command;
      if (item.type === 'redis') {
        command = `TYPE ${JSON.stringify(node.item)}`;
      } else {
        command = `SELECT * FROM ${quoteName(item.type, node.namespace)}.${quoteName(item.type, node.item)} LIMIT 100;`;
      }
      setCommands(current => ({...current, [item.id]: command}));
    }
  }

  function closeTab(targetId) {
    const {nextTabs, nextActive} = tabStateAfterClose(targetId);
    const activeChanged = activeIdRef.current === targetId;
    tabsRef.current = nextTabs;
    activeIdRef.current = nextActive;
    if (activeChanged && nextActive !== undefined) markActivity(nextActive);
    setTabs(nextTabs);
    setActiveId(nextActive);
  }

  const filteredConnections = useMemo(
    () => connections.filter(item => !search || includes([item.name, item.host, item.type_alias], search)),
    [connections, search],
  );

  const treeData = filteredConnections.map(item => {
    const groups = metadata[item.id]?.groups || [];
    return {
      key: `connection-${item.id}`,
      connectionId: item.id,
      kind: 'connection',
      icon: <DatabaseOutlined/>,
      title: (
        <span className={styles.connectionLabel} title={`${item.name} · ${item.type_alias}`}>
          <i className={`${styles.typeDot} ${typeClass(item.type)}`}/>
          <span className={styles.connectionName}>{item.name}</span>
          {connectionMenu(item).items.length > 0 && (
            <Dropdown trigger={['click']} menu={connectionMenu(item)}>
              <span className={styles.connectionAction} onClick={event => event.stopPropagation()}>
                <MoreOutlined/>
              </span>
            </Dropdown>
          )}
        </span>
      ),
      children: groups.map((group, groupIndex) => ({
        key: `group-${item.id}-${groupIndex}`,
        connectionId: item.id,
        kind: 'group',
        title: group.name,
        children: group.items.map((name, itemIndex) => ({
          key: `item-${item.id}-${groupIndex}-${itemIndex}`,
          connectionId: item.id,
          kind: 'table',
          namespace: group.name,
          item: name,
          title: name,
          icon: <TableOutlined/>,
          isLeaf: true,
        })),
      })),
    };
  });

  const tabItems = tabs.map(id => {
    const item = connections.find(connection => connection.id === id);
    if (!item) return null;
    return {
      key: String(id),
      label: item.name,
      children: (
        <QueryPanel
          connection={item}
          command={commands[id]}
          onActivity={() => markActivity(id)}
          onCommandChange={value => setCommands(current => ({...current, [id]: value}))}/>
      ),
    };
  }).filter(Boolean);

  if (!hasPermission('database.connection.view')) {
    return <div style={{height: '100vh'}}><NotFound/></div>;
  }

  return (
    <div className={styles.container}>
      <aside className={styles.sider}>
        <a className={styles.logo} href="/dashboard" target="_blank" rel="noreferrer">
          <MoonBrand/>
        </a>
        <div className={styles.sourceHeader}>
          <span>{t('数据库连接')}</span>
          <Space size={2}>
            <Button type="text" size="small" title={t('刷新')} icon={<ReloadOutlined/>} onClick={fetchConnections}/>
            {hasPermission('database.connection.add') && (
              <Button type="text" size="small" title={t('新建连接')} icon={<PlusOutlined/>} onClick={() => openForm()}/>
            )}
          </Space>
        </div>
        <Input allowClear className={styles.search} prefix={<SearchOutlined/>}
               placeholder={t('搜索连接')} onChange={event => setSearch(event.target.value)}/>
        <Spin spinning={fetching || Boolean(connectingId)} wrapperClassName={styles.tree}>
          {treeData.length ? (
            <Tree showIcon blockNode treeData={treeData} onSelect={selectNode}
                  expandedKeys={expandedKeys} onExpand={setExpandedKeys}/>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('暂无数据库连接')}/>
          )}
        </Spin>
      </aside>
      <main className={styles.content}>
        {tabItems.length ? (
          <Tabs className={styles.tabs} type="editable-card" hideAdd activeKey={String(activeId)}
                onChange={key => {
                  const id = Number(key);
                  markActivity(id);
                  setActiveId(id);
                }}
                onEdit={(key, action) => action === 'remove' && closeTab(Number(key))}
                tabBarExtraContent={activeId ? (
                  <Button type="text" icon={<ReloadOutlined/>}
                          onClick={() => openConnection(connections.find(item => item.id === activeId), true)}>{t('刷新目录')}</Button>
                ) : null}
                items={tabItems}/>
        ) : (
          <div className={styles.empty}>
            <Empty image={<DatabaseOutlined style={{fontSize: 64, color: '#cbd5e1'}}/>}
                   description={t('点击左侧连接源进入数据库工作台')}/>
          </div>
        )}
      </main>
      <ConnectionForm
        record={record}
        visible={formVisible}
        onClose={() => setFormVisible(false)}
        onSaved={() => {
          setFormVisible(false);
          setMetadata({});
          fetchConnections();
        }}/>
    </div>
  );
}

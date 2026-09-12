import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Modal, Space, Table, Tag, Tooltip, message } from 'antd';
import { ClearOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import { hasPermission, http, t } from 'libs';
import { clearDockerCache, readDockerCache, writeDockerCache } from './cache';
import styles from './index.module.less';


const KIND_LABELS = {
  images: '镜像',
  networks: '网络',
  volumes: '存储卷',
};

// Docker 内置网络不允许删除，提前禁用避免用户点击后才收到报错。
const PROTECTED_NETWORKS = ['bridge', 'host', 'none'];

export default function Resources({kind, hostId}) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState('');
  const seq = useRef(0);
  const mountedRef = useRef(false);
  const canWrite = hasPermission('docker.project.do');

  const load = useCallback((force = false) => {
    if (hostId === undefined || !mountedRef.current) return Promise.resolve();
    if (!force) {
      const cached = readDockerCache(hostId, kind);
      if (cached && Array.isArray(cached.items)) {
        setItems(cached.items);
        return Promise.resolve(cached);
      }
    }
    const current = ++seq.current;
    setLoading(true);
    return http.post('/api/docker/resource/', {host_id: hostId, kind, action: 'list'}, {timeout: 70000})
      .then(data => {
        if (current !== seq.current) return;
        writeDockerCache(hostId, kind, {items: data.items || []});
        setItems(data.items || []);
      })
      .finally(() => {
        if (current === seq.current) setLoading(false);
      });
  }, [hostId, kind]);

  useEffect(() => {
    mountedRef.current = true;
    setItems([]);
    load();
    return () => {
      mountedRef.current = false;
      seq.current += 1;
    };
  }, [load]);

  function remove(item) {
    Modal.confirm({
      title: t('删除{}', t(KIND_LABELS[kind])),
      content: t('确定要删除【{}】？此操作不可恢复。', item.name),
      okButtonProps: {danger: true},
      onOk: () => {
        if (!mountedRef.current) return;
        setBusy(item.id);
        return http.post('/api/docker/resource/', {
          host_id: hostId, kind, action: 'remove',
          target: kind === 'images' ? item.id : item.name,
          force: kind === 'images',
        }, {timeout: 320000})
          .then(() => {
            clearDockerCache(hostId, kind, 'overview');
            message.success(t('删除成功'));
            return load(true);
          })
          .finally(() => { if (mountedRef.current) setBusy(''); });
      },
    });
  }

  function prune() {
    const tips = {
      images: t('将清理所有悬空镜像（未被任何标签引用的层）。'),
      networks: t('将清理所有未被容器使用的网络。'),
      volumes: t('将清理所有未被容器使用的存储卷，卷内数据会一并丢失。'),
    };
    Modal.confirm({
      title: t('清理未使用的{}', t(KIND_LABELS[kind])),
      content: tips[kind],
      okButtonProps: {danger: true},
      onOk: () => {
        if (!mountedRef.current) return;
        setBusy('prune');
        return http.post('/api/docker/resource/', {host_id: hostId, kind, action: 'prune'},
          {timeout: 320000})
          .then(data => {
            clearDockerCache(hostId, kind, 'overview');
            message.success(data.output ? data.output.split('\n').slice(-2).join(' ') : t('清理完成'));
            return load(true);
          })
          .finally(() => { if (mountedRef.current) setBusy(''); });
      },
    });
  }

  function actionColumn(item) {
    const isProtected = kind === 'networks' && PROTECTED_NETWORKS.includes(item.name);
    return (
      <Tooltip title={isProtected ? t('Docker 内置网络不可删除') : t('删除')}>
        <Button type="text" danger icon={<DeleteOutlined/>}
                loading={busy === item.id} disabled={!canWrite || isProtected || loading || Boolean(busy)}
                onClick={() => remove(item)}/>
      </Tooltip>
    );
  }

  const columnsByKind = {
    images: [
      {title: t('镜像'), dataIndex: 'name', ellipsis: true, render: (value, item) => (
        <Space size={6}>
          <span>{value}</span>
          {item.dangling && <Tag color="orange">{t('悬空')}</Tag>}
        </Space>
      )},
      {title: 'ID', dataIndex: 'id', width: 200, ellipsis: true},
      {title: t('大小'), dataIndex: 'size', width: 110},
      {title: t('创建于'), dataIndex: 'created', width: 150},
    ],
    networks: [
      {title: t('名称'), dataIndex: 'name', ellipsis: true},
      {title: 'ID', dataIndex: 'id', width: 200, ellipsis: true},
      {title: t('驱动'), dataIndex: 'driver', width: 120},
      {title: t('范围'), dataIndex: 'scope', width: 110},
    ],
    volumes: [
      {title: t('名称'), dataIndex: 'name', ellipsis: true},
      {title: t('驱动'), dataIndex: 'driver', width: 120},
      {title: t('挂载点'), dataIndex: 'mountpoint', ellipsis: true},
    ],
  };

  const columns = [
    ...columnsByKind[kind],
    {title: t('操作'), width: 80, render: (_, item) => actionColumn(item)},
  ];

  return (
    <div>
      <div className={styles.configBar}>
        <span className={styles.resourceCount}>{t('共 {} 项', items.length)}</span>
        <Space>
          <Button icon={<ReloadOutlined/>} loading={loading} disabled={hostId === undefined || Boolean(busy)} onClick={() => load(true)}>{t('刷新')}</Button>
          <Button danger icon={<ClearOutlined/>} loading={busy === 'prune'}
                  disabled={!canWrite || hostId === undefined || loading || Boolean(busy)}
                  onClick={prune}>{t('清理未使用')}</Button>
        </Space>
      </div>
      <Table size="small" rowKey="id" loading={loading} columns={columns} dataSource={items}
             scroll={{x: 720}}
             pagination={{size: 'small', hideOnSinglePage: true, pageSize: 10}}/>
    </div>
  );
}

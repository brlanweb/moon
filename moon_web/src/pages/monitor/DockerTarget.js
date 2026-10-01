import React, {useEffect, useMemo, useState} from 'react';
import {Alert, Select, Space, Spin} from 'antd';
import {http, t} from 'libs';


function sameScope(left, right) {
  if (!left || !right || left.kind !== right.kind) return false;
  if (left.kind === 'standalone_container') return left.container === right.container;
  return left.project === right.project
    && left.workdir === right.workdir
    && left.service === right.service
    && JSON.stringify(left.config_files || []) === JSON.stringify(right.config_files || []);
}


export default function DockerTarget({hostId, value, onChange}) {
  const [hosts, setHosts] = useState([]);
  const [projects, setProjects] = useState([]);
  const [standalone, setStandalone] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    http.get('/api/host/').then(res => setHosts(res.filter(item => item.is_verified)));
  }, []);

  useEffect(() => {
    setProjects([]);
    setStandalone([]);
    setLoaded(false);
    setError('');
    if (!hostId) return;
    setLoading(true);
    http.post('/api/docker/discover/', {host_id: hostId, use_cache: false}, {timeout: 70000})
      .then(res => {
        setProjects(res.projects || []);
        setStandalone(res.standalone || []);
        setLoaded(true);
      }, err => {
        setError(typeof err === 'string' ? err : t('Docker服务加载失败'));
        setLoaded(true);
      })
      .finally(() => setLoading(false));
  }, [hostId]);

  const options = useMemo(() => {
    const result = [];
    projects.forEach(project => {
      const seen = new Set();
      const children = [];
      (project.containers || []).forEach(container => {
        if (!container.service || seen.has(container.service)) return;
        seen.add(container.service);
        children.push({
          key: `compose:${project.name}:${project.config_file}:${container.service}`,
          label: `${container.service} (${(project.containers || []).filter(
            item => item.service === container.service).length} ${t('个副本')})`,
          scope: {
            version: 1,
            kind: 'compose_service',
            project: project.name,
            workdir: project.workdir,
            config_files: project.config_files || [project.config_file],
            service: container.service,
          },
        });
      });
      if (children.length) result.push({
        key: `project:${project.name}:${project.config_file}`,
        label: `${project.name} · ${project.workdir}`,
        children,
      });
    });
    if (standalone.length) result.push({
      key: 'standalone',
      label: t('独立容器'),
      children: standalone.map(container => ({
        key: `container:${container.name}`,
        label: `${container.name} (${container.state || '-'})`,
        scope: {version: 1, kind: 'standalone_container', container: container.name},
      })),
    });
    return result;
  }, [projects, standalone]);

  const flatOptions = options.reduce((items, group) => items.concat(group.children), []);
  const selected = flatOptions.find(item => sameScope(item.scope, value));
  const selectedKey = selected?.key;
  const stale = Boolean(value && loaded && !selected && !loading && !error);

  function handleHostChange(id) {
    onChange(id, null);
  }

  function handleTargetChange(key) {
    const item = flatOptions.find(option => option.key === key);
    onChange(hostId, item?.scope || null);
  }

  return (
    <Space direction="vertical" size={12} style={{width: '100%'}}>
      <Select
        showSearch
        allowClear
        optionFilterProp="children"
        value={hostId}
        placeholder={t('请选择已验证的Docker主机')}
        onChange={handleHostChange}>
        {hosts.map(host => (
          <Select.Option key={host.id} value={host.id}>{host.name}（{host.hostname}）</Select.Option>
        ))}
      </Select>
      <Spin spinning={loading}>
        <Select
          showSearch
          allowClear
          optionFilterProp="children"
          value={selectedKey}
          disabled={!hostId || loading}
          placeholder={hostId ? t('请选择Compose服务或独立容器') : t('请先选择Docker主机')}
          onChange={handleTargetChange}>
          {options.map(group => (
            <Select.OptGroup key={group.key} label={group.label}>
              {group.children.map(item => (
                <Select.Option key={item.key} value={item.key}>{item.label}</Select.Option>
              ))}
            </Select.OptGroup>
          ))}
        </Select>
      </Spin>
      {error && <Alert showIcon type="error" message={error}/>}
      {stale && <Alert showIcon type="warning" message={t('已保存的Docker目标当前不可用，请刷新主机状态或重新选择目标。')}/>}
      {!error && loaded && options.length === 0 && (
        <Alert showIcon type="info" message={t('该主机未发现可监控的Docker服务或容器')}/>
      )}
    </Space>
  );
}

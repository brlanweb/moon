import React, { useEffect, useRef, useState } from 'react';
import {
  Alert, Button, Checkbox, Empty, Input, Modal, Select, Space, Spin, Table, Tabs, Tag, Tooltip, message,
} from 'antd';
import {
  AppstoreOutlined, CaretRightOutlined, ClearOutlined, CloudServerOutlined, DatabaseOutlined,
  DeleteOutlined, DockerOutlined, FileTextOutlined, HddOutlined, PauseOutlined, PlayCircleOutlined,
  PlusOutlined, RedoOutlined, ReloadOutlined, SaveOutlined, SearchOutlined, StopOutlined,
} from '@ant-design/icons';
import { ACEditor } from 'components';
import { hasPermission, http, t, X_TOKEN } from 'libs';
import { Prompt, useHistory, useLocation } from 'react-router-dom';
import CreateProject from './CreateProject';
import Resources from './Resources';
import { clearDockerCache, readDockerCache, writeDockerCache } from './cache';
import styles from './index.module.less';


const SECTION_LABELS = {
  overview: '概览',
  containers: '容器',
  images: '镜像',
  networks: '网络',
  volumes: '卷',
  compose: 'Compose',
};

const SECTION_ICONS = {
  overview: <AppstoreOutlined/>, containers: <DockerOutlined/>, images: <DatabaseOutlined/>,
  networks: <CloudServerOutlined/>, volumes: <HddOutlined/>, compose: <FileTextOutlined/>,
};

export function resolveSection(section, pathname = '', search = '') {
  const querySection = new URLSearchParams(search).get('tab');
  const value = section || querySection || pathname.replace(/\/+$/, '').split('/').pop();
  const aliases = {project: 'compose', projects: 'compose', storage: 'volumes', docker: 'overview'};
  const key = aliases[value] || value;
  return Object.prototype.hasOwnProperty.call(SECTION_LABELS, key) ? key : 'overview';
}

export default function DockerConsole({section, location, path, match} = {}) {
  const routerLocation = useLocation();
  const routerHistory = useHistory();
  const currentSection = resolveSection(
    section, location?.pathname || path || match?.path || routerLocation.pathname,
    location?.search || routerLocation.search);
  const [hosts, setHosts] = useState([]);
  const [hostId, setHostId] = useState();
  const [composeDirty, setComposeDirty] = useState(false);

  useEffect(() => {
    let cancelled = false;
    http.get('/api/host/').then(data => { if (!cancelled) setHosts(data); });
    return () => { cancelled = true; };
  }, []);

  function changeHost(value) {
    const apply = () => { setComposeDirty(false); setHostId(value); };
    if (composeDirty) {
      Modal.confirm({
        title: t('存在未保存修改'),
        content: t('切换服务器会丢弃当前修改，确认继续？'),
        onOk: apply,
      });
      return;
    }
    apply();
  }

  function changeSection(key) {
    if (section) return;
    const target = key === 'overview' ? '/docker' : `/docker?tab=${key}`;
    const current = `${routerLocation.pathname}${routerLocation.search}`;
    if (current !== target) routerHistory.push(target);
  }

  let content;
  if (currentSection === 'overview') {
    content = <OverviewPanel key={hostId === undefined ? 'none' : hostId}
                             hostId={hostId} onNavigate={changeSection}/>;
  } else if (currentSection === 'images' || currentSection === 'networks' || currentSection === 'volumes') {
    content = hostId === undefined ? <Empty description={t('请先选择服务器')}/> : (
      <Resources key={`${currentSection}:${hostId}`} kind={currentSection} hostId={hostId}/>
    );
  } else {
    content = <ProjectConsole key={`${currentSection}:${hostId === undefined ? 'none' : hostId}`}
                              hosts={hosts} hostId={hostId} onDirtyChange={setComposeDirty}
                              initialView={currentSection === 'containers' ? 'standalone' : 'project'}/>;
  }

  return (
    <main className={styles.workspace}>
      <header className={styles.workspaceHeader}>
        <div className={styles.brand}>
          <DockerOutlined/>
          <div><h1>Docker</h1><span>{hostId === undefined ? t('选择服务器开始管理') : t('SSH · 读写')}</span></div>
        </div>
        <div className={styles.hostPicker}>
          <Select value={hostId} aria-label={t('选择服务器')} placeholder={t('选择服务器')}
                  onChange={changeHost}>
            {hosts.map(host => <Select.Option key={host.id} value={host.id}>{host.name} ({host.hostname})</Select.Option>)}
          </Select>
        </div>
      </header>
      <Tabs className={styles.workspaceTabs} activeKey={currentSection} onChange={changeSection}
            items={Object.keys(SECTION_LABELS).map(key => ({
              key, label: <span>{SECTION_ICONS[key]} {t(SECTION_LABELS[key])}</span>,
            }))}/>
      <section className={`${styles.workspaceBody} ${currentSection === 'compose' || currentSection === 'containers' ? styles.workspaceBodyFlush : ''}`}>
        {content}
      </section>
    </main>
  );
}

function OverviewPanel({hostId, onNavigate}) {
  const [data, setData] = useState();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  function load(force = false) {
    if (hostId === undefined) return Promise.resolve();
    if (!force) {
      const cached = readDockerCache(hostId, 'overview');
      if (cached) {
        setData(cached);
        return Promise.resolve(cached);
      }
    }
    setLoading(true);
    setError(false);
    return http.post('/api/docker/overview/', {host_id: hostId}, {timeout: 70000})
      .then(result => {
        writeDockerCache(hostId, 'overview', result);
        setData(result);
        return result;
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, [hostId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (hostId === undefined) return <Empty description={t('请先选择服务器')}/>;
  if (error) return (
    <Empty description={t('概览加载失败')}>
      <Button icon={<ReloadOutlined/>} loading={loading} onClick={() => load(true)}>{t('重试')}</Button>
    </Empty>
  );
  if (!data) return <div className={styles.overviewLoading}><Spin spinning={loading}/></div>;

  const metrics = [
    ['containers_running', '运行中容器', <DockerOutlined/>, 'containers'],
    ['containers_paused', '暂停容器', <PauseOutlined/>, 'containers'],
    ['containers_stopped', '停止容器', <StopOutlined/>, 'containers'],
    ['containers', '容器总数', <AppstoreOutlined/>, 'containers'],
    ['images', '镜像', <DatabaseOutlined/>, 'images'],
    ['memory', '内存', <HddOutlined/>],
  ];
  const engine = [
    ['Engine 版本', data.engine_version], ['最高 API 版本', data.api_version],
    ['最低 API 版本', data.min_api_version], ['连接方式', 'SSH'],
    ['操作系统', data.operating_system], ['架构', data.architecture],
    ['内核', data.kernel_version], ['存储驱动', data.storage_driver],
  ];
  const capabilities = [
    ['CPU', data.cpus], ['内存', data.memory], ['容器管理', '可用'],
    ['实时 Stats', '可用'], ['实时日志', '可用'], ['Compose', '可用'],
  ];

  return (
    <div className={styles.overview}>
      <div className={styles.overviewActions}>
        <Tag>docker {data.engine_version}</Tag>
        <Button icon={<ReloadOutlined/>} loading={loading} onClick={() => load(true)}>{t('刷新')}</Button>
      </div>
      <div className={styles.metricGrid}>
        {metrics.map(([key, label, icon, target]) => {
          const content = <><span>{icon}</span><strong>{data[key]}</strong><small>{t(label)}</small></>;
          return target ? (
            <button type="button" className={`${styles.metric} ${styles.metricLink}`} key={key}
                    onClick={() => onNavigate(target)}>{content}</button>
          ) : <div className={styles.metric} key={key}>{content}</div>;
        })}
      </div>
      <div className={styles.infoGrid}>
        <section className={styles.infoPanel}>
          <h2><DatabaseOutlined/> Engine</h2>
          <dl>{engine.map(([label, value]) => <React.Fragment key={label}><dt>{t(label)}</dt><dd>{value || '-'}</dd></React.Fragment>)}</dl>
        </section>
        <section className={styles.infoPanel}>
          <h2><AppstoreOutlined/> {t('资源与能力')}</h2>
          <dl>{capabilities.map(([label, value]) => <React.Fragment key={label}><dt>{t(label)}</dt><dd>{value}</dd></React.Fragment>)}</dl>
        </section>
      </div>
    </div>
  );
}

// v2：缓存结构从「项目数组」改为「项目 + 独立容器」，换前缀避免读到旧数据
const PROJECT_CACHE_PREFIX = 'spug:docker:inspect:v2:';
// 跟随日志时前端保留的最大行数，超出丢弃最早的，避免长时间盯着日志把内存吃满
const MAX_LOG_LINES = 5000;

function projectKey(item) {
  return `${item.name}|${item.workdir}|${item.config_file}`;
}

// 远程主机的项目发现要遍历 docker inspect，常需十几秒。这里把上一次结果
// 存到 localStorage，切换服务器时先渲染缓存，真实数据由后台刷新覆盖。
function readProjectCache(hostId) {
  try {
    const data = JSON.parse(localStorage.getItem(PROJECT_CACHE_PREFIX + hostId));
    if (!data || !Array.isArray(data.projects) || !Array.isArray(data.standalone)) return null;
    return data.projects.length || data.standalone.length ? data : null;
  } catch (e) {
    return null;
  }
}

function writeProjectCache(hostId, data) {
  try {
    localStorage.setItem(PROJECT_CACHE_PREFIX + hostId, JSON.stringify({
      projects: data.projects || [], standalone: data.standalone || [],
    }));
  } catch (e) {
    // 配额不足时忽略：缓存只是加速手段，缺失不影响功能
  }
}

function ProjectConsole({hosts, hostId, initialView = 'project', onDirtyChange}) {
  const [projects, setProjects] = useState([]);
  // 非 compose 管理的容器（docker run 起的，或 compose 标签残缺）
  const [standalone, setStandalone] = useState([]);
  const [activeKey, setActiveKey] = useState();
  const [fetching, setFetching] = useState(false);
  const [running, setRunning] = useState('');
  const [configLoading, setConfigLoading] = useState(false);
  const [configContent, setConfigContent] = useState('');
  const [savedContent, setSavedContent] = useState('');
  const [selectedFile, setSelectedFile] = useState();
  const [logLines, setLogLines] = useState([]);
  const [logKeyword, setLogKeyword] = useState('');
  const [logService, setLogService] = useState();
  const [tail, setTail] = useState(200);
  // 实时跟随开关，开启后用 SSE 持续接收 docker logs -f 的输出
  const [follow, setFollow] = useState(false);
  const [following, setFollowing] = useState(false);
  const [activeTab, setActiveTab] = useState(hasPermission('docker.project.edit') ? 'compose' : 'logs');
  const [createOpen, setCreateOpen] = useState(false);
  // 列表来自缓存、后台正在拉取真实数据时为 true，仅用于提示，不阻塞交互。
  const [stale, setStale] = useState(false);
  const [stats, setStats] = useState({});
  // Compose 页显示项目，容器页直接进入独立容器视图。
  const [view, setView] = useState(initialView);
  const mountedRef = useRef(false);
  const discoverSeq = useRef(0);
  const configSeq = useRef(0);
  const logsSeq = useRef(0);
  const configCache = useRef({});
  const activeKeyRef = useRef();
  const statsRef = useRef(null);
  const editorBoxRef = useRef();
  const logBoxRef = useRef();
  const logStreamRef = useRef(null);
  // 用户是否贴着日志底部，决定新日志到达时要不要自动滚动
  const stickBottomRef = useRef(true);
  // ACEditor 只接受具体像素高度，用 ResizeObserver 跟随容器铺满剩余空间
  const [editorHeight, setEditorHeight] = useState(360);
  const [logWrap, setLogWrap] = useState(true);
  const active = projects.find(item => projectKey(item) === activeKey);
  const isContainerWorkspace = initialView === 'standalone';
  const managedContainers = projects.reduce((result, project) => result.concat(
    project.containers.map(container => ({...container, managed: true}))), []);
  const displayedContainers = isContainerWorkspace ? managedContainers.concat(standalone) : standalone;
  const writeBusy = Boolean(running && !running.startsWith('logs:'));

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      discoverSeq.current += 1;
      configSeq.current += 1;
      logsSeq.current += 1;
      closeStats();
      closeLogStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (onDirtyChange) onDirtyChange(configContent !== savedContent);
  }, [configContent, savedContent, onDirtyChange]);

  useEffect(() => () => {
    if (onDirtyChange) onDirtyChange(false);
  }, [onDirtyChange]);

  useEffect(() => { activeKeyRef.current = activeKey; }, [activeKey]);

  useEffect(() => {
    if (hostId !== undefined) loadProjects(hostId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostId]);

  useEffect(() => {
    if (!active) {
      setConfigContent('');
      setSavedContent('');
      return;
    }
    setSelectedFile(active.config_file);
    setLogLines([]);
    setLogService(undefined);
    // 切项目要停掉跟随，避免用户以为看的还是原来那个项目的日志
    setFollow(false);
    if (hasPermission('docker.project.edit')) loadConfig(active, active.config_file);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeKey]);

  function applyProjects(items, preferredKey, silent) {
    setProjects(items);
    const wanted = preferredKey || activeKeyRef.current;
    const next = items.find(item => projectKey(item) === wanted) || (silent ? null : items[0]);
    if (next) setActiveKey(projectKey(next));
    else if (!silent) setActiveKey(undefined);
  }

  function discover(targetHostId = hostId, preferredKey, silent = false, useCache = false) {
    if (!mountedRef.current || targetHostId === undefined) return Promise.resolve(null);
    const seq = ++discoverSeq.current;
    setFetching(true);
    if (!silent) {
      // 静默刷新用于操作后同步状态：保留列表可以避免整页闪烁重排。
      setProjects([]);
      setStandalone([]);
      setActiveKey(undefined);
      setConfigContent('');
      setLogLines([]);
    }
    return http.post('/api/docker/discover/', {host_id: targetHostId, use_cache: useCache},
      {timeout: 70000})
      .then(data => {
        if (seq !== discoverSeq.current) return null;
        const items = data.projects || [];
        if (!data.cached) writeProjectCache(targetHostId, data);
        setStandalone(data.standalone || []);
        applyProjects(items, preferredKey, silent);
        return data;
      })
      .finally(() => {
        if (seq === discoverSeq.current) setFetching(false);
      });
  }

  /** 切换服务器时的加载策略：先出缓存、再后台刷新，避免长时间空白等待。
   *  1. 本地 localStorage 缓存命中 → 立刻渲染，后台静默刷新
   *  2. 未命中 → 请求服务端长效缓存，若确实是缓存数据再补一次强制刷新 */
  function loadProjects(targetHostId) {
    setStats({});
    closeStats();
    const cached = readProjectCache(targetHostId);
    if (cached) {
      discoverSeq.current += 1;
      setStandalone(cached.standalone || []);
      applyProjects(cached.projects || [], undefined, false);
      setStale(true);
      return discover(targetHostId, undefined, true).finally(() => {
        if (mountedRef.current) setStale(false);
      });
    }
    setStale(true);
    return discover(targetHostId, undefined, false, true)
      .then(data => (data && data.cached ? discover(targetHostId, undefined, true) : null))
      .finally(() => { if (mountedRef.current) setStale(false); });
  }

  function closeStats() {
    if (statsRef.current) {
      statsRef.current.close();
      statsRef.current = null;
    }
  }

  // 采样只覆盖运行中的容器；容器集合变化时才需要重建连接，否则会因为
  // 每次 discover 产生新对象导致 SSE 反复断连。
  function runningNames(items) {
    return (items || []).filter(item => item.state === 'running').map(item => item.name);
  }

  let statsTargets = [];
  let statsQuery = null;
  if (view === 'project' && active) {
    statsTargets = runningNames(active.containers);
    statsQuery = {host_id: hostId, project: active.name, config_file: active.config_file};
  } else if (view === 'standalone') {
    statsTargets = runningNames(displayedContainers);
    statsQuery = {host_id: hostId, names: statsTargets.join(',')};
  }
  const statsUrl = statsTargets.length
    ? `/api/docker/stats/?${new URLSearchParams({...statsQuery, 'x-token': X_TOKEN}).toString()}`
    : '';
  // 容器集合变化（重启、扩缩容）时也要重连，让服务端重新解析采样目标
  const statsKey = statsUrl ? `${statsUrl}#${statsTargets.join(',')}` : '';

  useEffect(() => {
    closeStats();
    setStats({});
    if (!statsKey) return undefined;
    const es = new EventSource(statsUrl);
    statsRef.current = es;
    let failures = 0;
    es.onmessage = event => {
      failures = 0;
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'stats') setStats(data.stats || {});
      } catch (err) {
        // 忽略非法帧，等待下一次采样
      }
    };
    es.onerror = () => {
      // 浏览器会自动重连，但鉴权失败等场景会无限重试，连续失败则彻底停止
      failures += 1;
      if (failures >= 3) closeStats();
    };
    return () => {
      es.close();
      if (statsRef.current === es) statsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statsKey]);

  useEffect(() => {
    const box = editorBoxRef.current;
    if (!box || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(entries => {
      const height = Math.round(entries[0].contentRect.height);
      if (height > 0) setEditorHeight(height);
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, [activeTab, view, activeKey]);

  useEffect(() => {
    // 仅在用户本来就贴着底部时才自动滚动，否则会把正在往回翻的人拽回来
    const box = logBoxRef.current;
    if (box && stickBottomRef.current) box.scrollTop = box.scrollHeight;
  }, [logLines]);

  useEffect(() => {
    // 项目视图与独立容器视图的日志来源不同，切换时清空避免张冠李戴
    setLogLines([]);
    setLogService(undefined);
    setFollow(false);
  }, [view]);

  function closeLogStream() {
    if (logStreamRef.current) {
      logStreamRef.current.close();
      logStreamRef.current = null;
    }
    if (mountedRef.current) setFollowing(false);
  }

  // 跟随日志的目标：项目视图按服务（可为空表示全部），独立容器视图按容器名
  let logQuery = null;
  if (follow && view === 'project' && active) {
    logQuery = {host_id: hostId, project: active.name, config_file: active.config_file, tail};
    if (logService) logQuery.service = logService;
  } else if (follow && view === 'standalone' && logService) {
    logQuery = {host_id: hostId, name: logService, tail};
  }
  const logStreamUrl = logQuery
    ? `/api/docker/logs/?${new URLSearchParams({...logQuery, 'x-token': X_TOKEN}).toString()}`
    : '';

  useEffect(() => {
    closeLogStream();
    if (!logStreamUrl) return undefined;
    setLogLines([]);
    stickBottomRef.current = true;
    setFollowing(true);
    const es = new EventSource(logStreamUrl);
    logStreamRef.current = es;
    let failures = 0;
    es.onmessage = event => {
      failures = 0;
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (data.type === 'log') {
        setLogLines(prev => {
          const next = prev.concat(data.lines || []);
          // 超出上限时丢弃最早的行，保证长时间跟随不会撑爆内存
          return next.length > MAX_LOG_LINES ? next.slice(next.length - MAX_LOG_LINES) : next;
        });
      } else if (data.type === 'error') {
        message.error(data.message || t('日志流中断'));
        closeLogStream();
      }
      // done：服务端到达时限主动收尾，交给 EventSource 自动重连继续跟随
    };
    es.onerror = () => {
      failures += 1;
      if (failures >= 3) {
        message.error(t('日志流连接失败，已停止跟随'));
        setFollow(false);
      }
    };
    return () => {
      es.close();
      if (logStreamRef.current === es) logStreamRef.current = null;
      if (mountedRef.current) setFollowing(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logStreamUrl]);

  function invalidateOverview() {
    clearDockerCache(hostId, 'overview');
  }

  function target(project = active, file = selectedFile) {
    return {
      host_id: hostId,
      project: project.name,
      config_file: file || project.config_file,
    };
  }

  function loadConfig(project = active, file = selectedFile, force = false) {
    if (!project || !file) return;
    const cached = configCache.current[file];
    if (cached !== undefined && !force) {
      // 读取远程配置需要数秒，命中缓存可让来回切换项目保持即时响应。
      setConfigContent(cached);
      setSavedContent(cached);
      setConfigLoading(false);
      return;
    }
    const seq = ++configSeq.current;
    setConfigLoading(true);
    http.get('/api/docker/config/', {params: target(project, file)})
      .then(data => {
        if (seq !== configSeq.current) return;
        const content = data.content || '';
        configCache.current[file] = content;
        setConfigContent(content);
        setSavedContent(content);
      })
      .finally(() => {
        if (seq === configSeq.current) setConfigLoading(false);
      });
  }

  function selectConfig(file) {
    if (configContent !== savedContent) {
      Modal.confirm({
        title: t('存在未保存修改'),
        content: t('切换配置文件会丢弃当前修改，确认继续？'),
        onOk: () => {
          setSelectedFile(file);
          loadConfig(active, file);
        },
      });
      return;
    }
    setSelectedFile(file);
    loadConfig(active, file);
  }

  function saveConfig() {
    setRunning('save');
    http.post('/api/docker/config/', {...target(), content: configContent})
      .then(() => {
        if (!mountedRef.current) return;
        configCache.current[selectedFile] = configContent;
        setSavedContent(configContent);
        message.success(t('Compose 配置已校验并保存'));
      })
      .finally(() => { if (mountedRef.current) setRunning(''); });
  }

  function removeProject() {
    let deleteFiles = false;
    Modal.confirm({
      title: t('删除项目【{}】', active.name),
      okText: t('删除'),
      okButtonProps: {danger: true},
      content: (
        <div>
          <p>{t('将执行 docker compose down --volumes，停止并移除该项目的容器、网络和数据卷。')}</p>
          <Checkbox onChange={event => { deleteFiles = event.target.checked; }}>
            {t('同时删除服务器上的 compose 配置文件')}
          </Checkbox>
        </div>
      ),
      onOk: () => {
        setRunning('remove:');
        return http.post('/api/docker/remove/', {
          ...target(), delete_files: deleteFiles,
        }, {timeout: 620000})
          .then(() => {
            invalidateOverview();
            message.success(t('项目已删除'));
            if (!mountedRef.current) return;
            setActiveKey(undefined);
            setLogLines([]);
            return discover(hostId);
          })
          .finally(() => { if (mountedRef.current) setRunning(''); });
      },
    });
  }

  function action(actionName, service) {
    const executeAction = () => {
      setRunning(`${actionName}:${service || ''}`);
      const seq = ++logsSeq.current;
      const requestKey = activeKey;
      return http.post('/api/docker/action/', {
        ...target(), action: actionName, service, tail,
      }, {timeout: 920000})
        .then(data => {
          if (actionName === 'logs') {
            // 丢弃过期响应：连续点击不同服务时，早发出的请求可能后返回。
            if (seq !== logsSeq.current || requestKey !== activeKey) return;
            setLogLines((data.output || '').split('\n'));
          } else {
            invalidateOverview();
            message.success(t('操作成功'));
            return discover(hostId, activeKey, true);
          }
        })
        .finally(() => { if (mountedRef.current) setRunning(''); });
    };
    if (actionName === 'down') {
      Modal.confirm({
        title: t('停止并移除项目容器'),
        content: t('将执行 docker compose down，确认继续？'),
        okButtonProps: {danger: true},
        onOk: executeAction,
      });
      return;
    }
    executeAction();
  }

  /** 独立容器的受限操作：只有启停、重启和日志，没有 compose 类动作。 */
  function containerAction(actionName, name) {
    const execute = () => {
      const seq = ++logsSeq.current;
      setRunning(`${actionName}:${name}`);
      return http.post('/api/docker/container/', {
        host_id: hostId, name, action: actionName, tail,
      }, {timeout: 320000})
        .then(data => {
          if (actionName === 'logs') {
            if (seq !== logsSeq.current) return null;
            setLogLines((data.output || '').split('\n'));
            return null;
          }
          invalidateOverview();
          message.success(t('操作成功'));
          return discover(hostId, activeKey, true);
        })
        .finally(() => { if (mountedRef.current) setRunning(''); });
    };
    if (actionName === 'stop') {
      Modal.confirm({
        title: t('停止容器【{}】', name),
        content: t('该容器不由 Docker Compose 管理，停止后需要手动或在此页面重新启动。'),
        okButtonProps: {danger: true},
        onOk: execute,
      });
      return;
    }
    if (actionName === 'remove') {
      const item = standalone.find(one => one.name === name) || {};
      Modal.confirm({
        title: t('删除容器【{}】', name),
        okText: t('删除'),
        okButtonProps: {danger: true},
        content: (
          <div>
            <p>{t('将执行 docker rm -f，{}容器会被直接移除。', item.state === 'running' ? t('运行中的') : '')}</p>
            <p>{t('该容器不由 Compose 管理，Moon 没有它的启动参数，删除后无法在此页面重建。')}</p>
            <p className={styles.hintMuted}>
              {t('镜像和具名数据卷会保留，如需清理请到「镜像管理」或「存储管理」中操作。')}
            </p>
          </div>
        ),
        onOk: execute,
      });
      return;
    }
    execute();
  }

  function managedContainerAction(actionName, item) {
    const seq = ++logsSeq.current;
    setRunning(`${actionName}:${item.name}`);
    return http.post('/api/docker/container/', {
      host_id: hostId, name: item.name, action: actionName, tail,
    }, {timeout: 320000})
      .then(data => {
        if (actionName === 'logs') {
          if (seq === logsSeq.current) setLogLines((data.output || '').split('\n'));
          return null;
        }
        invalidateOverview();
        message.success(t('操作成功'));
        return discover(hostId, activeKey, true);
      })
      .finally(() => { if (mountedRef.current) setRunning(''); });
  }

  function unifiedContainerAction(actionName, item) {
    if (item.managed) return managedContainerAction(actionName, item);
    return containerAction(actionName, item.name);
  }

  function selectLogTarget(value) {
    logsSeq.current += 1;
    setLogService(value);
    setLogLines([]);
  }

  function selectProject(item) {
    if (configContent !== savedContent) {
      Modal.confirm({
        title: t('存在未保存修改'),
        content: t('切换项目会丢弃当前修改，确认继续？'),
        onOk: () => { setView('project'); setActiveKey(projectKey(item)); },
      });
      return;
    }
    setView('project');
    setActiveKey(projectKey(item));
  }

  function refreshProjects() {
    const run = () => {
      configCache.current = {};
      // 保留当前列表与选中项，刷新期间界面不闪烁
      discover(hostId, activeKey, true);
    };
    if (configContent !== savedContent) {
      Modal.confirm({
        title: t('存在未保存修改'),
        content: t('刷新会丢弃当前修改，确认继续？'),
        onOk: run,
      });
      return;
    }
    run();
  }

  function renderUsage(item, field) {
    const stat = stats[item.name];
    if (item.state !== 'running') return <span className={styles.usageIdle}>-</span>;
    if (!stat) return <span className={styles.usageIdle}>{t('采样中')}</span>;
    if (field === 'cpu') return <span className={styles.usageValue}>{stat.cpu || '-'}</span>;
    return (
      <div className={styles.usageMem}>
        <span>{stat.mem || '-'}</span>
        <small>{stat.mem_percent || ''}</small>
      </div>
    );
  }

  const canOperate = hasPermission('docker.project.do');
  const canRemove = hasPermission('docker.project.del');
  const stateColumn = {
    title: t('状态'), dataIndex: 'state', width: 110,
    render: value => <Tag color={value === 'running' ? 'green' : 'red'}>{value}</Tag>,
  };
  const usageColumns = [
    {title: 'CPU', key: 'cpu', width: 90, render: (_, item) => renderUsage(item, 'cpu')},
    {title: t('内存'), key: 'mem', width: 180, render: (_, item) => renderUsage(item, 'mem')},
  ];
  const portColumn = {
    title: t('端口'), dataIndex: 'ports', width: 200,
    render: value => value?.join(', ') || '-',
  };

  const columns = [
    {title: t('服务'), dataIndex: 'service', width: 150, render: value => <strong>{value}</strong>},
    {title: t('容器'), dataIndex: 'name', ellipsis: true},
    {title: t('镜像'), dataIndex: 'image', ellipsis: true},
    stateColumn,
    ...usageColumns,
    portColumn,
    {title: t('操作'), width: 170, render: (_, item) => (
      <Space size={4}>
        <Tooltip title={t('查看日志')}><Button type="text" icon={<FileTextOutlined/>} onClick={() => {
          setActiveTab('logs');
          selectLogTarget(item.service);
          // 跟随中只需切换目标，日志流会自动重连；否则拉一次静态日志
          if (!follow) action('logs', item.service);
        }}/></Tooltip>
        <Tooltip title={t('重启')}><Button type="text" icon={<RedoOutlined/>} disabled={writeBusy || !canOperate} onClick={() => action('restart', item.service)}/></Tooltip>
        <Tooltip title={t('重新构建')}><Button type="text" icon={<DockerOutlined/>} disabled={writeBusy || !canOperate} onClick={() => action('rebuild', item.service)}/></Tooltip>
      </Space>
    )},
  ];

  const standaloneColumns = [
    {title: t('容器'), dataIndex: 'name', ellipsis: true, render: (value, item) => (
      <Space size={6}>
        <strong>{value}</strong>
        {item.managed && <Tag color="blue">Compose</Tag>}
        {item.partial_labels && (
          <Tooltip title={t('该容器带有残缺的 Compose 标签（project={}），缺少配置文件路径，无法用 Compose 管理。建议重建时去掉这些标签。', item.project || '-')}>
            <Tag color="orange">{t('标签残缺')}</Tag>
          </Tooltip>
        )}
      </Space>
    )},
    {title: t('镜像'), dataIndex: 'image', ellipsis: true},
    stateColumn,
    ...usageColumns,
    portColumn,
    {title: t('操作'), width: 170, render: (_, item) => (
      <Space size={4}>
        <Tooltip title={t('查看日志')}><Button type="text" icon={<FileTextOutlined/>}
          onClick={() => {
            selectLogTarget(item.name);
            if (!follow) unifiedContainerAction('logs', item);
          }}/></Tooltip>
        {item.state === 'running' ? (
          <Tooltip title={t('停止')}><Button type="text" danger icon={<StopOutlined/>}
            disabled={writeBusy || !canOperate} onClick={() => unifiedContainerAction('stop', item)}/></Tooltip>
        ) : (
          <Tooltip title={t('启动')}><Button type="text" icon={<CaretRightOutlined/>}
            disabled={writeBusy || !canOperate} onClick={() => unifiedContainerAction('start', item)}/></Tooltip>
        )}
        <Tooltip title={t('重启')}><Button type="text" icon={<RedoOutlined/>}
          disabled={writeBusy || !canOperate || item.state !== 'running'}
          onClick={() => unifiedContainerAction('restart', item)}/></Tooltip>
        {!item.managed && (
          <Tooltip title={canRemove ? t('删除容器') : t('无删除权限')}>
            <Button type="text" danger icon={<DeleteOutlined/>}
              loading={running === `remove:${item.name}`}
              disabled={writeBusy || !canRemove}
              onClick={() => containerAction('remove', item.name)}/>
          </Tooltip>
        )}
      </Space>
    )},
  ];

  const exitedContainers = standalone.filter(item => item.state !== 'running');

  /** 批量清理已停止的独立容器：rollback-xxx 之类的残留往往攒了一堆 */
  function pruneExited() {
    Modal.confirm({
      title: t('清理 {} 个已停止的容器', exitedContainers.length),
      okText: t('全部删除'),
      okButtonProps: {danger: true},
      content: (
        <div>
          <p>{t('将逐个执行 docker rm -f，仅涉及非运行状态的独立容器：')}</p>
          <pre className={styles.pruneList}>{exitedContainers.map(item => item.name).join('\n')}</pre>
          <p className={styles.hintMuted}>{t('镜像和具名数据卷会保留。')}</p>
        </div>
      ),
      onOk: async () => {
        setRunning('remove:batch');
        const failed = [];
        try {
          // 串行执行：并发删除会同时抢主机上的 docker 守护进程锁
          for (const item of exitedContainers) {
            try {
              await http.post('/api/docker/container/', {
                host_id: hostId, name: item.name, action: 'remove',
              }, {timeout: 320000});
            } catch (err) {
              failed.push(item.name);
            }
          }
        } finally {
          setRunning('');
        }
        invalidateOverview();
        if (failed.length) message.warning(t('{} 个容器删除失败', failed.length));
        else message.success(t('清理完成'));
        return discover(hostId, activeKey, true);
      },
    });
  }

  // 日志面板在两种视图下复用：项目视图按服务过滤，独立容器视图按容器名
  const isStandalone = view === 'standalone';
  const logOptions = isStandalone
    ? displayedContainers.map(item => ({value: item.name, label: item.name}))
    : (active?.containers || []).map(item => ({value: item.service, label: item.service}));

  function reloadLogs() {
    if (!logService) return;
    if (isStandalone) {
      const item = displayedContainers.find(value => value.name === logService);
      if (item) unifiedContainerAction('logs', item);
    } else {
      action('logs', logService);
    }
  }

  // 独立容器必须先选中一个才能跟随，项目视图不选则跟随全部服务
  const canFollow = isStandalone ? Boolean(logService) : Boolean(active);
  const logPlaceholder = follow
    ? t('正在等待日志输出…')
    : (isStandalone ? t('选择容器后加载或开启实时跟随') : t('选择服务并加载日志'));
  const normalizedKeyword = logKeyword.trim().toLowerCase();
  const visibleLogLines = normalizedKeyword
    ? logLines.filter(line => line.toLowerCase().includes(normalizedKeyword))
    : logLines;
  const visibleLogText = visibleLogLines.length
    ? visibleLogLines.join('\n')
    : (normalizedKeyword && logLines.length ? t('没有匹配的日志') : logPlaceholder);

  const logPane = (
    <div className={styles.logs}>
      <div className={styles.logToolbar}>
        <Select allowClear value={logService} style={{width: 200}}
                placeholder={isStandalone ? t('选择容器') : t('全部服务')}
                onChange={selectLogTarget}
                options={logOptions}/>
        <Select value={tail} style={{width: 130}} onChange={setTail}
                options={[100, 200, 500, 1000, 2000].map(value => ({value, label: `${value} lines`}))}/>
        <Input allowClear value={logKeyword} prefix={<SearchOutlined/>} className={styles.logSearch}
               placeholder={t('搜索日志')} onChange={event => setLogKeyword(event.target.value)}/>
        <Button icon={<ReloadOutlined/>} loading={running.startsWith('logs:')}
                disabled={follow || (isStandalone && !logService)}
                onClick={isStandalone ? reloadLogs : () => action('logs', logService)}>
          {t('加载日志')}
        </Button>
        <Tooltip title={canFollow ? '' : t('请先选择容器')}>
          <Button type={follow ? 'primary' : 'default'} danger={follow}
                  icon={follow ? <PauseOutlined/> : <PlayCircleOutlined/>}
                  disabled={!canFollow} onClick={() => setFollow(!follow)}>
            {follow ? t('停止跟随') : t('实时跟随')}
          </Button>
        </Tooltip>
        {follow && (
          <Tag color={following ? 'green' : 'orange'} className={styles.followTag}>
            {following ? t('实时') : t('连接中')}
          </Tag>
        )}
        <Checkbox checked={logWrap} onChange={e => setLogWrap(e.target.checked)}
                  className={styles.logWrap}>{t('自动换行')}</Checkbox>
        <span className={styles.logCount}>
          {normalizedKeyword ? t('{} / {} 行', visibleLogLines.length, logLines.length) : t('{} 行', logLines.length)}
        </span>
      </div>
      <pre ref={logBoxRef} className={logWrap ? styles.logWrapOn : styles.logWrapOff}
           onScroll={event => {
             const box = event.target;
             stickBottomRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
           }}>
        {visibleLogText}
      </pre>
    </div>
  );

  const tabItems = [];
  if (hasPermission('docker.project.edit')) {
    tabItems.push({key: 'compose', label: 'Docker Compose', children: (
      <Spin spinning={configLoading} wrapperClassName={styles.paneSpin}>
        <div className={styles.pane}>
          <div className={styles.configBar}>
            <Select value={selectedFile} style={{minWidth: 360, maxWidth: '70%'}}
                    options={(active?.config_files || []).map(file => ({value: file, label: file}))}
                    onChange={selectConfig}/>
            <Space>
              <Button icon={<ReloadOutlined/>} onClick={() => loadConfig(active, selectedFile, true)}>{t('重新读取')}</Button>
              <Button type="primary" icon={<SaveOutlined/>} loading={running === 'save'}
                      disabled={writeBusy || configContent === savedContent} onClick={saveConfig}>{t('保存配置')}</Button>
            </Space>
          </div>
          <div ref={editorBoxRef} className={styles.editorBox}>
            <ACEditor mode="text" theme="one_dark" value={configContent}
                      width="100%" height={`${editorHeight}px`} showPrintMargin={false}
                      onChange={setConfigContent}/>
          </div>
        </div>
      </Spin>
    )});
  }
  tabItems.push({key: 'logs', label: t('日志'), children: logPane});

  return (
    <div className={styles.page}>
      <Prompt when={configContent !== savedContent}
              message={t('离开项目管理会丢弃未保存的配置修改，确认继续？')}/>
      <aside className={styles.sidebar}>
        <div className={styles.sidebarHeader}><div><DockerOutlined/> {t(initialView === 'standalone' ? '容器' : 'Compose 项目')}</div></div>
        <div className={styles.listHeader}>
          <span>{t(isContainerWorkspace ? '容器' : '项目')}{stale && (projects.length || standalone.length) ? ` · ${t('刷新中')}` : ''}</span>
          <Space size={2}>
            {!isContainerWorkspace && hasPermission('docker.project.add') && (
              <Button type="text" size="small" icon={<PlusOutlined/>} disabled={!hostId}
                      title={t('新建项目')} onClick={() => setCreateOpen(true)}/>
            )}
            <Button type="text" size="small" icon={<ReloadOutlined/>} loading={fetching}
                    disabled={hostId === undefined} title={t('刷新')} onClick={refreshProjects}/>
          </Space>
        </div>
        <Spin spinning={fetching && !projects.length && !standalone.length} wrapperClassName={styles.projectSpin}>
          <div className={styles.projectList}>
            {isContainerWorkspace ? displayedContainers.map(item => (
              <button key={item.name} className={logService === item.name ? styles.activeProject : styles.project}
                      onClick={() => {
                        selectLogTarget(item.name);
                        if (!follow) unifiedContainerAction('logs', item);
                      }}>
                <span>{item.name}</span><small>{item.image} · {item.state}</small>
              </button>
            )) : projects.map(item => (
              <button key={projectKey(item)} className={view === 'project' && projectKey(item) === activeKey ? styles.activeProject : styles.project}
                      onClick={() => selectProject(item)}>
                <span>{item.name}</span><small>{item.containers.length} containers · {item.workdir}</small>
              </button>
            ))}
            {!fetching && !(isContainerWorkspace ? displayedContainers.length : projects.length) && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={hostId === undefined ? t('请先选择服务器') : t(isContainerWorkspace ? '该服务器暂无容器' : '该服务器暂无项目')}/>}
          </div>
        </Spin>
        {!isContainerWorkspace && (
          <div className={styles.resourceNav}>
            <button disabled={!hostId}
                    className={view === 'standalone' ? styles.activeProject : styles.project}
                    onClick={() => setView('standalone')}>
              <span>{t('独立容器')} ({standalone.length})</span>
            </button>
          </div>
        )}
      </aside>
      <main className={styles.content}>
        {view === 'standalone' ? (
          <>
            <header className={styles.header}>
              <div>
                <h2>{t(isContainerWorkspace ? '容器' : '独立容器')}</h2>
                <span>{hosts.find(item => item.id === hostId)?.name}</span>
              </div>
              <Space>
                <Button icon={<ReloadOutlined/>} loading={fetching} onClick={refreshProjects}>{t('刷新')}</Button>
                {canRemove && exitedContainers.length > 0 && (
                  <Button danger icon={<ClearOutlined/>} loading={running === 'remove:batch'}
                          disabled={writeBusy} onClick={pruneExited}>
                    {t('清理已停止 ({})', exitedContainers.length)}
                  </Button>
                )}
                {!isContainerWorkspace && <Button onClick={() => setView('project')}>{t('返回项目')}</Button>}
              </Space>
            </header>
            {!isContainerWorkspace && (
              <section className={styles.toolbar}>
                <Alert type="info" showIcon
                       message={t('这些容器不由 Docker Compose 管理（docker run 启动，或 Compose 标签残缺）。Moon 没有它们的启动参数，删除后无法在此页面重建。')}/>
              </section>
            )}
            <section className={styles.containers}>
              <Table size="small" rowKey="name" pagination={false} columns={standaloneColumns}
                     dataSource={displayedContainers} scroll={{x: 1180}}
                     locale={{emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
                                                description={t(isContainerWorkspace ? '该服务器暂无容器' : '该服务器上所有容器都由 Compose 管理')}/>}}/>
            </section>
            <section className={styles.editorArea}>
              <Tabs activeKey="logs" items={[{key: 'logs', label: t('日志'), children: logPane}]}
                    className={styles.fullTabs}/>
            </section>
          </>
        ) : !active ? (
          <Empty description={hostId === undefined ? t('请先选择服务器') : t('该服务器没有 Compose 项目')}>
            {standalone.length > 0 && (
              <Button type="primary" onClick={() => setView('standalone')}>
                {t('查看 {} 个独立容器', standalone.length)}
              </Button>
            )}
          </Empty>
        ) : (
          <>
            <header className={styles.header}>
              <div><h2>{active.name}</h2><span>{active.workdir}</span></div>
              <Space>
                <Button icon={<ReloadOutlined/>} loading={fetching} onClick={refreshProjects}>{t('刷新')}</Button>
                {hasPermission('docker.project.del') && (
                  <Button danger icon={<DeleteOutlined/>} loading={running.startsWith('remove:')}
                          disabled={writeBusy} onClick={removeProject}>{t('删除项目')}</Button>
                )}
              </Space>
            </header>
            <section className={styles.toolbar}>
              <Space wrap>
                <Button type="primary" icon={<CaretRightOutlined/>} loading={running.startsWith('publish:')}
                        disabled={writeBusy || !hasPermission('docker.project.do')} onClick={() => action('publish')}>{t('拉取并发布')}</Button>
                <Button icon={<DockerOutlined/>} loading={running.startsWith('rebuild:')}
                        disabled={writeBusy || !hasPermission('docker.project.do')} onClick={() => action('rebuild')}>{t('全部重建')}</Button>
                <Button icon={<RedoOutlined/>} loading={running.startsWith('restart:')}
                        disabled={writeBusy || !hasPermission('docker.project.do')} onClick={() => action('restart')}>{t('重启项目')}</Button>
                <Button danger icon={<StopOutlined/>} disabled={writeBusy || !hasPermission('docker.project.do')}
                        onClick={() => action('stop')}>{t('停止项目')}</Button>
              </Space>
            </section>
            <section className={styles.containers}>
              <Table size="small" rowKey="name" pagination={false} columns={columns}
                     dataSource={active.containers} scroll={{x: 1180}}/>
            </section>
            {!hasPermission('docker.project.edit') && (
              <Alert type="info" showIcon message={t('当前角色仅可查看容器状态和日志')}/>
            )}
            <section className={styles.editorArea}>
              <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems}
                    className={styles.fullTabs}/>
            </section>
          </>
        )}
      </main>
      <CreateProject open={createOpen} hostId={hostId} onClose={() => setCreateOpen(false)}
                     onCreated={result => {
                       invalidateOverview();
                       setCreateOpen(false);
                       discover(hostId, `${result.name}|${result.workdir}|${result.config_file}`);
                     }}/>
    </div>
  );
}

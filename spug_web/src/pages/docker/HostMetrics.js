import React, {useEffect, useState} from 'react';
import {Chart, Geom, Axis, Tooltip} from 'bizcharts';
import {http, t} from 'libs';
import styles from './index.module.less';

export const METRICS_TTL = 60000;
export const POLL_INTERVAL = 5000;
const cache = new Map();

export function readMetricsCache(hostId) {
  const now = Date.now();
  cache.forEach((entry, key) => { if (now >= entry.expires) cache.delete(key); });
  return cache.get(hostId)?.value;
}

function remember(hostId, value) {
  readMetricsCache(hostId);
  // Bound memory even if many hosts are visited within a minute.
  if (cache.size >= 50) cache.delete(cache.keys().next().value);
  cache.set(hostId, {value, expires: Date.now() + METRICS_TTL});
}

export default function HostMetrics({hostId}) {
  const [entry, setEntry] = useState(() => ({hostId, data: readMetricsCache(hostId)}));
  const [clock, setClock] = useState(Date.now());
  const [failed, setFailed] = useState(false);
  const data = entry.hostId === hostId ? entry.data : readMetricsCache(hostId);

  useEffect(() => {
    let disposed = false;
    let pending = false;
    let timer;
    setEntry({hostId, data: readMetricsCache(hostId)});
    setFailed(false);
    async function poll() {
      if (disposed || pending || document.hidden) return;
      pending = true;
      try {
        const result = await http.get('/api/host/metrics/overview/', {params: {id: hostId}, timeout: 40000});
        if (disposed || result?.host_id !== hostId || !Array.isArray(result.history)) return;
        const value = {...result, history: result.history.slice(-61), receivedAt: Date.now()};
        remember(hostId, value);
        setEntry({hostId, data: value});
        setFailed(Boolean(value.error));
      } catch (error) {
        if (!disposed) setFailed(true);
      } finally {
        pending = false;
        if (!disposed && !document.hidden) timer = setTimeout(poll, POLL_INTERVAL);
      }
    }
    function visibility() {
      clearTimeout(timer);
      if (!document.hidden) poll();
    }
    // Expiration status advances even while an HTTP request is pending.
    const ticker = setInterval(() => {
      readMetricsCache(hostId);
      setClock(Date.now());
    }, 1000);
    document.addEventListener('visibilitychange', visibility);
    poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
      clearInterval(ticker);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [hostId]);

  // Use server age + local elapsed time, tolerating client/server clock skew.
  const age = data?.sampled_at ? (data.server_time - data.sampled_at) * 1000 + Math.max(0, clock - data.receivedAt) : Infinity;
  const expired = age >= METRICS_TTL;
  const history = expired ? [] : (data?.history || []);
  const latest = history[history.length - 1];
  const status = failed || data?.error ? '不可用' : data?.sampled_at && age > POLL_INTERVAL
    ? '数据已过期 · 更新中' : !latest ? '采集中' : '实时';
  const charts = [
    {key: 'cpu', label: 'CPU', value: latest?.cpu},
    {key: 'memory', label: '内存', value: latest?.memory},
    {key: 'gpu', label: 'GPU', value: latest?.gpu?.length ? Math.max(...latest.gpu.map(g => g.value)) : null},
  ];
  return <section aria-label={t('服务器实时指标')}>
    <div className={styles.hostMetricsHeader}>
      <strong>{t('服务器实时指标')}</strong>
      <span>{t(status)} · {t('每 5 秒采样')}{data?.sampled_at ? ` · ${t('更新时间')} ${new Date(data.sampled_at * 1000).toLocaleTimeString()}` : ''}</span>
    </div>
    <div className={styles.hostMetricsGrid}>
      {charts.map(metric => {
        const gpuIds = [...new Set(history.flatMap(point => (point.gpu || []).map(g => g.id)))];
        const points = history.flatMap(point => metric.key === 'gpu'
          ? gpuIds.map(id => ({time: point.ts * 1000, value: point.gpu?.find(g => g.id === id)?.value ?? null, series: `GPU ${id}`}))
          : [{time: point.ts * 1000, value: point[metric.key] ?? null, series: metric.label}]);
        const available = points.some(point => Number.isFinite(point.value));
        const missing = metric.key === 'gpu' && latest?.gpu_status === 'absent' ? '未检测到 GPU'
          : metric.key === 'cpu' && latest && latest.cpu == null && !failed ? '采集中' : '不可用';
        return <div className={styles.hostMetricChart} key={metric.key}>
          <div className={styles.hostMetricsHeader}><strong>{metric.label}</strong>
            <span>{metric.key === 'gpu' && Number.isFinite(metric.value) ? `${t('最高')} ` : ''}{Number.isFinite(metric.value) ? `${metric.value}%` : t(missing)}</span></div>
          {available ? <Chart height={170} data={points} forceFit padding={[15, 15, 35, 40]}
            scale={{time: {type: 'time', mask: 'HH:mm:ss', tickCount: 3}, value: {min: 0, max: 100, alias: '%'}}}>
            <Axis name="time" label={{autoRotate: false}}/><Axis name="value"/><Tooltip/>
            <Geom type="line" position="time*value" color="series" size={2} connectNulls={false}/>
            <Geom type="point" position="time*value" color="series" size={2}/>
          </Chart> : <div className={styles.hostMetricEmpty}>{t(!latest && !failed ? '采集中' : missing)}</div>}
        </div>;
      })}
    </div>
  </section>;
}

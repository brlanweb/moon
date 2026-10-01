import {t} from 'libs';

export const resourceMetrics = {
  cpu: t('CPU使用率'),
  memory: t('内存使用率'),
  disk: t('磁盘使用率'),
  temperature: t('温度'),
};

export function resourceDefaults(metric = 'cpu') {
  return {metric, operator: 'gte', value: metric === 'temperature' ? 85 : 80, mount: ''};
}

export function validResource(targets, extra) {
  return Array.isArray(targets) && targets.length > 0 &&
    targets.every(id => Number.isSafeInteger(id) && id > 0) &&
    extra && Object.prototype.hasOwnProperty.call(resourceMetrics, extra.metric) &&
    extra.operator === 'gte' && Number.isFinite(extra.value) && extra.value >= 0 &&
    extra.value <= (extra.metric === 'temperature' ? 250 : 100) &&
    (extra.mount === undefined || typeof extra.mount === 'string');
}

export function resourceThreshold(extra) {
  if (!extra) return '---';
  const unit = extra.metric === 'temperature' ? '\u00b0C' : '%';
  const mount = extra.metric === 'disk' ? ` (${extra.mount || t('最高使用率')})` : '';
  return `${resourceMetrics[extra.metric] || extra.metric} >= ${extra.value}${unit}${mount}`;
}

export function resourceTargets(record) {
  return (record.targets || []).map(id => record.target_names?.[String(id)] || `#${id}`).join(', ');
}

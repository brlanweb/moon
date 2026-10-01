import React from 'react';
import {Form, Input, InputNumber, Select} from 'antd';
import {t} from 'libs';
import {resourceDefaults, resourceMetrics} from './resource';

export default function ResourceFields({value, onChange}) {
  const extra = value || resourceDefaults();
  const temperature = extra.metric === 'temperature';
  return (
    <React.Fragment>
      <Form.Item required label={t('资源指标')}>
        <Select value={extra.metric} onChange={metric => onChange(resourceDefaults(metric))}>
          {Object.entries(resourceMetrics).map(([metric, label]) => (
            <Select.Option key={metric} value={metric}>{label}</Select.Option>
          ))}
        </Select>
      </Form.Item>
      <Form.Item required label={t('资源阈值')}>
        <InputNumber
          aria-label={t('资源阈值')}
          min={0}
          max={temperature ? 250 : 100}
          value={extra.value}
          addonBefore=">="
          addonAfter={temperature ? '\u00b0C' : '%'}
          style={{width: '100%'}}
          onChange={value => onChange({...extra, operator: 'gte', value})}/>
      </Form.Item>
      {extra.metric === 'disk' && (
        <Form.Item label={t('磁盘挂载点')}>
          <Input
            value={extra.mount || ''}
            placeholder={t('留空使用最高使用率')}
            onChange={e => onChange({...extra, mount: e.target.value})}/>
        </Form.Item>
      )}
    </React.Fragment>
  );
}

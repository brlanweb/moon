import React from 'react';
import { Tooltip } from 'antd';
import { t } from 'libs';

const Tips1 = (
  <span>{t('内置全局变量')}</span>
)

const Tips2 = (
  <Tooltip title={t('配置中心应用的配置将会以 _MOON_标识符_Key 方式组合成环境变量，可通过执行 env | grep MOON 来查看所有的内置的和配置中心的可使用变量。')}>
    <span style={{color: '#28786f'}}>{t('配置中心的配置变量')}</span>
  </Tooltip>
)

export default (
  <span>{t('可使用 ')}{Tips1}{t(' 和 ')}{Tips2}</span>
)
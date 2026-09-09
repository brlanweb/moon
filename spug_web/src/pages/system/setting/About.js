/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import styles from './index.module.css';
import {Descriptions, Spin, Alert} from 'antd';
import {http, VERSION, t} from 'libs';

export default class About extends React.Component {
  state = {fetching: true, info: {}};
  active = false;

  componentDidMount() {
    this.active = true;
    http.get('/api/setting/about/')
      .then(info => { if (this.active) this.setState({info}); })
      .catch(() => {})
      .finally(() => { if (this.active) this.setState({fetching: false}); });
  }

  componentWillUnmount() { this.active = false; }

  render() {
    const {info, fetching} = this.state;
    return (
      <Spin spinning={fetching}>
        <div className={styles.title}>{t('关于')} Moon</div>
        <Descriptions column={1}>
          <Descriptions.Item label={t('操作系统')}>{info.system_version}</Descriptions.Item>
          <Descriptions.Item label={t('Python版本')}>{info.python_version}</Descriptions.Item>
          <Descriptions.Item label={t('Django版本')}>{info.django_version}</Descriptions.Item>
          <Descriptions.Item label={t('Moon API版本')}>{info.spug_version}</Descriptions.Item>
          <Descriptions.Item label={t('Moon Web版本')}>{VERSION}</Descriptions.Item>
          <Descriptions.Item label={t('项目源码')}>
            <a href="https://github.com/brlanweb/moon" target="_blank" rel="noopener noreferrer">Moon</a>
          </Descriptions.Item>
          <Descriptions.Item label={t('许可证')}>
            <a href="https://github.com/brlanweb/moon" target="_blank" rel="noopener noreferrer">AGPL-3.0</a>
          </Descriptions.Item>
          <Descriptions.Item label={t('上游项目')}>
            <a href="https://github.com/openspug/spug" target="_blank" rel="noopener noreferrer">OpenSpug</a>
          </Descriptions.Item>
        </Descriptions>
        {!fetching && info.spug_version && info.spug_version !== VERSION && (
          <Alert showIcon style={{maxWidth: 500}} type="warning"
                 message={t('Moon API版本与Web版本不匹配，请尝试刷新浏览器后再次查看。')}/>
        )}
      </Spin>
    );
  }
}

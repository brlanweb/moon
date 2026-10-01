import React from 'react';
import {Layout} from 'antd';
import {GithubOutlined} from '@ant-design/icons';
import {t} from 'libs';
import styles from './layout.module.less';

export default function Footer() {
  return (
    <Layout.Footer style={{padding: 0}}>
      <div className={styles.footer}>
        <div className={styles.links}>
          <a className={styles.item} href="https://github.com/brlanweb/moon" target="_blank" rel="noopener noreferrer">
            <GithubOutlined style={{marginRight: 6}}/>{t('项目源码')}
          </a>
        </div>
        <div style={{color: 'rgba(0, 0, 0, .45)'}}>Moon / {new Date().getFullYear()}</div>
      </div>
    </Layout.Footer>
  );
}

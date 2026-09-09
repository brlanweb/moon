/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Breadcrumb } from 'antd';
import styles from './index.module.less';


export default class extends React.Component {
  static Item = Breadcrumb.Item

  render() {
    // 条件渲染会产生 false/null，不能直接读取最后一个原始子项的 props。
    const children = React.Children.toArray(this.props.children).filter(React.isValidElement);
    let title = this.props.title;
    if (!title && children.length) {
      title = children[children.length - 1].props.children
    }

    return (
      <div className={styles.breadcrumb}>
        <Breadcrumb>
          {children}
        </Breadcrumb>
        {this.props.extra ? (
          <div className={styles.title}>
            <span>{title}</span>
            {this.props.extra}
          </div>
        ) : null}
      </div>
    )
  }
}
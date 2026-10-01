import React from 'react';
import { Card, List } from 'antd';
import { t } from 'libs';

function TodoIndex(props) {
  return (
    <Card title={t('待办事项')} bodyStyle={{height: 234, padding: '0 24px'}}>
      <List/>
    </Card>
  )
}

export default TodoIndex
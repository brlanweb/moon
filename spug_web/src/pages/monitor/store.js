/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, computed } from 'mobx';
import { http, includes } from 'libs';
import moment from 'moment';
import lds from 'lodash';
import {resourceDefaults} from './resource';

class Store {
  autoReload = null;
  @observable records = [];
  @observable record = {};
  @observable types = [];
  @observable groups = [];
  @observable overviews = [];
  @observable page = 0;
  @observable isFetching = false;
  @observable formVisible = false;
  @observable ovFetching = false;

  @observable f_name;
  @observable f_type;
  @observable f_active = '';
  @observable f_group;

  @computed get dataSource() {
    let records = this.records;
    if (this.f_active) records = records.filter(x => x.is_active === (this.f_active === '1'));
    if (this.f_name) records = records.filter(x => includes(x.name, this.f_name));
    if (this.f_type) records = records.filter(x => x.type_alias === this.f_type);
    if (this.f_group) records = records.filter(x => x.group === this.f_group);
    return records
  }

  @computed get ovDataSource() {
    let records = this.overviews;
    if (this.f_type) {
      // 兼容尚未重载的新旧接口，按稳定的监控 ID 回退到列表中的展示类型。
      const types = new Map(this.records.map(item => [String(item.id), item.type_alias]));
      records = records.filter(x =>
        (x.type_alias || types.get(String(x.id).split('_')[0]) || x.type) === this.f_type);
    }
    if (this.f_group) records = records.filter(x => x.group === this.f_group);
    if (this.f_name) records = records.filter(x => includes(x.name, this.f_name));
    return records
  }

  recordsFor = (resourceOnly = false) => this.dataSource.filter(x => (x.type === '7') === resourceOnly);

  overviewsFor = (resourceOnly = false) => {
    // Overview types are translated labels; join the stable detection ID instead.
    const ids = new Set(this.records.filter(x => (x.type === '7') === resourceOnly).map(x => String(x.id)));
    return this.ovDataSource.filter(x => ids.has(String(x.id).split('_')[0]));
  };

  typesFor = (resourceOnly = false) => Array.from(new Set(
    this.records.filter(x => (x.type === '7') === resourceOnly).map(x => x.type_alias)
  ));

  @computed get cascaderOptions() {
    let data = {}
    for (let i of this.records) {
      const tmp = {value: i.id, label: i.name}
      if (data[i.group]) {
        data[i.group]['children'].push(tmp)
      } else {
        data[i.group] = {value: i.group, label: i.group, children: [tmp]}
      }
    }
    return Object.values(data)
  }

  fetchRecords = () => {
    this.isFetching = true;
    return http.get('/api/monitor/')
      .then(({groups, detections}) => {
        const tmp = new Set();
        detections.map(item => {
          tmp.add(item['type_alias']);
          const value = item['latest_run_time'];
          item['latest_run_time_alias'] = value ? moment(value).fromNow() : null;
          return null
        });
        this.types = Array.from(tmp);
        this.records = detections;
        this.groups = groups;
      })
      .finally(() => this.isFetching = false)
  };

  fetchOverviews = () => {
    if (this.autoReload === false) return
    this.ovFetching = true;
    return http.get('/api/monitor/overview/')
      .then(res => this.overviews = res)
      .finally(() => {
        this.ovFetching = false;
        if (this.autoReload) setTimeout(this.fetchOverviews, 5000)
      })
  }

  showForm = (info, resourceOnly = false) => {
    if (info) {
      this.record = lds.cloneDeep(info)
    } else if (this.record.id || !this.record.type || (this.record.type === '7') !== resourceOnly) {
      this.record = resourceOnly
        ? {type: '7', targets: [], extra: resourceDefaults(), ai_mode: ''}
        : {type: '1', targets: []}
    }
    this.page = 0;
    this.formVisible = true;
  }
}

export default new Store()

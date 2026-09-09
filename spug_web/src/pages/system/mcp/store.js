import {decorate, observable} from 'mobx';
import http from 'libs/http';

class Store {
  tokens = [];
  hosts = [];
  logs = [];
  logTotal = 0;
  logPage = 1;
  logPageSize = 20;
  logStatus = undefined;
  logOperation = undefined;
  logTokenId = undefined;
  loading = false;
  createVisible = false;

  fetchTokens = async () => {
    const data = await http.get('/api/mcp-admin/tokens/');
    this.tokens = data.tokens;
    this.hosts = data.hosts;
  };

  fetchLogs = async () => {
    const data = await http.get('/api/mcp-admin/logs/', {params: {
      page: this.logPage, page_size: this.logPageSize,
      status: this.logStatus, operation: this.logOperation, token_id: this.logTokenId,
    }});
    this.logs = data.records;
    this.logTotal = data.total;
  };

  fetch = async () => {
    this.loading = true;
    try { await Promise.all([this.fetchTokens(), this.fetchLogs()]); }
    finally { this.loading = false; }
  };
}

decorate(Store, {
  tokens: observable, hosts: observable, logs: observable, logTotal: observable,
  logPage: observable, logPageSize: observable, logStatus: observable,
  logOperation: observable, logTokenId: observable,
  loading: observable, createVisible: observable,
});

export default new Store();

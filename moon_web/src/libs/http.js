import http from 'axios'
import history from './history'
import { X_TOKEN } from './functools';
import { t, langMode } from './i18n';
import { message } from 'antd';

// response处理
function handleResponse(response) {
  let result;
  const malformedExecution = response.config?.executionProtocol && response.status === 200 &&
    (!response.data || typeof response.data !== 'object' ||
      (!response.data.error && (!response.data.data || typeof response.data.data !== 'object')));
  if (malformedExecution) {
    result = t('无效的数据格式');
  } else if (response.status === 401) {
    result = t('会话过期，请重新登录');
    if (history.location.pathname !== '/') {
      history.push('/', {from: history.location})
    } else if (!response.config?.executionProtocol) {
      return Promise.reject()
    }
  } else if (response.status === 200) {
    if (response.data.error) {
      result = response.data.error
    } else if (response.data.hasOwnProperty('data')) {
      return Promise.resolve(response.data.data)
    } else if (response.headers['content-type'] === 'application/octet-stream') {
      return Promise.resolve(response)
    } else if (!response.config.isInternal) {
      return Promise.resolve(response.data)
    } else {
      result = t('无效的数据格式')
    }
  } else {
    result = t('请求失败: {}', `${response.status} ${response.statusText}`)
  }
  message.error(result);
  if (response.config?.executionProtocol) {
    // Opt-in only: ordinary pages retain their existing string rejection contract.
    const admissionRejected = [400, 401, 403, 404, 405, 413, 415, 422, 429].includes(response.status);
    return Promise.reject({message: result, responseReceived: true,
      executionStatus: response.data?.execution_status ||
        (admissionRejected && response.config.url === '/api/database/execute/' ? 'not_started' : 'unavailable')});
  }
  return Promise.reject(result)
}

// 请求拦截器
http.interceptors.request.use(request => {
  request.isInternal = request.url.startsWith('/api/');
  if (request.isInternal) {
    request.headers['X-Token'] = X_TOKEN;
    request.headers['X-Language'] = langMode
  }
  request.timeout = request.timeout || 30000;
  return request;
});

// 返回拦截器
http.interceptors.response.use(response => {
  return handleResponse(response)
}, error => {
  if (error.response) {
    return handleResponse(error.response)
  }
  const result = t('请求异常: {}', error.message);
  message.error(result);
  if (error.config?.executionProtocol) {
    return Promise.reject({message: result, networkUncertain: Boolean(error.request) ||
      ['ECONNABORTED', 'ETIMEDOUT', 'ERR_NETWORK'].includes(error.code)});
  }
  return Promise.reject(result)
});

export default http;

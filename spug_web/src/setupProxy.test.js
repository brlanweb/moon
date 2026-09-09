/** @jest-environment node */
const http = require('http');
const express = require('express');

let mockUpstream;
jest.mock('http-proxy-middleware', () => {
  const proxy = jest.requireActual('http-proxy-middleware');
  return (context, options) => proxy(context, {...options, target: mockUpstream, logLevel: 'silent'});
});
const setupProxy = require('./setupProxy');

let upstream;
let server;
const listen = app => new Promise(resolve => {
  const instance = app.listen(0, '127.0.0.1', () => resolve(instance));
});
const close = instance => new Promise(resolve => instance.close(resolve));

beforeAll(async () => {
  // The container gateway accepts API-prefixed paths, not Django's internal paths.
  upstream = await listen(http.createServer((req, res) => {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      res.writeHead(req.url.startsWith('/api/') ? 200 : 405, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({url: req.url, method: req.method, body}));
    });
  }));
  mockUpstream = `http://127.0.0.1:${upstream.address().port}`;
  const app = express();
  setupProxy(app);
  server = await listen(app);
});
afterAll(async () => {
  await close(server);
  await close(upstream);
});

function request(method, path, body = '') {
  return new Promise((resolve, reject) => {
    const req = http.request({
      hostname: '127.0.0.1', port: server.address().port, method, path,
      headers: {'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body)}
    }, res => {
      let text = '';
      res.on('data', chunk => { text += chunk; });
      res.on('end', () => resolve({status: res.statusCode, data: JSON.parse(text)}));
    });
    req.on('error', reject);
    req.end(body);
  });
}

test('login POST reaches the gateway with API prefix and JSON body intact', async () => {
  const result = await request('POST', '/api/account/login/', '{}');
  expect(result.status).toBe(200);
  expect(result.data).toEqual({url: '/api/account/login/', method: 'POST', body: '{}'});
});

test('authenticated API paths retain prefix and query parameters', async () => {
  const result = await request('GET', '/api/host/?page=2');
  expect(result.status).toBe(200);
  expect(result.data.url).toBe('/api/host/?page=2');
});

import { buildRepoUrl, parseRepoUrl } from './repoAuth';

test('GitHub PAT works without a username and survives reopening', () => {
  const url = buildRepoUrl({type: 'token', url: 'https://github.com/brlanweb/stratos.git', token: ' github_pat_example '});
  expect(url).toBe('https://x-access-token:github_pat_example@github.com/brlanweb/stratos.git');
  expect(parseRepoUrl(url)).toMatchObject({type: 'token', token: 'github_pat_example', url: 'https://github.com/brlanweb/stratos.git'});
});

test('credentials are encoded and old credentials are replaced', () => {
  expect(buildRepoUrl({type: 'password', url: 'https://old:secret@git.example/repo.git', username: 'a@b', password: 'p:/@#'}))
    .toBe('https://a%40b:p%3A%2F%40%23@git.example/repo.git');
});

test('token rejects HTTP, missing token, and SSH public keys', () => {
  for (const data of [
    {url: 'http://github.com/a/b', token: 'example'},
    {url: 'https://github.com/a/b', token: '  '},
    {url: 'https://github.com/a/b', token: 'ssh-ed25519 AAAA example'},
  ]) expect(() => buildRepoUrl({type: 'token', ...data})).toThrow();
});

test('SSH mode accepts SSH URLs and rejects HTTPS', () => {
  expect(buildRepoUrl({type: 'key', url: 'git@github.com:brlanweb/stratos.git'})).toBe('git@github.com:brlanweb/stratos.git');
  expect(parseRepoUrl('ssh://git@github.com/a/b')).toMatchObject({type: 'key'});
  expect(() => buildRepoUrl({type: 'key', url: 'https://github.com/a/b'})).toThrow();
});

test('legacy password credentials are preserved', () => {
  expect(parseRepoUrl('https://alice:p%40ss@git.example/a/b')).toMatchObject({type: 'password', username: 'alice', password: 'p@ss'});
});

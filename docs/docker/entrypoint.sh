#!/bin/bash
#
set -e

if [ -e /root/.bashrc ]; then
    source /root/.bashrc
fi

if [ -f /data/moon/env ]; then
    source /data/moon/env
fi

# 首次启动时拉取代码；前端需自行构建或挂载 moon_web/build。
if [ ! -d /data/moon/moon_api ]; then
    git clone -b "${MOON_DOCKER_VERSION:-4.0}" "${MOON_REPO_URL:-https://github.com/brlanweb/moon.git}" /data/moon
fi

mkdir -p /data/moon/moon_api/logs

exec supervisord -c /etc/supervisord.conf

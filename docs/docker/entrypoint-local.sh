#!/bin/bash
# Moon 运行时入口：代码通过卷挂载到 /data/moon，配置全部由 MOON_* 环境变量注入。
set -e

if [ -f /data/moon/env ]; then
    source /data/moon/env
fi

mkdir -p /data/moon/moon_api/logs

exec supervisord -c /etc/supervisor/supervisord.conf

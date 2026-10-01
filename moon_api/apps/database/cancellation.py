"""Cancellation runs beside the owning request, never against a recycled worker.

The control thread is joined before the dedicated work connection can be closed.
It only sees the request's immutable target; the HTTP cancel endpoint writes intent.
"""
import re
import shlex
from contextlib import closing
from copy import copy
from threading import Event, Thread
from uuid import uuid4

from apps.database.client import (
    DatabaseClientError, _mysql, _postgresql, _clickhouse, _redis,
    _dbapi_execute, _clickhouse_execute, _redis_execute,
)


def redis_cancellable(command):
    args = shlex.split(command)
    if not args:
        return False
    name = args[0].upper()
    return name in {'BLPOP', 'BRPOP', 'BRPOPLPUSH', 'BLMOVE', 'BLMPOP',
                    'BZPOPMIN', 'BZPOPMAX', 'BZMPOP'} or (
        name in {'XREAD', 'XREADGROUP'} and 'BLOCK' in [x.upper() for x in args[1:]])


def interrupted(engine, exc):
    if engine in ('mysql', 'mariadb'):
        import pymysql
        return isinstance(exc, pymysql.err.OperationalError) and exc.args[0] == 1317
    if engine == 'postgresql':
        return getattr(exc, 'sqlstate', None) == '57014'
    if engine == 'redis':
        import redis
        return isinstance(exc, redis.exceptions.ResponseError) and str(exc).startswith('UNBLOCKED')
    if engine == 'clickhouse':
        from clickhouse_connect.driver.exceptions import DatabaseError, StreamFailureError
        return isinstance(exc, (DatabaseError, StreamFailureError)) and bool(re.search(r'Code:\s*394\b', str(exc)))
    return False


def uncertain_failure(engine, exc):
    if engine in ('mysql', 'mariadb'):
        return bool(exc.args and isinstance(exc.args[0], int) and exc.args[0] >= 2000)
    if engine == 'postgresql':
        return getattr(exc, 'sqlstate', None) is None
    if engine == 'redis':
        import redis
        return isinstance(exc, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError))
    if engine == 'clickhouse':
        return not re.search(r'Code:\s*\d+', str(exc))
    return True


def pin_redis(client):
    """After establishing the ID, forbid redis-py from silently reconnecting."""
    import redis
    def connect():
        if client.connection._sock is None:
            raise redis.exceptions.ConnectionError('Dedicated execution connection was lost')
    client.connection.connect = connect


def cancelled_result():
    return {'status': 'cancelled', 'columns': [], 'rows': [], 'affected': 0,
            'elapsed': 0, 'message': '查询已中断'}


class Watcher:
    def __init__(self, registry, cancel):
        self.registry, self.cancel = registry, cancel
        self.done = Event()
        self.thread = Thread(target=self.watch, daemon=True)

    def watch(self):
        failed_attempt = None
        while not self.done.wait(0.1):
            state = {}
            try:
                state = self.registry.heartbeat()
                if not state.get('cancel_requested') or state.get('cancel_attempt') == failed_attempt:
                    continue
                outcome = self.cancel()
                self.registry.update(cancel_status=outcome)
                # 'not_running' can mean cancel arrived just before dispatch.
                # Retry while the dedicated worker is held; never run later SQL on it.
                if outcome == 'unsupported':
                    return
            except Exception:
                try:
                    self.registry.update(cancel_status='failed', cancel_error='原生取消失败，请检查控制权限或连接状态')
                except Exception:
                    pass
                failed_attempt = state.get('cancel_attempt')

    def run(self, operation, engine):
        self.thread.start()
        try:
            return operation()
        except Exception as exc:
            if interrupted(engine, exc) and self.registry.status().get('cancel_requested'):
                return cancelled_result()
            error = DatabaseClientError(str(exc))
            error.execution_uncertain = uncertain_failure(engine, exc)
            raise error from exc
        finally:
            self.done.set()
            self.thread.join()


def execute_registered(connection, command, database, registry):
    control = copy(connection)
    control.read_only = False  # Only internal, registered cancellation SQL uses this copy.
    control.connect_timeout = min(connection.connect_timeout, 3)
    control.query_timeout = 3
    engine = connection.type
    try:
        if engine in ('mysql', 'mariadb'):
            with closing(_mysql(connection, database)) as worker:
                target = int(worker.thread_id())
                with closing(_mysql(control, database='')) as controller:
                    registry.update(target={'thread_id': target}, engine=engine)

                    def cancel():
                        with controller.cursor() as cursor:
                            cursor.execute(f'KILL QUERY {target}')
                        return 'sent'

                    return Watcher(registry, cancel).run(lambda: _dbapi_execute(worker, command), engine)
        if engine == 'postgresql':
            from psycopg import sql
            with closing(_postgresql(connection)) as worker:
                with worker.cursor() as cursor:
                    if database:
                        cursor.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(database)))
                    cursor.execute('SELECT pid, backend_start::text FROM pg_stat_activity WHERE pid = pg_backend_pid()')
                    pid, started = cursor.fetchone()
                registry.update(target={'pid': pid, 'backend_start': started}, engine=engine)

                def cancel():
                    with closing(_postgresql(control)) as client:
                        with client.cursor() as cursor:
                            cursor.execute('SELECT pg_cancel_backend(pid) FROM pg_stat_activity '
                                           'WHERE pid = %s AND backend_start = %s::timestamptz '
                                           'AND datname = current_database() AND usename = current_user', (pid, started))
                            row = cursor.fetchone()
                    return 'sent' if row and row[0] else 'not_running'

                return Watcher(registry, cancel).run(lambda: _dbapi_execute(worker, command), engine)
        if engine == 'clickhouse':
            query_id = str(uuid4())
            with closing(_clickhouse(connection, database=database)) as worker:
                if 'query_id' not in worker.valid_transport_settings:
                    raise DatabaseClientError('当前 ClickHouse 驱动不支持安全指定 query_id')
                worker.query_retries = 0
                registry.update(target={'query_id': query_id}, engine=engine)

                def cancel():
                    with closing(_clickhouse(control)) as client:
                        result = client.query('KILL QUERY WHERE query_id = {target:String} SYNC',
                                              parameters={'target': query_id})
                        rows = result.named_results()
                        statuses = [row['kill_status'] for row in rows]
                    if not statuses:
                        return 'not_running'
                    if all(status in ('finished', 'waiting') for status in statuses):
                        return 'sent'
                    raise DatabaseClientError('ClickHouse 拒绝中断')

                return Watcher(registry, cancel).run(
                    lambda: _clickhouse_execute(worker, command, query_id=query_id), engine)
        if engine == 'redis':
            with closing(_redis(connection, dedicated=True)) as worker:
                target = int(worker.client_id())
                pin_redis(worker)
                supported = redis_cancellable(command)
                with closing(_redis(control, dedicated=True)) as controller:
                    controller.ping()
                    pin_redis(controller)
                    registry.update(target={'client_id': target}, engine=engine,
                                    cancel_status='available' if supported else 'unsupported')

                    def cancel():
                        if not supported:
                            return 'unsupported'
                        count = controller.execute_command('CLIENT', 'UNBLOCK', target, 'ERROR')
                        return 'sent' if count == 1 else 'not_running'

                    return Watcher(registry, cancel).run(lambda: _redis_execute(worker, command), engine)
        raise DatabaseClientError('不支持的数据库类型')
    except DatabaseClientError:
        raise
    except Exception as exc:
        # Setup failed before the user's command was dispatched.
        raise DatabaseClientError(str(exc)) from exc

import hashlib
import shlex
from dataclasses import dataclass
from uuid import uuid4

import sqlparse
from django.core import signing
from django_redis import get_redis_connection
from sqlparse import tokens as T


CONFIRMATION_MAX_AGE = 60
_CONFIRMATION_SALT = 'apps.database.command-confirmation'
_CONFIRMATION_KEY_PREFIX = 'spug:database:confirmation:'
_CONSUME_CONFIRMATION_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then
    redis.call('DEL', KEYS[1])
end
return value
"""

_SQL_READ_TYPES = {'SELECT', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN'}
_SQL_DATA_CHANGE_TYPES = {
    'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'MERGE', 'UPSERT', 'LOAD',
}
_SQL_KNOWN_NON_READ_TYPES = {
    'ALTER', 'ANALYZE', 'BEGIN', 'CALL', 'COMMENT', 'COMMIT', 'CREATE',
    'DECLARE', 'DROP', 'EXEC', 'EXECUTE', 'GRANT', 'LOCK', 'REINDEX',
    'REVOKE', 'ROLLBACK', 'SET', 'TRUNCATE', 'VACUUM',
}
_REDIS_READ_COMMANDS = {
    'BITCOUNT', 'BITFIELD_RO', 'BITPOS', 'DBSIZE', 'DUMP', 'ECHO', 'EXISTS',
    'GEODIST', 'GEOHASH', 'GEOPOS', 'GEOSEARCH', 'GET', 'GETBIT', 'GETRANGE',
    'HEXISTS', 'HGET', 'HGETALL', 'HKEYS', 'HLEN', 'HMGET', 'HRANDFIELD',
    'HSCAN', 'HSTRLEN', 'HVALS', 'INFO', 'KEYS', 'LINDEX', 'LLEN', 'LPOS',
    'LRANGE', 'MGET', 'OBJECT', 'PFCOUNT', 'PING', 'PTTL',
    'RANDOMKEY', 'SCAN', 'SCARD', 'SDIFF', 'SINTER', 'SINTERCARD',
    'SISMEMBER', 'SMEMBERS', 'SMISMEMBER', 'SRANDMEMBER', 'SSCAN', 'STRLEN',
    'SUNION', 'TIME', 'TTL', 'TYPE', 'XINFO', 'XLEN', 'XPENDING',
    'XRANGE', 'XREAD', 'XREVRANGE', 'ZCARD', 'ZCOUNT', 'ZDIFF', 'ZINTER',
    'ZINTERCARD', 'ZLEXCOUNT', 'ZMSCORE', 'ZRANDMEMBER', 'ZRANGE',
    'ZRANGEBYLEX', 'ZRANGEBYSCORE', 'ZRANK', 'ZREVRANGE', 'ZREVRANGEBYLEX',
    'ZREVRANGEBYSCORE', 'ZREVRANK', 'ZSCAN', 'ZSCORE', 'ZUNION',
}
_REDIS_WRITE_COMMANDS = {
    'APPEND', 'BITFIELD', 'BITOP', 'BLMOVE', 'BLMPOP', 'BLPOP', 'BRPOP',
    'BRPOPLPUSH', 'BZPOPMAX', 'BZPOPMIN', 'COPY', 'DECR', 'DECRBY', 'DEL',
    'EVAL', 'EVALSHA', 'EXPIRE', 'EXPIREAT', 'FCALL', 'FLUSHALL', 'FLUSHDB',
    'GEOADD', 'GETDEL',
    'GETEX', 'GETSET', 'HDEL', 'HINCRBY', 'HINCRBYFLOAT', 'HMSET', 'HSET',
    'HSETNX', 'INCR', 'INCRBY', 'INCRBYFLOAT', 'LINSERT', 'LMOVE', 'LMPOP',
    'LPOP', 'LPUSH', 'LPUSHX', 'LREM', 'LSET', 'LTRIM', 'MIGRATE', 'MSET',
    'MSETNX', 'PERSIST', 'PEXPIRE', 'PEXPIREAT', 'PFADD', 'PFMERGE', 'PSETEX',
    'RENAME', 'RENAMENX', 'RESTORE', 'RPOP', 'RPOPLPUSH', 'RPUSH', 'RPUSHX',
    'SADD', 'SDIFFSTORE', 'SET', 'SETBIT', 'SETEX', 'SETNX', 'SETRANGE',
    'SINTERSTORE', 'SMOVE', 'SORT', 'SPOP', 'SREM', 'SUNIONSTORE', 'SWAPDB',
    'TOUCH', 'UNLINK', 'XACK', 'XADD', 'XAUTOCLAIM', 'XCLAIM', 'XDEL', 'XGROUP',
    'XSETID', 'XTRIM', 'ZADD', 'ZDIFFSTORE', 'ZINCRBY', 'ZINTERSTORE',
    'ZMPOP', 'ZPOPMAX', 'ZPOPMIN', 'ZRANGESTORE', 'ZREM', 'ZREMRANGEBYLEX',
    'ZREMRANGEBYRANK', 'ZREMRANGEBYSCORE', 'ZUNIONSTORE',
}
_REDIS_READ_SUBCOMMANDS = {
    'MEMORY': {'DOCTOR', 'MALLOC-STATS', 'STATS', 'USAGE'},
}
_REDIS_WRITE_SUBCOMMANDS = {
    'MEMORY': {'PURGE'},
}


class PolicyViolation(Exception):
    pass


@dataclass(frozen=True)
class CommandClassification:
    statement_types: tuple
    read_only: bool
    has_data_change: bool
    known: bool


@dataclass(frozen=True)
class PolicyDecision:
    statement_types: tuple
    requires_confirmation: bool = False
    confirmation_token: str = None


def _meaningful_tokens(statement):
    return [
        token for token in statement.flatten()
        if not token.is_whitespace
        and token.ttype not in T.Comment
        and not (token.ttype in T.Punctuation and token.value == ';')
    ]


def _top_level_words(statement):
    return [
        token.value.upper()
        for token in statement.tokens
        if not token.is_whitespace and token.ttype not in T.Comment
    ]


def _copy_target(words):
    if not words or words[0] != 'COPY':
        return None
    try:
        target_index = words.index('TO') + 1
    except ValueError:
        return None
    return words[target_index] if target_index < len(words) else None


def _has_mysql_executable_comment(statement):
    return any(
        token.ttype in T.Comment
        and token.value.lstrip().startswith(('/*!', '/*M!'))
        for token in statement.flatten()
    )


def _classify_sql_statement(statement):
    tokens = _meaningful_tokens(statement)
    if not tokens:
        return 'UNKNOWN', False, False, False

    words = [token.value.upper() for token in tokens]
    parsed_type = statement.get_type().upper()
    statement_type = parsed_type if parsed_type != 'UNKNOWN' else words[0]

    if statement_type == 'COPY':
        target = _copy_target(_top_level_words(statement))
        is_read = target == 'STDOUT'
        return statement_type, is_read, not is_read, True

    mutation_tokens = {
        token.value.upper()
        for token in tokens
        if token.ttype in T.Keyword.DML
    } & _SQL_DATA_CHANGE_TYPES
    if words[0] == 'LOAD' and len(words) > 1 and words[1] == 'DATA':
        mutation_tokens.add('LOAD')
    if words[0] == 'EXPLAIN' and 'ANALYZE' not in words:
        mutation_tokens.clear()

    has_data_change = (
        statement_type in _SQL_DATA_CHANGE_TYPES
        or bool(mutation_tokens)
        or (statement_type == 'SELECT' and 'INTO' in words)
    )
    read_only = statement_type in _SQL_READ_TYPES and not has_data_change
    known = (
        statement_type in _SQL_READ_TYPES
        or statement_type in _SQL_DATA_CHANGE_TYPES
        or statement_type in _SQL_KNOWN_NON_READ_TYPES
        or parsed_type != 'UNKNOWN'
    )
    return statement_type, read_only, has_data_change, known


def _classify_sql(database_type, command):
    parsed_statements = sqlparse.parse(command)
    has_executable_comment = (
        database_type in ('mysql', 'mariadb')
        and any(_has_mysql_executable_comment(statement)
                for statement in parsed_statements)
    )
    statements = []
    for statement in parsed_statements:
        classified = _classify_sql_statement(statement)
        if classified[0] != 'UNKNOWN' or _meaningful_tokens(statement):
            statements.append(classified)
    if not statements:
        statements.append(('UNKNOWN', False, False, False))
    return CommandClassification(
        statement_types=tuple(item[0] for item in statements),
        read_only=not has_executable_comment and all(item[1] for item in statements),
        has_data_change=has_executable_comment or any(item[2] for item in statements),
        known=not has_executable_comment and all(item[3] for item in statements),
    )


def _classify_redis(command):
    try:
        args = shlex.split(command)
    except ValueError:
        args = []
    command_type = args[0].upper() if args else 'UNKNOWN'
    subcommand = args[1].upper() if len(args) > 1 else None
    is_read = (
        command_type in _REDIS_READ_COMMANDS
        or subcommand in _REDIS_READ_SUBCOMMANDS.get(command_type, set())
    )
    is_write = (
        command_type in _REDIS_WRITE_COMMANDS
        or subcommand in _REDIS_WRITE_SUBCOMMANDS.get(command_type, set())
    )
    return CommandClassification(
        statement_types=(command_type,),
        read_only=is_read,
        has_data_change=is_write,
        known=is_read or is_write,
    )


def classify_command(database_type, command):
    if database_type == 'redis':
        return _classify_redis(command)
    return _classify_sql(database_type, command)


def _is_copy_to_program(database_type, command):
    if database_type != 'postgresql':
        return False
    return any(
        _copy_target(_top_level_words(statement)) == 'PROGRAM'
        for statement in sqlparse.parse(command)
    )


def _confirmation_payload(user_id, connection_id, command, database, nonce=None):
    payload = {
        'user_id': user_id,
        'connection_id': connection_id,
        'command_sha256': hashlib.sha256(command.encode('utf-8')).hexdigest(),
        'database': database,
    }
    if nonce is not None:
        payload['nonce'] = nonce
    return payload


def _confirmation_key(nonce):
    return f'{_CONFIRMATION_KEY_PREFIX}{nonce}'


def _create_confirmation_token(user_id, connection_id, command, database):
    redis = get_redis_connection()
    for _ in range(3):
        nonce = uuid4().hex
        payload = _confirmation_payload(
            user_id, connection_id, command, database, nonce=nonce,
        )
        token = signing.dumps(payload, salt=_CONFIRMATION_SALT, compress=True)
        if redis.set(
                _confirmation_key(nonce), token,
                ex=CONFIRMATION_MAX_AGE, nx=True):
            return token
    raise PolicyViolation('无法创建确认令牌，请重试')


def _validate_confirmation_token(token, user_id, connection_id, command, database):
    try:
        payload = signing.loads(
            token,
            salt=_CONFIRMATION_SALT,
            max_age=CONFIRMATION_MAX_AGE,
        )
    except (signing.BadSignature, signing.SignatureExpired, TypeError, ValueError) as exc:
        raise PolicyViolation('确认令牌无效或已过期') from exc
    nonce = payload.get('nonce') if isinstance(payload, dict) else None
    expected = _confirmation_payload(
        user_id, connection_id, command, database, nonce=nonce,
    )
    if not isinstance(nonce, str) or not nonce or payload != expected:
        raise PolicyViolation('确认令牌无效或已过期')
    stored_token = get_redis_connection().eval(
        _CONSUME_CONFIRMATION_SCRIPT, 1, _confirmation_key(nonce),
    )
    if isinstance(stored_token, bytes):
        stored_token = stored_token.decode('utf-8')
    if stored_token != token:
        raise PolicyViolation('确认令牌无效或已过期')


def enforce_command_policy(
        connection, user_id, command, confirmation_token=None, database=None):
    effective_database = database if database is not None else getattr(connection, 'database', None)
    classification = classify_command(connection.type, command)
    if _is_copy_to_program(connection.type, command):
        raise PolicyViolation('不允许执行 COPY TO PROGRAM')
    if connection.read_only and (
            not classification.known or not classification.read_only):
        raise PolicyViolation('只读连接不允许执行该命令')

    requires_confirmation = (
        connection.environment == 'production'
        and (classification.has_data_change or not classification.known)
    )
    if not requires_confirmation:
        return PolicyDecision(classification.statement_types)
    if confirmation_token:
        _validate_confirmation_token(
            confirmation_token, user_id, connection.id, command, effective_database,
        )
        return PolicyDecision(classification.statement_types)
    return PolicyDecision(
        classification.statement_types,
        requires_confirmation=True,
        confirmation_token=_create_confirmation_token(
            user_id, connection.id, command, effective_database,
        ),
    )

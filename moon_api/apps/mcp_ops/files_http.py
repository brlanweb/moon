"""HTTP endpoint serving one-time MCP file transfer links: PUT/POST uploads and GET downloads."""
import time
from urllib.parse import quote

from anyio import to_thread
from asgiref.sync import sync_to_async
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from apps.mcp_ops import files
from apps.mcp_ops.service import _redact

_BATCH = files.CHUNK_SIZE


def _client_ip(request):
    # Nginx overwrites X-Moon-Client-IP with its trusted peer address.
    ip = request.headers.get('x-moon-client-ip') or (request.client.host if request.client else '')
    return ip.strip()[:50]


def _error(message, status):
    return JSONResponse({'error': message}, status_code=status, headers={'Cache-Control': 'no-store'})


async def _claim(secret, mode, ip):
    try:
        return await sync_to_async(files.claim_link, thread_sensitive=True)(secret, mode, ip), None
    except files.TransferError as exc:
        return None, _error(str(exc), exc.status)


async def upload(request):
    secret = request.path_params['secret']
    ip = _client_ip(request)
    length = request.headers.get('content-length')
    # Reject oversize declared bodies before consuming the link so the caller can retry correctly.
    if length and length.isdigit() and int(length) > files.MAX_FILE_BYTES:
        return _error('上传文件超过 1 GiB 上限', 413)
    if 'multipart/form-data' in request.headers.get('content-type', ''):
        return _error('请直接以请求体发送文件内容（例如 curl -T），不支持 multipart 表单', 415)
    claimed, error = await _claim(secret, files.UPLOAD, ip)
    if error:
        return error
    token, host, path = claimed
    started = time.monotonic()
    writer = None
    try:
        writer = await to_thread.run_sync(files.Upload, host, path, files.is_unrestricted(token))
        buffer = bytearray()
        async for chunk in request.stream():
            if not chunk:
                continue
            buffer.extend(chunk)
            if writer.size + len(buffer) > files.MAX_FILE_BYTES:
                raise files.TransferError('上传文件超过 1 GiB 上限', 413)
            if len(buffer) >= _BATCH:
                data, buffer = bytes(buffer), bytearray()
                await to_thread.run_sync(writer.write, data)
        if buffer:
            await to_thread.run_sync(writer.write, bytes(buffer))
        if length and length.isdigit() and int(length) != writer.size:
            raise files.TransferError('上传内容不完整', 400)
        await to_thread.run_sync(writer.commit)
        await sync_to_async(files.finish_audit, thread_sensitive=True)(
            token, files.UPLOAD, ip, host, writer.target, 'success', writer.size,
            files.monotonic_ms(started), digest=writer.sha256)
        return JSONResponse({'host_id': host.id, 'remote_path': writer.target,
                             'size': writer.size, 'sha256': writer.sha256},
                            headers={'Cache-Control': 'no-store'})
    except Exception as exc:
        status = exc.status if isinstance(exc, files.TransferError) else (
            400 if isinstance(exc, ClientDisconnect) else 502)
        reason = '客户端中断上传' if isinstance(exc, ClientDisconnect) else _redact(str(exc)) or '上传失败'
        size = writer.size if writer else 0
        await sync_to_async(files.finish_audit, thread_sensitive=True)(
            token, files.UPLOAD, ip, host, path, 'failed', size, files.monotonic_ms(started), reason[:255])
        return _error(reason, status)
    finally:
        if writer is not None:
            await to_thread.run_sync(writer.close)


async def download(request):
    if request.method != 'GET':
        # Starlette answers HEAD on GET routes; it must not consume the one-time link.
        return _error('请使用 GET 下载', 405)
    secret = request.path_params['secret']
    ip = _client_ip(request)
    claimed, error = await _claim(secret, files.DOWNLOAD, ip)
    if error:
        return error
    token, host, path = claimed
    started = time.monotonic()
    try:
        reader = await to_thread.run_sync(files.Download, host, path, files.is_unrestricted(token))
    except Exception as exc:
        reason = _redact(str(exc)) or '下载失败'
        await sync_to_async(files.finish_audit, thread_sensitive=True)(
            token, files.DOWNLOAD, ip, host, path, 'failed', 0, files.monotonic_ms(started), reason[:255])
        return _error(reason, 403 if isinstance(exc, files.AuthorizationError) else 502)

    async def body():
        status, reason = 'failed', '客户端中断下载'
        try:
            while True:
                data = await to_thread.run_sync(reader.read)
                if not data:
                    break
                yield data
            if reader.sent == reader.size:
                status, reason = 'success', None
            else:
                reason = '远程文件读取不完整'
        except Exception as exc:
            reason = _redact(str(exc))[:255] or '下载失败'
            raise
        finally:
            await to_thread.run_sync(reader.close)
            await sync_to_async(files.finish_audit, thread_sensitive=True)(
                token, files.DOWNLOAD, ip, host, reader.real, status, reader.sent,
                files.monotonic_ms(started), reason)

    filename = quote(reader.name)
    return StreamingResponse(body(), media_type='application/octet-stream', headers={
        'Content-Length': str(reader.size), 'Cache-Control': 'no-store',
        'Content-Disposition': f"attachment; filename*=UTF-8''{filename}",
        'X-Content-Type-Options': 'nosniff',
    })


routes = [
    Route('/mcp/files/{secret}', upload, methods=['PUT', 'POST']),
    Route('/mcp/files/{secret}', download, methods=['GET']),
]

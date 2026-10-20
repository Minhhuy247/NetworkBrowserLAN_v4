"""LAN Browser v4: HTTP server + SSE + multiple clients + binary file relay.
Uses built-in socketserver (TCP) and custom network_http raw socket HTTP client.
For classroom LAN only. No user authentication or HTTPS on the LAN.
"""
import argparse
import hashlib
import html
import json
import mimetypes
import os
import queue
import re
import secrets
import socket
import tempfile
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from network_http import fetch, FetchError

ROOT = Path(__file__).resolve().parent
MAX_FILE = 20 * 1024 * 1024
MAX_FILES = 20
STALE_SECONDS = 17

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

class Hub:
    def __init__(self):
        self.lock = threading.RLock()
        self.clients = {}   # secret session id -> name, ip, connected, last_seen, queue
        self.messages = deque(maxlen=150)
        self.logs = deque(maxlen=200)
        self.files = {}
        self.store = tempfile.TemporaryDirectory(prefix='network_browser_v4_')
        self.log('SYSTEM', 'Khởi tạo hệ thống TCP/HTTP')

    def log(self, typ, msg):
        line = {'time': now(), 'type': typ, 'text': msg}
        with self.lock:
            self.logs.append(line)
            self.broadcast('log', line)
        print(f"[{line['time']}] [{typ}] {msg}", flush=True)

    def online(self):
        with self.lock:
            return [{'id': cid, 'name': v['name'], 'ip': v['ip'], 'connected_at': v['connected_at']}
                    for cid,v in self.clients.items()]

    def broadcast(self, kind, obj, recipients=None):
        data = {'kind': kind, 'data': obj}
        with self.lock:
            for cid, client in self.clients.items():
                if recipients is None or cid in recipients:
                    try:
                        client['queue'].put_nowait(data)
                    except queue.Full:
                        pass

    def announce_presence(self):
        self.broadcast('presence', {'clients': self.online()})

    def join(self, name, ip):
        name = str(name).strip()[:32]
        if not name:
            raise ValueError('Nhập tên Client trước khi kết nối.')
        with self.lock:
            cid = secrets.token_urlsafe(24)
            self.clients[cid] = {'name': name, 'ip': ip, 'connected_at': now(),
                                 'last_seen': time.monotonic(), 'queue': queue.Queue(maxsize=300)}
            self.log('CONNECT', f'{name} ({ip}) đã kết nối. Online: {len(self.clients)}')
            self.announce_presence()
            history = [m for m in self.messages if m['to'] == 'all']
            return cid, list(history)

    def require(self, cid):
        with self.lock:
            if not cid or cid not in self.clients:
                raise PermissionError('Phiên Client đã mất kết nối. Vui lòng kết nối lại.')
            return self.clients[cid]

    def heartbeat(self, cid):
        with self.lock:
            client = self.require(cid)
            client['last_seen'] = time.monotonic()

    def leave(self, cid, cause='ngắt kết nối'):
        with self.lock:
            v = self.clients.pop(cid, None)
            if v:
                self.log('DISCONNECT', f"{v['name']} ({v['ip']}) {cause}. Online: {len(self.clients)}")
                self.announce_presence()
            return bool(v)

    def prune(self):
        with self.lock:
            stale = [cid for cid,v in self.clients.items() if time.monotonic()-v['last_seen'] > STALE_SECONDS]
        for cid in stale:
            self.leave(cid, '(mất heartbeat / đóng trình duyệt)')

    def send_chat(self, cid, to, body):
        with self.lock:
            sender = self.require(cid)
            body = str(body).strip()
            if not body or len(body) > 2000:
                raise ValueError('Tin nhắn phải dài từ 1 đến 2000 ký tự.')
            if to != 'all' and to not in self.clients:
                raise ValueError('Người nhận hiện không trực tuyến.')
            msg = {'id': secrets.token_hex(8), 'time': now(), 'from': cid,
                   'from_name': sender['name'], 'to': to, 'text': body}
            self.messages.append(msg)
            recipients = None if to == 'all' else {cid, to}
            self.broadcast('chat', msg, recipients)
            dest = 'Nhóm' if to=='all' else self.clients[to]['name']
            self.log('CHAT', f"{sender['name']} → {dest} ({len(body)} ký tự)")
            return msg

    def store_file(self, cid, to, filename, stream, length):
        with self.lock:
            sender = self.require(cid)
            if to != 'all' and to not in self.clients:
                raise ValueError('Người nhận không trực tuyến.')
            if len(self.files) >= MAX_FILES:
                raise ValueError('Server đã đầy (tối đa 20 file mỗi lần chạy).')
            recipients = set(self.clients.keys()) if to=='all' else {cid, to}
            sender_name = sender['name']
        filename = str(filename).replace('\\','/').split('/')[-1].strip()[:160]
        filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)
        if filename in ('','.','..'):
            raise ValueError('Tên file không hợp lệ.')
        if not 0 <= length <= MAX_FILE:
            raise ValueError('File vượt giới hạn 20 MB.')
        fid = secrets.token_hex(16)
        path = Path(self.store.name) / fid
        digest = hashlib.sha256()
        remain = length
        try:
            with open(path, 'wb') as f:
                while remain:
                    chunk = stream.read(min(remain, 65536))
                    if not chunk:
                        raise ValueError('Truyền file chưa hoàn tất.')
                    f.write(chunk)
                    digest.update(chunk)
                    remain -= len(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        info = {'id': fid, 'name': filename, 'size': length, 'sha256': digest.hexdigest(),
                'from': cid, 'from_name': sender_name, 'to': to, 'time': now(),
                'recipients': recipients, 'path': path}
        with self.lock:
            self.files[fid] = info
            self.broadcast('file', self.file_public(info), recipients)
        self.log('FILE', f"{sender_name} gửi {filename} ({length} bytes) → " + ('Nhóm' if to=='all' else 'Client riêng'))
        return self.file_public(info)

    @staticmethod
    def file_public(info):
        return {k:v for k,v in info.items() if k not in ('recipients','path')}

    def get_file(self, cid, fid):
        with self.lock:
            self.require(cid)
            info = self.files.get(fid)
            if not info or cid not in info['recipients']:
                raise PermissionError('Bạn không có quyền tải file này.')
            return info

HUB = Hub()

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'NetworkBrowserLAN/4.0'

    def log_message(self, format, *args):
        return  # Application events logged by HUB

    def reply(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        if isinstance(body, (dict,list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def error(self, status, message):
        self.reply(status, {'ok':False,'error': str(message)})

    def request_json(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise ValueError('Content-Length không hợp lệ.')
        if n > 120000 or n < 0:
            raise ValueError('JSON quá lớn.')
        try:
            return json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
        except (json.JSONDecodeError, UnicodeError):
            raise ValueError('JSON không hợp lệ.')

    def do_HEAD(self):
        self.dispatch()

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def dispatch(self):
        url = urlsplit(self.path)
        path = url.path
        args = parse_qs(url.query)
        try:
            if self.command in ('GET','HEAD'):
                if path == '/':
                    return self.static('index.html', 'text/html; charset=utf-8')
                if path == '/static/style.css':
                    return self.static('static/style.css', 'text/css; charset=utf-8')
                if path == '/static/app.js':
                    return self.static('static/app.js', 'text/javascript; charset=utf-8')
                if path == '/demo':
                    return self.demo()
                if path == '/api/state':
                    return self.reply(200, {'ok': True,'clients':HUB.online(),
                                            'logs':list(HUB.logs)[-90:],
                                            'server_time':now(), 'max_file':MAX_FILE})
                if path == '/api/events':
                    return self.events(args.get('id',[''])[0])
                if path.startswith('/api/files/'):
                    return self.download(path.split('/')[-1], args.get('client_id',[''])[0])
            elif self.command == 'POST':
                if path == '/demo':
                    return self.demo()
                if path == '/api/files/upload':
                    return self.upload(args)
                data = self.request_json()
                if path == '/api/connect':
                    cid, history = HUB.join(data.get('name',''),self.client_address[0])
                    return self.reply(200, {'ok':True,'id':cid, 'history':history,
                                             'clients':HUB.online(), 'files':[]})
                if path == '/api/heartbeat':
                    HUB.heartbeat(data.get('id'))
                    return self.reply(200,{'ok':True})
                if path == '/api/disconnect':
                    HUB.leave(data.get('id'), '(chủ động rời đi)')
                    return self.reply(200,{'ok':True})
                if path == '/api/chat':
                    msg = HUB.send_chat(data.get('id'),data.get('to'),data.get('text',''))
                    return self.reply(200,{'ok':True,'message':msg})
                if path == '/api/fetch':
                    client = HUB.require(data.get('id'))
                    result = fetch(data.get('url',''),data.get('method','GET'),data.get('body',''))
                    HUB.log('HTTP',f"{client['name']} | {result['method']} {result['url'][:110]} → {result['status']} ({result['elapsed_ms']} ms)")
                    return self.reply(200,{'ok':True,'result':result})
            return self.error(404,'Không tìm thấy tài nguyên.')
        except PermissionError as ex:
            self.error(403, ex)
        except (ValueError,FetchError) as ex:
            self.error(400, ex)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as ex:
            HUB.log('ERROR',str(ex))
            try:
                self.error(500,'Lỗi nội bộ Server: '+str(ex))
            except OSError:
                pass

    def static(self, file, ctype):
        raw = (ROOT/file).read_bytes()
        self.reply(200,raw,ctype,extra={'X-Frame-Options':'DENY'})

    def demo(self):
        text = ''
        if self.command == 'POST':
            count = int(self.headers.get('Content-Length','0'))
            if count > 100000:
                return self.error(413,'POST quá lớn')
            text = self.rfile.read(count).decode('utf-8','replace')
        message = html.escape(text) if text else 'Trang HTML mẫu phục vụ kiểm thử GET/POST/HEAD.'
        html_response = f'''<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Network Browser LAN Demo</title></head>
        <body><div class="container"><h1>Demo giao thức HTTP/1.1</h1><p>Máy chủ TCP phản hồi thành công.</p>
        <p>{message}</p><div>Đề tài lập trình mạng</div><span>GET</span> <span>POST</span>
        <img src="/static/demo-placeholder.png" alt="Hình minh họa"></div></body></html>'''
        HUB.log('HTTP',f'{self.client_address[0]} | {self.command} /demo → 200')
        self.reply(200,html_response,'text/html; charset=utf-8')

    def events(self, cid):
        client = HUB.require(cid)
        q = client['queue']
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control','no-cache, no-transform')
        self.send_header('Connection','keep-alive')
        self.send_header('X-Accel-Buffering','no')
        self.end_headers()
        try:
            self.wfile.write(b': connected\n\n'); self.wfile.flush()
            while True:
                with HUB.lock:
                    if cid not in HUB.clients:
                        break
                try:
                    item = q.get(timeout=8)
                    payload = 'data: '+json.dumps(item, ensure_ascii=False)+'\n\n'
                    self.wfile.write(payload.encode('utf-8'))
                except queue.Empty:
                    self.wfile.write(b': heartbeat\n\n')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.close_connection = True

    def upload(self, args):
        cid = args.get('id',[''])[0]
        to = args.get('to',[''])[0]
        name = args.get('name',[''])[0]
        HUB.require(cid)
        try:
            length = int(self.headers.get('Content-Length','-1'))
        except ValueError:
            return self.error(400,'Kích thước file không hợp lệ.')
        if length > MAX_FILE:
            return self.error(413,'File vượt quá 20 MB.')
        if length < 0:
            return self.error(411,'Thiếu Content-Length.')
        file_info = HUB.store_file(cid,to,name,self.rfile,length)
        self.reply(201,{'ok':True,'file':file_info})

    def download(self, fid, cid):
        info = HUB.get_file(cid,fid)
        file = info['path']
        size = info['size']
        self.send_response(200)
        self.send_header('Content-Type','application/octet-stream')
        self.send_header('Content-Length',str(size))
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Disposition',"attachment; filename*=UTF-8''" + quote(info['name']))
        self.send_header('X-File-SHA256',info['sha256'])
        self.end_headers()
        if self.command == 'HEAD':
            return
        try:
            with open(file,'rb') as stream:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            HUB.log('DOWNLOAD',f"{HUB.require(cid)['name']} tải {info['name']}")
        except (BrokenPipeError,ConnectionResetError,OSError):
            pass

def sweeper():
    while True:
        time.sleep(3)
        HUB.prune()

def get_ips():
    addresses = set()
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.connect(('1.1.1.1',80))  # UDP connect chooses interface; sends no packet.
            addresses.add(sock.getsockname()[0])
    except OSError:
        pass
    addresses.add('127.0.0.1')
    return sorted(addresses)

def main():
    parser = argparse.ArgumentParser(description='Network Browser LAN v4 – HTTP/TCP Server')
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--port',default=8080,type=int)
    args = parser.parse_args()
    threading.Thread(target=sweeper,daemon=True).start()
    try:
        http = Server((args.host,args.port),Handler)
    except OSError as ex:
        print(f'Không mở được cổng {args.port}: {ex}')
        raise SystemExit(1)
    HUB.log('SERVER',f'HTTP TCP Socket đang lắng nghe tại {args.host}:{args.port}')
    print('\n=== NETWORK BROWSER LAN v4 ===')
    for ip in get_ips():
        print(f'Chrome/Edge: http://{ip}:{args.port}')
    print('Client khác phải dùng IP LAN thật của máy Server từ ipconfig (Windows).')
    print('Nhấn Ctrl+C để dừng.\n')
    try:
        http.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print('\nĐang dừng Server...')
    finally:
        http.server_close()
        HUB.store.cleanup()

if __name__ == '__main__':
    main()

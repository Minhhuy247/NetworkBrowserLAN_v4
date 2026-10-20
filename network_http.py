"""HTTP/1.1 client built atop TCP sockets for networking coursework.
Only Python standard library. Browser UI is not used to fetch destination sites.
"""
import gzip
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
from http.client import HTTPResponse

MAX_RESPONSE = 2 * 1024 * 1024

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.counts = {tag: 0 for tag in ('p', 'div', 'span', 'img')}
        self.words = []
        self.ignore = 0
    def handle_starttag(self, tag, attrs):
        if tag in self.counts:
            self.counts[tag] += 1
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.ignore += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.ignore = max(0, self.ignore - 1)
    def handle_data(self, data):
        if not self.ignore and data.strip():
            self.words.append(data.strip())

class FetchError(Exception):
    pass

def fetch(url, method='GET', post_body='', redirects=0):
    method = method.upper()
    if method not in ('GET', 'HEAD', 'POST'):
        raise FetchError('Chỉ hỗ trợ GET, POST hoặc HEAD.')
    if not isinstance(url, str) or len(url) > 2048:
        raise FetchError('URL không hợp lệ hoặc quá dài.')
    target = urlsplit(url)
    if target.scheme not in ('http', 'https') or not target.hostname or target.username or target.password:
        raise FetchError('Nhập URL http:// hoặc https:// hợp lệ (không kèm mật khẩu).')
    try:
        port = target.port or (443 if target.scheme == 'https' else 80)
    except ValueError:
        raise FetchError('Cổng trong URL không hợp lệ.')
    if port < 1 or port > 65535:
        raise FetchError('Cổng không hợp lệ.')
    host = target.hostname
    path = target.path or '/'
    if target.query:
        path += '?' + target.query
    body = str(post_body).encode('utf-8') if method == 'POST' else b''
    if len(body) > 100 * 1024:
        raise FetchError('Nội dung POST vượt quá 100 KB.')
    host_header = f'[{host}]' if ':' in host else host
    if port != (443 if target.scheme == 'https' else 80):
        host_header += f':{port}'
    lines = [f'{method} {path} HTTP/1.1', f'Host: {host_header}',
             'User-Agent: NetworkBrowserLAN-v4/1.0 (Socket)',
             'Accept: text/html, */*', 'Accept-Encoding: identity',
             'Connection: close']
    if method == 'POST':
        lines.extend(['Content-Type: text/plain; charset=utf-8', f'Content-Length: {len(body)}'])
    request_text = '\r\n'.join(lines) + '\r\n\r\n'
    begin = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=7) as sock:
            sock.settimeout(12)
            if target.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            with sock:
                sock.sendall(request_text.encode('ascii', 'replace') + body)
                response = HTTPResponse(sock)
                response.begin()
                status = response.status
                reason = response.reason
                headers = {key: value for key, value in response.getheaders()}
                if method == 'HEAD':
                    content = b''
                else:
                    content = response.read(MAX_RESPONSE + 1)
                    if len(content) > MAX_RESPONSE:
                        raise FetchError('Trang quá lớn (giới hạn phản hồi 2 MB).')
    except (OSError, ssl.SSLError, TimeoutError, ValueError) as exc:
        raise FetchError('Lỗi kết nối TCP/HTTP: ' + str(exc)) from exc
    if status in (301, 302, 303, 307, 308) and headers.get('Location') and redirects < 3:
        destination = urljoin(url, headers['Location'])
        if method == 'POST' and status in (301, 302, 303):
            return fetch(destination, 'GET', '', redirects+1)
        return fetch(destination, method, post_body, redirects+1)
    encoding = headers.get('Content-Encoding', '').lower()
    if encoding == 'gzip' and content:
        try:
            content = gzip.decompress(content)
            if len(content) > MAX_RESPONSE:
                raise FetchError('HTML giải nén quá lớn.')
        except OSError:
            raise FetchError('Không giải nén được gzip.')
    content_type = headers.get('Content-Type', '')
    charset_match = re.search(r'charset\s*=\s*["\']?([\w.-]+)', content_type, re.I)
    charset = charset_match.group(1) if charset_match else 'utf-8'
    try:
        decoded = content.decode(charset, errors='replace')
    except LookupError:
        decoded = content.decode('utf-8', errors='replace')
    is_html = ('text/html' in content_type.lower()) or ('<html' in decoded[:500].lower())
    parser = PageParser()
    if method != 'HEAD' and is_html:
        parser.feed(decoded)
    elapsed_ms = round((time.monotonic()-begin)*1000)
    return {
        'url': url, 'final_url': url,
        'method': method, 'status': status, 'reason': reason,
        'headers': headers, 'byte_length': len(content),
        'content_length_header': headers.get('Content-Length','—'),
        'html_length': len(decoded) if method != 'HEAD' and is_html else 0,
        'counts': parser.counts, 'text': '\n'.join(parser.words)[:15000],
        'html': decoded[:220000] if method != 'HEAD' and is_html else '',
        'preview': decoded[:15000] if method != 'HEAD' else '',
        'is_html': is_html, 'elapsed_ms': elapsed_ms,
        'request_line': request_text.split('\r\n')[0],
        'request_headers': '\n'.join(lines[1:]),
    }

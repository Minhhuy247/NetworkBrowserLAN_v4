"""Run: python -m unittest discover -s tests -v"""
import hashlib
import http.client
import json
import socket
import threading
import time
import unittest
from urllib.parse import quote
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from network_http import fetch

class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = server.Server(('127.0.0.1',0),server.Handler)
        cls.port=cls.http.server_address[1]
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.port}'
        cls.sessions=[]

    @classmethod
    def tearDownClass(cls):
        for sid in cls.sessions: server.HUB.leave(sid,'test cleanup')
        cls.http.shutdown();cls.http.server_close()

    def http_req(self,method,path,body=None,ctype='application/json'):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        if isinstance(body,(dict,list)):
            body=json.dumps(body).encode()
        headers={'Content-Type':ctype} if body is not None else {}
        conn.request(method,path,body=body,headers=headers)
        res=conn.getresponse();raw=res.read();code=res.status;hdr=dict(res.getheaders());conn.close()
        return code,hdr,raw

    def join(self,name):
        code,_,raw=self.http_req('POST','/api/connect',{'name':name})
        self.assertEqual(code,200)
        sid=json.loads(raw)['id'];self.sessions.append(sid)
        return sid

    def test_01_static(self):
        code,headers,raw=self.http_req('GET','/')
        self.assertEqual(code,200);self.assertIn(b'NetScope',raw)
        code,_,raw=self.http_req('GET','/static/app.js')
        self.assertEqual(code,200)

    def test_02_browser_GET(self):
        res=fetch(self.base+'/demo','GET')
        self.assertEqual(res['status'],200)
        self.assertEqual(res['counts']['p'],2)
        self.assertGreater(res['html_length'],100)
        self.assertEqual(res['counts']['img'],1)

    def test_03_browser_POST(self):
        res=fetch(self.base+'/demo','POST','Dữ liệu kiểm tra')
        self.assertEqual(res['status'],200)
        self.assertIn('Dữ liệu kiểm tra',res['text'])

    def test_04_browser_HEAD(self):
        res=fetch(self.base+'/demo','HEAD')
        self.assertEqual(res['status'],200)
        self.assertEqual(res['byte_length'],0)
        self.assertEqual(res['counts']['p'],0)
        self.assertIn('Content-Length',res['headers'])

    def test_05_multiple_clients(self):
        a=self.join('Alpha');b=self.join('Beta');c=self.join('Gamma')
        self.assertGreaterEqual(len(server.HUB.online()),3)
        self.assertNotEqual(a,b);self.assertNotEqual(b,c)

    def test_06_private_chat(self):
        a=self.join('P1');b=self.join('P2');c=self.join('P3')
        msg=server.HUB.send_chat(a,b,'Hello riêng')
        self.assertEqual(msg['to'],b)
        qa=server.HUB.clients[a]['queue'];qb=server.HUB.clients[b]['queue'];qc=server.HUB.clients[c]['queue']
        def get_chat(q):
            found=[]
            while True:
                try:item=q.get_nowait()
                except Exception:break
                if item['kind']=='chat' and item['data']['id']==msg['id']:found.append(item)
            return found
        self.assertTrue(get_chat(qa));self.assertTrue(get_chat(qb));self.assertFalse(get_chat(qc))

    def test_07_group_chat(self):
        a=self.join('G1');b=self.join('G2')
        msg=server.HUB.send_chat(a,'all','Hello nhóm')
        self.assertEqual(msg['to'],'all')
        self.assertTrue(any(m['id']==msg['id'] for m in server.HUB.messages))

    def test_08_file_upload_download(self):
        a=self.join('F1');b=self.join('F2');c=self.join('F3')
        payload=b'LAN-v4\x00\x01\xff'*300
        import io
        info=server.HUB.store_file(a,b,'example.pdf',io.BytesIO(payload),len(payload))
        self.assertEqual(info['sha256'],hashlib.sha256(payload).hexdigest())
        self.assertEqual(server.HUB.get_file(b,info['id'])['path'].read_bytes(),payload)
        with self.assertRaises(PermissionError):server.HUB.get_file(c,info['id'])
        path='/api/files/'+info['id']+'?client_id='+quote(b)
        code,hdr,data=self.http_req('GET',path)
        self.assertEqual(code,200);self.assertEqual(data,payload)
        self.assertEqual(hdr['X-File-SHA256'],hashlib.sha256(payload).hexdigest())

    def test_09_file_upload_http(self):
        a=self.join('Uploader');b=self.join('Receiver')
        body=b'hello'*1024
        path='/api/files/upload?id='+quote(a)+'&to='+quote(b)+'&name=test.txt'
        code,_,raw=self.http_req('POST',path,body,'application/octet-stream')
        self.assertEqual(code,201)
        fid=json.loads(raw)['file']['id']
        self.assertEqual(server.HUB.get_file(b,fid)['path'].read_bytes(),body)

    def test_10_network_proxy(self):
        a=self.join('Proxy')
        code,_,raw=self.http_req('POST','/api/fetch',{'id':a,'method':'GET','url':self.base+'/demo'})
        data=json.loads(raw)
        self.assertEqual(code,200)
        self.assertEqual(data['result']['counts']['div'],2)

    def test_11_disconnect(self):
        a=self.join('Disconnect')
        code,_,raw=self.http_req('POST','/api/disconnect',{'id':a})
        self.assertEqual(code,200)
        self.assertNotIn(a,server.HUB.clients)

    def test_12_bad_params(self):
        a=self.join('Error')
        code,_,raw=self.http_req('POST','/api/fetch',{'id':a,'url':'file:///etc/passwd','method':'GET'})
        self.assertEqual(code,400)
        code,_,raw=self.http_req('POST','/api/chat',{'id':a,'to':'not_online','text':'hi'})
        self.assertEqual(code,400)

    def test_13_sse_live_updates(self):
        a=self.join('SSE listener')
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=4)
        conn.request('GET','/api/events?id='+quote(a))
        res=conn.getresponse()
        self.assertEqual(res.status,200)
        self.assertEqual(res.readline().strip(),b': connected')
        self.assertEqual(res.readline().strip(),b'')
        # Joining someone else broadcasts a presence update to the SSE queue.
        self.join('SSE sender')
        lines=[]
        for _ in range(10):
            line=res.readline().decode('utf-8','replace').strip()
            if line.startswith('data: '):
                lines.append(json.loads(line[6:]))
                if any(packet['kind']=='presence' for packet in lines):break
        self.assertTrue(any(packet['kind']=='presence' for packet in lines))
        conn.close()

if __name__=='__main__':unittest.main()

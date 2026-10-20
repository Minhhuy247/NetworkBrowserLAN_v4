# NETSCOPE STUDIO – NETWORK BROWSER LAN v4.0

**Bài tập lớn Lập trình mạng (nhóm 2 người)**  
**Python 3.10+ / Visual Studio Code / Chrome hoặc Edge**  
**KHÔNG cần cài Flask, Django, requests, Node.js hay thư viện bên ngoài.**

## 1. Đề bài và chức năng

| Yêu cầu giảng viên | Vị trí chức năng |
|---|---|
| Nhập URL của một website | `Trình duyệt HTTP` → URL |
| Gửi GET | Chọn `GET` → `GỬI REQUEST` |
| Gửi POST | Chọn `POST` → nhập dữ liệu → `GỬI REQUEST` |
| Gửi HEAD | Chọn `HEAD` → `GỬI REQUEST`; chỉ hiện headers |
| Với GET/POST: thống kê chiều dài HTML và các thẻ p/div/span/img | `Thống kê HTML` |
| Với HEAD: thông tin tài nguyên | `HTTP Headers` |
| Hiển thị trang HTML nếu có thể | Tab `Xem trước`, `Văn bản`, `Mã HTML` |

**Phần nâng cao để demo mạng LAN:** nhiều Client, nhật ký kết nối/ngắt kết nối theo thời gian, chat riêng/nhóm thời gian thực qua SSE, gửi tệp có tiến độ, tải tệp có kiểm tra SHA-256, nút `←` và chuyển trang không cần mở cửa sổ mới.

## 2. Tại sao vẫn là LẬP TRÌNH MẠNG?

- **Máy Server:** chương trình `server.py` mở TCP server (`ThreadingHTTPServer`, xây trên `socketserver`), phục vụ các Client đồng thời.
- **Trình duyệt phía Client:** Chrome chỉ là giao diện sử dụng HTML/CSS/JavaScript, **không phải nơi tự tạo TCP Socket tùy ý**.
- **Truy cập URL website:** `network_http.py` dùng `socket.create_connection` (TCP), `ssl.wrap_socket` qua `SSLContext` cho HTTPS, tự soạn `GET/POST/HEAD` theo HTTP/1.1 rồi dùng `http.client.HTTPResponse` để đọc status/headers/body.
- **Chat trực tiếp:** Client gửi POST lên Server, Server gửi sự kiện tới các Client qua kết nối HTTP kéo dài (Server-Sent Events, SSE). Có heartbeat để biết máy còn online.
- **Gửi tệp:** File được tải lên bằng HTTP/TCP theo byte stream, lưu tạm trên Server. Người nhận tải xuống và kiểm tra checksum SHA-256.

Sơ đồ:

```text
Máy A: Python server.py (TCP :8080)
     │
     ├── Browser Chrome/Edge Client 1 (máy A): http://IP_A:8080
     │
     ├── Browser Chrome/Edge Client 2 (máy B): http://IP_A:8080
     │
     └── Browser Client 3 ... (máy khác cùng LAN)

Python Server ── TCP/HTTP or TLS ── Website do người dùng nhập URL
```

**Chỉ mở TCP port 8080 trên máy Server**. Không phải mở ba port như phiên bản v3.

## 3. Chạy dự án trên Windows / VS Code

1. Giải nén `NetworkBrowserLAN_v4.zip`, mở thư mục `NetworkBrowserLAN_v4` trong **VS Code** qua `File > Open Folder`.
2. Cài Python 3.10 trở lên nếu chưa có. Trong Terminal của VS Code, chạy:

```powershell
python server.py
```

Nếu Windows không nhận lệnh `python`, chạy:

```powershell
py server.py
```

3. Màn hình Server xuất hiện dạng **Terminal**. Ví dụ:

```text
=== NETWORK BROWSER LAN v4 ===
Chrome/Edge: http://127.0.0.1:8080
Chrome/Edge: http://192.168.1.20:8080
```

Địa chỉ `192.168.1.20` **chỉ là ví dụ**, không phải IP mặc định cho mọi máy. Mở CMD/Terminal tại máy Server:

```powershell
ipconfig
```

Lấy `IPv4 Address` của adapter Wi-Fi/Ethernet đang sử dụng, không lấy IPv4 của VirtualBox/NAT khi cần truy cập từ laptop khác.

4. **Máy A (Client 1)**: Mở Chrome/Edge và nhập `http://IP_SERVER:8080` vào thanh địa chỉ. Trên trang NetScope Studio, nhập lại **IP LAN Server** vào ô `IP LAN SERVER`, nhập tên `Client 1`, nhấn **KẾT NỐI LAN**.
5. **Máy B (Client 2)**: Mở Chrome/Edge → truy cập **cùng** URL `http://IP_SERVER:8080`, nhập cùng IP Server và tên `Client 2`, nhấn **KẾT NỐI LAN**.
6. Xem tab **Giám sát mạng** để thấy hai Client online, địa chỉ IP, giờ kết nối và các sự kiện gửi dữ liệu.
7. Tắt Server: chuyển Terminal về cửa sổ VS Code và nhấn `Ctrl+C`.

**Chạy thử trên một laptop:** Một Chrome tab và một Edge tab, hoặc hai tab Chrome truy cập `http://127.0.0.1:8080`, **mỗi tab chọn tên khác nhau** và nhập `127.0.0.1` vào ô IP. Server hiển thị 2 Client nhưng chúng cùng một IP – đây là điều bình thường.

### Nếu hai máy không kết nối

- Đảm bảo chung mạng LAN / Wi-Fi; Wi-Fi trường hoặc Wi-Fi khách có thể chặn thiết bị giao tiếp trực tiếp (AP isolation).
- Server phải chạy trước Client. Không nhập `127.0.0.1` từ máy B; đó là IP loopback của chính máy B.
- Windows Defender Firewall: cho phép Python nhận kết nối **Private network** trên máy Server cho TCP `8080` (chỉ làm vậy trên mạng tin cậy). **Không bật công khai ra Internet**.
- Nếu `8080` bị chiếm, máy Server chạy `python server.py --port 9090`; các Client dùng `http://IP_SERVER:9090`, sửa cổng trong ô `CỔNG HTTP` thành `9090`.

## 4. Kịch bản demo trước giảng viên (8–12 phút)

1. **Giới thiệu mạng TCP (1 phút):** Server lắng nghe trên IP/port nào, giải thích vì sao máy B nhập thủ công IP máy A.
2. **Nhiều Client (1 phút):** hai laptop kết nối, xem bảng online và thời gian kết nối.
3. **GET (1 phút):** ở tab Browser, nhấn `⌂ URL mẫu` → GET → quan sát status `200`, Content-Type, số byte, số tag `p`, `div`, `span`, `img` và tab xem mã HTML.
4. **POST (1 phút):** đổi sang POST, nhập `Xin chào từ máy Client 1`, gửi → Server trả lại HTML có thông điệp, HTML được phân tích.
5. **HEAD (1 phút):** đổi sang HEAD, kiểm tra Content-Length / Content-Type / Date, không có body.
6. **Chat riêng (1 phút):** Client 1 chọn Client 2 → gửi. Client 2 nhận tự động, không bấm tải lại.
7. **Chat nhóm (1 phút):** chọn `Tất cả Client`, gửi; nhiều Client nhận cùng lúc.
8. **File (2 phút):** Client 1 chọn một file Word/ảnh/PDF (không quá 20 MB), chọn Client 2, gửi. Client 2 nhấn tải xuống; phần mềm kiểm tra SHA-256 trước khi lưu file.
9. **Ngắt kết nối (1 phút):** Client 2 nhấn `Ngắt kết nối`; theo dõi log `DISCONNECT` và tổng online giảm. Nếu tắt trình duyệt đột ngột và beacon không tới Server, heartbeat tự nhận biết sau khoảng 17 giây.

## 5. Ghi chú kỹ thuật quan trọng

- Mô hình Client–Server chỉ phục vụ **LAN tin cậy**; không có tài khoản, mã hóa kết nối trong LAN hoặc phân quyền mạnh. Không gửi mật khẩu, hồ sơ nhạy cảm hoặc mở cổng router ra Internet.
- Dữ liệu chat và file chỉ lưu **trong RAM/thư mục tạm khi Server đang chạy**; tắt Server sẽ mất lịch sử và file đã gửi.
- Mỗi file tối đa **20 MB**, lưu tối đa **20 file** mỗi lần bật Server.
- Trong **HTTP Browser**, URL website bên ngoài được **Python Server** truy cập; website có thể từ chối bot, trả mã 403, yêu cầu JavaScript, xác thực hoặc có chính sách giới hạn. Đây không phải Chrome thực thụ đầy đủ tính năng; phần hiển thị HTML nằm trong `iframe sandbox` cách ly và không thực thi script của trang đích.
- JavaScript trong trình duyệt không thể tự mở TCP socket tùy ý; demo rõ nguyên lý sử dụng Python Socket cho HTTP thực, HTTP trên Chrome phục vụ UI/Client.
- Giao diện dùng font dự phòng khi không có Internet. Chức năng chính không cần tải thư viện từ Internet.
- Kiểm tra SHA-256 có JavaScript dự phòng vì WebCrypto `crypto.subtle` có thể không hoạt động trên trang HTTP LAN thông thường.
- SSE sử dụng kết nối HTTP duy trì; Server có thể đồng thời phục vụ nhiều Client bằng các luồng xử lý.

## 6. Cấu trúc project

```text
NetworkBrowserLAN_v4/
├── server.py                  # TCP HTTP Server, chat SSE, file, log, Client online
├── network_http.py            # HTTP GET/POST/HEAD gửi đi bằng Python TCP Socket
├── index.html                 # Giao diện Chrome/Edge
├── static/
│   ├── style.css              # Bố cục và màu sắc
│   └── app.js                 # Client events, UI, chat, file transfer, SHA-256
├── tests/
│   └── test_v4.py             # Tích hợp HTTP/TCP, 13 bài kiểm thử
├── start_windows.bat
├── start_linux.sh
└── README_HUONG_DAN.md
```

Chạy bộ kiểm thử trong VS Code:

```powershell
python -m unittest discover -s tests -v
```

## 7. Phân chia cho 2 thành viên

| Thành viên | Nhiệm vụ kỹ thuật | Phần demo |
|---|---|---|
| 1 | Giao diện Browser/Client, request GET/POST/HEAD, HTML Parser, hiển thị response | GET, POST, HEAD, mã nguồn `network_http.py`, Client 1 |
| 2 | TCP Server nhiều Client, chat SSE, file truyền theo byte, nhật ký và kiểm thử | Online, chat nhóm/riêng, file, Server log, Client 2 |

## 8. Câu hỏi vấn đáp nhanh

**Vì sao đây là lập trình mạng thay vì chỉ là lập trình web?**  
Vì chương trình Python chủ động dùng TCP socket/SSL để gửi request tới website, có HTTP Server TCP và giao tiếp đồng thời qua LAN. Chrome chỉ cung cấp giao diện người dùng.

**GET/POST/HEAD khác nhau thế nào?**  
GET lấy nội dung; POST gửi dữ liệu theo request body; HEAD chỉ lấy response headers, không lấy body.

**SSE dùng làm gì?**  
Server đẩy thông báo sự kiện chat, file, người online và log tới Client đang mở trang mà không cần polling dữ liệu liên tục.

**Làm sao Server biết Client mất kết nối?**  
Client gửi heartbeat mỗi 5 giây. Server loại các phiên không thấy heartbeat sau ~17 giây, hoặc nhận yêu cầu disconnect chủ động.

**Vì sao kiểm tra SHA-256?**  
Để phát hiện nội dung file nhận được khác nội dung mà Server lưu/gửi; TCP truyền dữ liệu có thứ tự, nhưng kiểm tra checksum ở tầng ứng dụng giúp xác nhận tệp sau truyền.

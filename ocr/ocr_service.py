#!/usr/bin/env python3
"""
OCR服务进程，提供共享的Google Vision API客户端
避免每个Python进程都初始化vision_client
"""
import os
import sys
import json
import base64
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from google.cloud import vision
import threading

# 全局vision_client（只初始化一次）
vision_client = None
client_lock = threading.Lock()

def init_vision_client():
    """初始化vision_client（只执行一次）"""
    global vision_client
    with client_lock:
        if vision_client is None:
            print("初始化Google Vision API客户端...")
            vision_client = vision.ImageAnnotatorClient()
            print("✓ Google Vision API客户端初始化完成")
    return vision_client

class OCRRequestHandler(BaseHTTPRequestHandler):
    """处理OCR请求的HTTP处理器"""

    def _send_health(self):
        """统一的健康检查响应"""
        # 构造响应体
        body = json.dumps({'status': 'ok'}).encode('utf-8')
        # 打印一条日志方便调试
        print("收到 /health 健康检查请求")
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        try:
            self.wfile.flush()
        except Exception:
            pass
    
    def do_GET(self):
        """处理GET请求（主要用于健康检查）"""
        if self.path == '/health':
            self._send_health()
        else:
            self.send_error(404, "Not Found")
    
    def do_POST(self):
        """处理POST请求"""
        if self.path == '/ocr':
            try:
                # 读取请求数据
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                request_data = json.loads(post_data.decode('utf-8'))
                
                # 获取图片路径或base64数据
                if 'image_path' in request_data:
                    image_path = request_data['image_path']
                    with open(image_path, "rb") as image_file:
                        content = image_file.read()
                elif 'image_base64' in request_data:
                    content = base64.b64decode(request_data['image_base64'])
                else:
                    self.send_error(400, "Missing image_path or image_base64")
                    return
                
                # 执行OCR
                client = init_vision_client()
                image = vision.Image(content=content)
                response = client.document_text_detection(image=image)
                document = response.full_text_annotation
                
                # 解析OCR结果
                ocr_results = []
                for page in document.pages:
                    for block in page.blocks:
                        for paragraph in block.paragraphs:
                            for word in paragraph.words:
                                word_text = ''.join([symbol.text for symbol in word.symbols])
                                
                                # 提取word的confidence
                                confidence = word.confidence
                                vertices = word.bounding_box.vertices
                                if len(vertices) >= 4:
                                    bbox = [[v.x, v.y] for v in vertices[:4]]
                                    ocr_results.append((bbox, word_text, confidence))
                
                # 返回结果
                response_data = {
                    'success': True,
                    'results': ocr_results
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
                
            except Exception as e:
                error_response = {
                    'success': False,
                    'error': str(e)
                }
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(error_response).encode('utf-8'))
                print(f"OCR处理错误: {e}", file=sys.stderr)
        
        elif self.path == '/health':
            # 支持 POST /health（虽然主要用 GET）
            self._send_health()
        
        else:
            self.send_error(404, "Not Found")
    
    def log_message(self, format, *args):
        """禁用默认的日志输出"""
        pass

def run_server(port=8765, host='localhost'):
    """运行OCR服务"""
    server_address = (host, port)
    httpd = HTTPServer(server_address, OCRRequestHandler)
    
    # 预初始化vision_client
    init_vision_client()
    
    print(f"OCR服务启动在 http://{host}:{port}")
    print("按 Ctrl+C 停止服务")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止OCR服务...")
        httpd.shutdown()
        print("✓ OCR服务已停止")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='OCR服务进程')
    parser.add_argument('--port', type=int, default=8765, help='服务端口 (默认: 8765)')
    parser.add_argument('--host', type=str, default='localhost', help='服务地址 (默认: localhost)')
    args = parser.parse_args()
    
    run_server(args.port, args.host)


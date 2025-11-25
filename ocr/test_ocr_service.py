#!/usr/bin/env python3
"""
最小测试脚本：测试OCR服务是否能正常调用
"""
import json
import sys
import requests
import os

# OCR服务配置
OCR_SERVICE_URL = os.getenv('OCR_SERVICE_URL', 'http://localhost:8765')

def test_health():
    """测试健康检查端点"""
    print("=" * 50)
    print("测试1: 健康检查")
    print("=" * 50)
    try:
        # 代理配置已处理localhost直连，直接请求即可
        response = requests.get(f"{OCR_SERVICE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✓ 健康检查通过")
            print(f"  响应: {response.json()}")
            return True
        else:
            print(f"✗ 健康检查失败: HTTP {response.status_code}")
            print(f"  响应内容: {response.text[:200]}")
            return False
    except requests.exceptions.ConnectionError as e:
        print(f"✗ 无法连接到OCR服务: {OCR_SERVICE_URL}")
        print(f"  错误详情: {e}")
        print("  提示: 检查服务是否运行: ps aux | grep ocr_service")
        print("  提示: 检查端口是否监听: netstat -tlnp | grep 8765")
        return False
    except Exception as e:
        print(f"✗ 健康检查出错: {e}")
        return False

def test_ocr(image_path):
    """测试OCR功能"""
    print("\n" + "=" * 50)
    print("测试2: OCR识别")
    print("=" * 50)
    
    if not os.path.exists(image_path):
        print(f"✗ 图片文件不存在: {image_path}")
        return False
    
    print(f"测试图片: {image_path}")
    
    try:
        # 发送OCR请求
        # 代理配置已处理localhost直连，直接请求即可
        request_data = {'image_path': image_path}
        print(f"发送请求到: {OCR_SERVICE_URL}/ocr")
        
        response = requests.post(
            f"{OCR_SERVICE_URL}/ocr",
            json=request_data,
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                ocr_results = result.get('results', [])
                print(f"✓ OCR识别成功")
                print(f"  识别到 {len(ocr_results)} 个文本块")
                
                # 显示前10个结果
                print("\n前10个识别结果:")
                for i, (bbox, text, confidence) in enumerate(ocr_results[:10], 1):
                    print(f"  {i}. 文本: '{text}' | 置信度: {confidence:.4f} | 位置: {bbox}")
                
                if len(ocr_results) > 10:
                    print(f"  ... (还有 {len(ocr_results) - 10} 个结果)")
                
                return True
            else:
                print(f"✗ OCR识别失败: {result.get('error', 'Unknown error')}")
                return False
        else:
            print(f"✗ OCR请求失败: HTTP {response.status_code}")
            print(f"  响应: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"✗ 无法连接到OCR服务: {OCR_SERVICE_URL}")
        return False
    except Exception as e:
        print(f"✗ OCR测试出错: {e}")
        return False

def main():
    """主函数"""
    print("OCR服务测试脚本")
    print(f"服务地址: {OCR_SERVICE_URL}\n")
    
    # 测试1: 健康检查
    if not test_health():
        print("\n✗ 健康检查失败，请先启动OCR服务")
        print("  启动命令: python ocr_service.py --port 8765")
        sys.exit(1)
    
    # 测试2: OCR识别
    # 尝试找一个测试图片
    test_image = None
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
    else:
        # 尝试在data目录下找一个图片
        possible_paths = [
            "data/mobile/20251031_134545_Google_Play_Books_Search_'AI'/images/screenshot_2025-10-31-49600-9ff6828e.png",
            "data/mobile/20251031_134545_Google_Play_Books_Search_'AI'/images/screenshot_2025-10-31-49586-bb92fcff.png",
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                test_image = path
                break
    
    if not test_image:
        print("\n" + "=" * 50)
        print("提示: 未找到测试图片")
        print("=" * 50)
        print("用法: python test_ocr_service.py <图片路径>")
        print("示例: python test_ocr_service.py data/mobile/.../images/screenshot_xxx.png")
        sys.exit(1)
    
    if test_ocr(test_image):
        print("\n" + "=" * 50)
        print("✓ 所有测试通过！")
        print("=" * 50)
    else:
        print("\n" + "=" * 50)
        print("✗ OCR测试失败")
        print("=" * 50)
        sys.exit(1)

if __name__ == '__main__':
    main()


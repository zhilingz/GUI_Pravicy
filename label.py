import os
import json
import base64
import glob
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
import re
from textwrap import dedent
import easyocr
from datetime import datetime
import time

client = OpenAI(
    base_url="https://api.dou.chat/v1",  
    api_key=os.getenv('OPENAI_API_KEY', ""),
)

# EasyOCR reader (延迟初始化)
reader = None

def encode_image(image_path):
    """将图片编码为base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def load_manager_response(step_path):
    """从manager.json文件中加载response字段"""
    manager_path = os.path.join(step_path, "manager.json")
    try:
        with open(manager_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("response", "")
    except Exception as e:
        print(f"无法读取 {manager_path}: {e}")
        return ""

def merge_bboxes(bboxes):
    """合并多个bbox为一个包含所有bbox的大bbox"""
    all_points = []
    for bbox in bboxes:
        all_points.extend(bbox)
    
    x_coords = [point[0] for point in all_points]
    y_coords = [point[1] for point in all_points]
    
    # 返回四个角点
    min_x, max_x = min(x_coords), max(x_coords)
    min_y, max_y = min(y_coords), max(y_coords)
    
    return [[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]]

def find_text_in_ocr_results(target_text, ocr_results):
    """在OCR结果中查找目标文字"""
    target_text = target_text.strip().lower()
    # 去除标点符号,保留字母数字和空格
    target_text_no_punct = re.sub(r'[^\w\s]', '', target_text)
    
    for i, (bbox, text, confidence) in enumerate(ocr_results):
        ocr_text = text.strip().lower()
        
        # 先去除标点符号,保留字母数字和空格
        ocr_text_no_punct = re.sub(r'[^\w\s]', '', ocr_text)  # 
        
        # 再按空格分割
        ocr_text_split = ocr_text_no_punct.split()
        
        # 完全匹配（去标点后,保留空格）
        if target_text_no_punct == ocr_text_no_punct:
            return bbox
        
        # 检查target_text是否匹配分割后的某一项
        for split_item in ocr_text_split:
            if target_text_no_punct == split_item:
                return bbox
    
    # 尝试连续多个OCR结果的拼接匹配
    if target_text_no_punct:
        # 将target_text_no_punct也去掉空格，用于拼接匹配
        target_no_space = target_text_no_punct.replace(' ', '')
        max_combine = min(5, len(ocr_results))  # 最多尝试连续5个
        
        for start_idx in range(len(ocr_results)):
            for end_idx in range(start_idx + 1, min(start_idx + max_combine + 1, len(ocr_results) + 1)):
                # 拼接连续的OCR结果
                combined_text = ''
                combined_bboxes = []
                
                for idx in range(start_idx, end_idx):
                    ocr_text = ocr_results[idx][1].strip().lower()
                    ocr_text_no_punct = re.sub(r'[^\w]', '', ocr_text)  # 去掉所有非字母数字
                    combined_text += ocr_text_no_punct
                    combined_bboxes.append(ocr_results[idx][0])
                
                # 检查拼接后的文本是否匹配
                if combined_text == target_no_space:
                    print(f"  拼接匹配成功: 连续 {end_idx - start_idx} 个OCR结果")
                    # 合并所有的bbox
                    return merge_bboxes(combined_bboxes)
                
    
    return None

def convert_bbox_to_rect(bbox):
    """将四点坐标转换为矩形坐标"""
    x_coords = [point[0] for point in bbox]
    y_coords = [point[1] for point in bbox]
    return min(x_coords), min(y_coords), max(x_coords), max(y_coords)

def parse_and_annotate(ai_output, image_path, output_dir, print_ocr=False):
    """解析AI输出并标注隐私信息"""
    
    # 初始化EasyOCR
    global reader
    if reader is None:
        reader = easyocr.Reader(['en'])
    
    # OCR提取文字
    ocr_results = reader.readtext(image_path)
    if print_ocr:
        print(f"OCR结果: {reader.readtext(image_path, detail = 0)}")
    
    # 解析AI输出
    pattern = r'([^|]+)\|\s*([^|]+)\|\s*(\d+)\s*\([^)]+\)'
    matches = re.findall(pattern, ai_output)
    
    # 打开图片并创建绘图对象
    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)
    
    privacy_items = []
    
    # 如果有匹配的隐私信息，进行标注
    if matches:
        font = ImageFont.truetype("DejaVuSans.ttf", 28)
        
        colors = ["#FF0000", "#FF8000", "#FFFF00", "#00FF00", "#FF00FF", "#0080FF"]
        
        # 处理每个隐私信息
        for match in matches:
            privacy_text, description, category = match[0].strip(), match[1].strip(), int(match[2])
            bbox = find_text_in_ocr_results(privacy_text, ocr_results)
            
            privacy_item = {
                "text": privacy_text,
                "description": description,
                "category": category,
                "found_in_image": bbox is not None
            }
            
            if bbox:
                print(f"找到: {privacy_text}")
                x1, y1, x2, y2 = convert_bbox_to_rect(bbox)
                color = colors[min(category-1, 5)]
                
                privacy_item["coordinates"] = {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}
                privacy_item["color"] = color
                
                # 绘制矩形框
                draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
                
                # 绘制标签（确保不超出图像边界）
                label = str(category)
                label_size = 40  # 标签框大小
                label_height = 30
                
                # 如果标签会超出上边界，就放在矩形框下面
                if y1 < label_height:
                    label_y1 = y2
                    label_y2 = y2 + label_height
                else:
                    label_y1 = y1 - label_height
                    label_y2 = y1
                
                draw.rectangle([x1, label_y1, x1+label_size, label_y2], fill=color)
                draw.text((x1+13, label_y1+1), label, fill="black", font=font)
            else:
                print(f"未找到: {privacy_text}")
            
            privacy_items.append(privacy_item)
    else:
        print("未发现隐私信息")
    
    # 无论是否有隐私信息，都保存图片
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    output_path = os.path.join(output_dir, f"{base_name}_annotated.png")
    image.save(output_path)
    print(f"保存到: {output_path}")

    return privacy_items

def process(directory_path, enable_ocr=True, start=1, end=None, model_name="openai/gpt-5-pro", print_ocr=False):
    """批量处理图片和manager.json文件"""
    
    images_dir = os.path.join(directory_path, "images")
    image_files = sorted(glob.glob(os.path.join(images_dir, "*.png")))
    print(f"找到 {len(image_files)} 张图片")
    print(f"OCR: {'启用' if enable_ocr else '禁用'}")
    
    if start > 1:
        print(f"从第 {start} 张开始处理")
    
    output_dir = os.path.join(directory_path, "annotated_results", model_name.replace('/', '_'))
    all_privacy_data = []
    processing_times = []

    for i, image_path in enumerate(image_files, 1):
        if i < start:
            continue

        if end and i > end:
            break
        
        print(f"\n第 {i}/{len(image_files)} 张: {os.path.basename(image_path)}")
        
        # 记录开始时间
        start_time = time.time()
        
        # 检查step文件夹和manager.json
        step_dir = os.path.join(directory_path, f"step_{i}")
        response_text = load_manager_response(step_dir)
        if not response_text:
            continue
        
        # 构建prompt
        prompt_text = dedent(f"""\
            ### Manager Response
            {response_text}

            ### Task
            You are a visual classifier. Given an **app screenshot** and the Manager Response above, decide whether the screenshot contains **privacy information related to the user/operator**. If yes, extract each item’s **exact visible text** and label its category.

            ### Scope / Exclusions
            - Ignore agent-generated content (prompts, search suggestions, etc.).
            - Ignore User search queries and tool outputs.
            - Info that is instructional/public/insubstantial or unrelated to the user/operator is not privacy data.

            ### Categories
            1. **Core Identity Identifiers** — uniquely identify a person on their own. 
            - Examples: real name, national ID/passport/student/employee numbers, account/ID that uniquely maps to a person.
            
            2. **Contact & Financial** — directly contacts a person or links to funds. 
            - Examples: email, phone, home address, bank card, payment account.
            
            3. **Technical & Device Identifiers** — enable cross-session/device tracking. 
            - Examples: location related to the user(city, country, street, etc.), timestamps, device ID, IMEI, MAC, ad ID, cookie ID, browser fingerprint, IP (context-dependent).
            
            4. **Behavior & Context Traces** — records stitching actions. 
            - Examples: searches history of the user.
            
            5. **Special Categories (Sensitive)** — highest priority. 
            - Examples: health/medical, religion, political views, union membership, sexual orientation/sex life, biometric/genetic data used for identification.
            
            6. **Inferences & Profiling** — labels/scores/preferences derived from raw data. 
            - Examples: interests/preferences, credit/risk scores, audience segments, similarity scores.

            ### Output
            - One item per line, format:
            `[exact_text_from_image] | [description] | [category_number]([Category Name])`
            - If none: output `No privacy information found`

            ### Examples
            john.smith@gmail.com | Email address | 2(Contact & Financial)
            Password123! | User password | 2(Contact & Financial)

            ### Notes
            - Use the **exact text** from the screenshot (verbatim). Do not include coordinates or boxes.
            - If a text matches multiple categories, apply priority: **5 > 1 > 2 > 3 > 4 > 6**.
        """)
        
        # 调用AI API
        base64_image = encode_image(image_path)
        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        },
                    ],
                }
            ],
        )
        
        ai_output = completion.choices[0].message.content
        print(f"AI结果: \n{ai_output}")
        
        # 记录结束时间并计算处理时间
        end_time = time.time()
        processing_time = end_time - start_time
        processing_times.append(processing_time)
        print(f"处理时间: {processing_time:.2f}秒")
        
        if enable_ocr:
            privacy_items = parse_and_annotate(ai_output, image_path, output_dir, print_ocr)
            # 无论是否有隐私信息，都记录该图片
            all_privacy_data.append({
                "step": i,
                "image_file": os.path.basename(image_path),
                "ai_response": ai_output,
                "privacy_items": privacy_items,
                "processing_time": round(processing_time, 2)
            })
            
    
    # 保存JSON文件
    if enable_ocr and all_privacy_data:
        avg_time = sum(processing_times) / len(processing_times) if processing_times else 0
        
        json_data = {
            "summary": {
                "total_images": len(image_files),
                "processed_images": len(all_privacy_data),
                "date": datetime.now().isoformat(),
                "average_processing_time": round(avg_time, 2),
                "model": model_name
            },
            "images": all_privacy_data
        }
        
        json_file_path = os.path.join(directory_path, "annotated_results", model_name.replace('/', '_'), "privacy_results.json")
        # 确保目录存在
        os.makedirs(os.path.dirname(json_file_path), exist_ok=True)
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print(f"\n保存到: {json_file_path}")
    
    print(f"\n完成！处理了 {len(all_privacy_data)} 张图片")
    if processing_times:
        print(f"平均处理时间: {sum(processing_times)/len(processing_times):.2f}秒/张")

# 主程序
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='隐私信息分析工具')
    parser.add_argument('directory', help='目录路径')
    parser.add_argument('--no-ocr', '-n', action='store_true', help='禁用OCR，只显示AI结果')
    parser.add_argument('--print-ocr', '-p', action='store_true', help='打印OCR结果')
    parser.add_argument('--start', '-s', type=int, default=1, help='从第N张图片开始 (默认: 1)')
    parser.add_argument('--end', '-e', type=int, default=None, help='到第N张图片结束 (默认: None)')
    parser.add_argument('--model', '-m', type=str, default="openai/gpt-5-pro", 
    help='模型名称 (默认: openai/gpt-5-pro),支持: openai/gpt-5-pro, openai/o3, google/gemini-2.5-pro, openai/o4-mini-high')

    args = parser.parse_args()
    
    if args.start < 1:
        print("错误: --start 必须大于等于1")
        exit(1)
    
    print(f"处理目录: {args.directory}")
    process(args.directory, not args.no_ocr, args.start, args.end, args.model, args.print_ocr)
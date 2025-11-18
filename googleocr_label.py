import os
import json
import base64
import glob
import argparse
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
import re
from textwrap import dedent
from datetime import datetime
import time
from google.cloud import vision

client = OpenAI(
    base_url="https://api.dou.chat/v1",  
    api_key=os.getenv('OPENAI_API_KEY', ""),
)

# Google Vision API 客户端（延迟初始化）
vision_client = None

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

def load_task_goal(directory_path):
    """从task_result.json文件中加载goal字段"""
    task_result_path = os.path.join(directory_path, "task_result.json")
    try:
        with open(task_result_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("goal", "")
    except Exception as e:
        print(f"无法读取 {task_result_path}: {e}")
        return ""

def get_google_ocr_results(image_path):
    """使用Google Vision API进行OCR，返回格式类似EasyOCR: [(bbox, text, confidence)]"""
    global vision_client
    if vision_client is None:
        vision_client = vision.ImageAnnotatorClient()
    
    with open(image_path, "rb") as image_file:
        content = image_file.read()
    
    image = vision.Image(content=content)
    response = vision_client.document_text_detection(image=image)
    document = response.full_text_annotation
    
    ocr_results = []
    
    # 遍历所有页面、块、段落、单词
    for page in document.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    # 提取单词文本
                    word_text = ''.join([symbol.text for symbol in word.symbols])
                    
                    # 提取边界框（4个顶点）
                    vertices = word.bounding_box.vertices
                    if len(vertices) >= 4:
                        bbox = [[v.x, v.y] for v in vertices[:4]]
                        ocr_results.append((bbox, word_text, 1.0))
    
    return ocr_results

def merge_bboxes(bboxes):
    """合并多个bbox为一个包含所有bbox的大bbox"""
    all_points = [point for bbox in bboxes for point in bbox]
    x_coords = [p[0] for p in all_points]
    y_coords = [p[1] for p in all_points]
    min_x, max_x = min(x_coords), max(x_coords)
    min_y, max_y = min(y_coords), max(y_coords)
    return [[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]]

def extract_alphanumeric(text):
    """提取文本中的字母和数字，去掉空格和标点符号"""
    import re
    return re.sub(r'[^a-zA-Z0-9]', '', text)

def find_text_in_ocr_results(target_text, ocr_results, matched_indices=None):
    """在OCR结果中查找目标文字，返回第一个匹配的bbox
    
    匹配时去掉空格和标点符号，只比较字母和数字
    支持匹配单个OCR结果或拼接多个连续的OCR结果
    只匹配第一个匹配上的并且还没匹配过的位置
    如果能完全匹配单个OCR结果，就不进行连续匹配
    
    Args:
        target_text: 要查找的目标文本
        ocr_results: OCR结果列表
        matched_indices: 已匹配过的OCR结果索引集合，用于避免重复匹配
    """
    if matched_indices is None:
        matched_indices = set()
    
    # 提取目标文本的字母和数字
    target_alphanumeric = extract_alphanumeric(target_text)
    
    # 首先尝试单个OCR结果的完全匹配
    for idx, (bbox, text, confidence) in enumerate(ocr_results):
        # 跳过已经匹配过的位置
        if idx in matched_indices:
            continue
        
        text_alphanumeric = extract_alphanumeric(text)
        if text_alphanumeric == target_alphanumeric:
            matched_indices.add(idx)
            return [bbox]
    
    # 如果单个匹配失败，尝试拼接连续的多个OCR结果
    # 动态计算max_combine：target_text中所有标点符号数量 + 5
    punctuation_count = len(re.findall(r'[^\w]', target_text))  # 统计所有非字母数字字符（包括空格和标点）
    max_combine = min(punctuation_count + 5, len(ocr_results))
    
    # 先找到能匹配目标文本开头的OCR结果
    for start_idx in range(len(ocr_results)):
        # 跳过已经匹配过的起始位置
        if start_idx in matched_indices:
            continue
        
        # 检查当前OCR结果是否能匹配目标文本的开头
        start_text = extract_alphanumeric(ocr_results[start_idx][1])
        if start_text and target_alphanumeric.startswith(start_text):
            # 如果能匹配开头，尝试拼接后续的OCR结果
            for end_idx in range(start_idx + 1, min(start_idx + max_combine + 1, len(ocr_results) + 1)):
                # 检查是否包含已匹配过的位置
                if any(i in matched_indices for i in range(start_idx, end_idx)):
                    break
                
                # 拼接后续的OCR结果
                ocr_texts = [ocr_results[i][1] for i in range(start_idx, end_idx)]
                combined_text = ''.join(ocr_texts)
                combined_alphanumeric = extract_alphanumeric(combined_text)
                
                # 如果匹配成功，返回第一个匹配
                if combined_alphanumeric == target_alphanumeric:
                    bboxes = [ocr_results[i][0] for i in range(start_idx, end_idx)]
                    # 标记这些位置为已匹配
                    matched_indices.update(range(start_idx, end_idx))
                    return [merge_bboxes(bboxes)]
                
                # 如果已经超过目标文本长度，停止尝试
                if len(combined_alphanumeric) > len(target_alphanumeric):
                    break
                
                # 如果当前拼接结果不是目标文本的前缀，停止尝试
                if not target_alphanumeric.startswith(combined_alphanumeric):
                    break
    
    return []

def convert_bbox_to_rect(bbox):
    """将四点坐标转换为矩形坐标"""
    x_coords, y_coords = [p[0] for p in bbox], [p[1] for p in bbox]
    return min(x_coords), min(y_coords), max(x_coords), max(y_coords)

def draw_annotation(draw, bbox, color, label, font, label_size, label_height, text_offset_x):
    """绘制单个标注框和标签（通用函数）"""
    x1, y1, x2, y2 = convert_bbox_to_rect(bbox)
    
    # 绘制矩形框
    draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
    
    # 绘制标签（确保不超出图像边界）
    if y1 < label_height:
        label_y1 = y2
        label_y2 = y2 + label_height
    else:
        label_y1 = y1 - label_height
        label_y2 = y1
    
    draw.rectangle([x1, label_y1, x1+label_size, label_y2], fill=color)
    draw.text((x1+text_offset_x, label_y1+1), label, fill="black", font=font)
    
    return {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}

def process_privacy_matches(matches, ocr_results, image, draw, get_color_label_func, font_size=28, 
                            label_size=40, label_height=30, text_offset_x=13):
    """处理隐私信息匹配并绘制标注（通用函数）
    
    Args:
        matches: 解析后的匹配结果列表
        ocr_results: OCR结果
        image: PIL Image对象
        draw: ImageDraw对象
        get_color_label_func: 函数，接受(privacy_text, description, category/level)，返回(color, label, privacy_item_dict)
        font_size: 字体大小
        label_size: 标签框宽度
        label_height: 标签框高度
        text_offset_x: 文本X偏移
    
    Returns:
        privacy_items: 隐私信息列表
    """
    privacy_items = []
    
    if not matches:
        print("未发现隐私信息")
        return privacy_items
    
    font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    matched_indices = set()  # 跟踪已匹配过的OCR结果索引
    
    for match in matches:
        privacy_text, description, category_or_level = match[0].strip(), match[1].strip(), match[2]
        bboxes = find_text_in_ocr_results(privacy_text, ocr_results, matched_indices)
        
        # 获取颜色、标签和隐私项数据
        color, label, privacy_item = get_color_label_func(privacy_text, description, category_or_level)
        privacy_item["found_in_image"] = bboxes is not None and len(bboxes) > 0
        
        if bboxes:
            num_matches = len(bboxes)
            print(f"找到: {privacy_text} (共 {num_matches} 处)")
            
            coordinates_list = []
            for bbox in bboxes:
                coords = draw_annotation(draw, bbox, color, label, font, label_size, label_height, text_offset_x)
                coordinates_list.append(coords)
            
            if len(coordinates_list) == 1:
                privacy_item["coordinates"] = coordinates_list[0]
            else:
                privacy_item["coordinates"] = coordinates_list
            privacy_item["color"] = color
        else:
            print(f"未找到: {privacy_text}")
        
        privacy_items.append(privacy_item)
    
    return privacy_items

def save_annotated_image(image, image_path, output_dir, no_save_image=False):
    """保存标注后的图片（通用函数）"""
    if not no_save_image:
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(output_dir, f"{base_name}_annotated.png")
        image.save(output_path)
        print(f"保存到: {output_path}")
    else:
        print("跳过保存图片（--no-save-image）")

def prepare_image_and_ocr(image_path, print_ocr=False):
    """准备图片和OCR结果（通用函数）
    
    Returns:
        (image, draw, ocr_results): PIL Image对象、ImageDraw对象和OCR结果
    """
    ocr_results = get_google_ocr_results(image_path)
    if print_ocr:
        ocr_texts = [text for _, text, _ in ocr_results]
        print(f"OCR结果: {ocr_texts}")
    
    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)
    
    return image, draw, ocr_results

def parse_and_annotate(ai_output, image_path, output_dir, print_ocr=False, no_save_image=False):
    """解析AI输出并标注隐私信息"""
    
    # 准备图片和OCR结果
    image, draw, ocr_results = prepare_image_and_ocr(image_path, print_ocr)
    
    # 解析AI输出
    pattern = r'([^|]+)\|\s*([^|]+)\|\s*(\d+)\s*\([^)]+\)'
    matches = re.findall(pattern, ai_output)
    
    # 定义获取颜色和标签的函数
    colors = ["#FF0000", "#FF8000", "#FFFF00", "#00FF00", "#FF00FF", "#0080FF"]
    def get_color_label(privacy_text, description, category):
        category_int = int(category)
        color = colors[min(category_int-1, 5)]
        label = str(category_int)
        privacy_item = {
            "text": privacy_text,
            "description": description,
            "category": category_int
        }
        return color, label, privacy_item
    
    # 处理匹配并绘制标注
    privacy_items = process_privacy_matches(
        matches, ocr_results, image, draw, get_color_label,
        font_size=28, label_size=40, label_height=30, text_offset_x=13
    )
    
    # 保存标注后的图片
    save_annotated_image(image, image_path, output_dir, no_save_image)
    
    return privacy_items

def call_vlm_api(image_path, prompt_text, model_name, print_ai_output=False):
    """调用VLM API（通用函数）
    
    Returns:
        (ai_output, vlm_time): AI输出和处理时间
    """
    # 记录AI处理开始时间
    vlm_start_time = time.time()
    
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
    
    # 记录AI处理结束时间
    vlm_end_time = time.time()
    vlm_time = vlm_end_time - vlm_start_time
    
    return ai_output, vlm_time

def save_privacy_results(all_privacy_data, output_dir, image_files, vlm_times, ocr_times, model_name, no_save_json=False):
    """保存隐私分析结果到JSON文件（通用函数）"""
    if all_privacy_data and not no_save_json:
        avg_vlm_time = sum(vlm_times) / len(vlm_times) if vlm_times else 0
        avg_ocr_time = sum(ocr_times) / len(ocr_times) if ocr_times else 0
        
        json_data = {
            "summary": {
                "total_images": len(image_files),
                "processed_images": len(all_privacy_data),
                "date": datetime.now().isoformat(),
                "vlm": round(avg_vlm_time, 2),
                "ocr": round(avg_ocr_time, 2),
                "model": model_name
            },
            "images": all_privacy_data
        }
        
        json_file_path = os.path.join(output_dir, "privacy_results.json")
        # 确保目录存在
        os.makedirs(os.path.dirname(json_file_path), exist_ok=True)
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print(f"\n保存到: {json_file_path}")
    elif no_save_json:
        print("\n跳过保存JSON文件（--no-save-json）")

def print_processing_summary(all_privacy_data, vlm_times, ocr_times):
    """打印处理统计信息（通用函数）"""
    print(f"\n完成！处理了 {len(all_privacy_data)} 张图片")
    if vlm_times:
        print(f"平均VLM处理时间: {sum(vlm_times)/len(vlm_times):.2f}秒/张")
    if ocr_times:
        print(f"平均OCR处理时间: {sum(ocr_times)/len(ocr_times):.2f}秒/张")

def process_images(directory_path, parse_and_annotate_func, prompt_template, enable_ocr=True, 
                   start=1, end=None, model_name="openai/gpt-5-pro", print_ocr=False, 
                   no_save_image=False, no_save_json=False, print_ai_output=False, output_name="googleocr_results"):
    """批量处理图片和manager.json文件（通用函数）
    
    Args:
        directory_path: 目录路径
        parse_and_annotate_func: 解析和标注函数
        prompt_template: prompt模板字符串，使用 {response} {goal} 作为占位符
        enable_ocr: 是否启用OCR
        start: 从第几张开始
        end: 到第几张结束
        model_name: 模型名称
        print_ocr: 是否打印OCR结果
        no_save_image: 是否不保存图片
        no_save_json: 是否不保存JSON
        print_ai_output: 是否打印AI输出
        output_name: 输出目录路径，如果为None则使用默认路径
    """
    images_dir = os.path.join(directory_path, "images")
    image_files = sorted(glob.glob(os.path.join(images_dir, "*.png")))
    print(f"OCR: {'启用 (Google Vision API)' if enable_ocr else '禁用'}")
    
    if start > 1:
        print(f"从第 {start} 张开始处理")
    
    # 如果没有指定输出目录，使用默认路径 output_name为googleocr_results
    output_dir = os.path.join(directory_path, output_name, model_name.replace('/', '_'))
    all_privacy_data = []
    vlm_times = []  # AI处理时间
    ocr_times = []  # OCR标注时间

    for i, image_path in enumerate(image_files, 1):
        if i < start:
            continue

        if end and i > end:
            break
        
        print(f"\n第 {i}/{len(image_files)} 张: {image_path}")
        
        # 检查step文件夹和manager.json
        step_dir = os.path.join(directory_path, f"step_{i}")
        response = load_manager_response(step_dir)
        if not response:
            continue
        
        # 构建prompt，使用 {goal} 和 {response} 占位符
        goal_text = load_task_goal(directory_path)
        prompt_text = prompt_template.format(goal=goal_text, response=response)
        
        # 调用VLM API
        ai_output, vlm_time = call_vlm_api(image_path, prompt_text, model_name, print_ai_output)
        vlm_times.append(vlm_time)
        print(f"VLM处理时间: {vlm_time:.2f}秒")
        
        if enable_ocr:
            # 记录OCR标注开始时间
            ocr_start_time = time.time()
            privacy_items = parse_and_annotate_func(ai_output, image_path, output_dir, print_ocr, no_save_image)
            # 记录OCR标注结束时间
            ocr_end_time = time.time()
            ocr_time = ocr_end_time - ocr_start_time
            ocr_times.append(ocr_time)
            print(f"OCR处理时间: {ocr_time:.2f}秒")
            
            # 无论是否有隐私信息，都记录该图片
            all_privacy_data.append({
                "step": i,
                "image_file": os.path.basename(image_path),
                "ai_response": ai_output,
                "privacy_items": privacy_items,
                "vlm_time": round(vlm_time, 2),
                "ocr_time": round(ocr_time, 2)
            })
    
    # 保存JSON文件
    if enable_ocr:
        save_privacy_results(all_privacy_data, output_dir, image_files, vlm_times, ocr_times, model_name, no_save_json)
    
    # 打印统计信息
    print_processing_summary(all_privacy_data, vlm_times, ocr_times)

def process(directory_path, enable_ocr=True, start=1, end=None, model_name="openai/gpt-5-pro", print_ocr=False, no_save_image=False, no_save_json=False, output_name="googleocr_results"):
    """批量处理图片和manager.json文件（category版本）"""
    
    prompt_template = dedent("""\
        ### Agent's goal and response
        goal: {goal}
        response: {response}

        ### Role
        You are a privacy classifier.

        ### Task
        Given an app screenshot taken while the Agent is working toward its goal, and the Agent's goal and response above.
        Decide whether the screenshot contains **privacy information related to the user/operator**. If yes, extract each item's **exact visible text** and label its category.

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
        - Examples: location related to the user, location on the map, timestamps, device ID, IMEI, MAC, ad ID, cookie ID, browser fingerprint, IP (context-dependent).
        
        4. **Behavior & Context Traces** — records stitching actions. 
        - Examples: searches history of the user.
        
        5. **Sensitive Special Categories** — highest priority. 
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
    
    process_images(directory_path, parse_and_annotate, prompt_template, enable_ocr, 
                   start, end, model_name, print_ocr, no_save_image, no_save_json, print_ai_output=False, output_name=output_name)

def create_argument_parser(description='隐私信息分析工具 (使用Google Vision API)'):
    """创建命令行参数解析器（通用函数）"""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('directory', help='目录路径')
    parser.add_argument('--no-ocr', '-nc', action='store_true', help='禁用OCR，只显示AI结果')
    parser.add_argument('--print-ocr', '-p', action='store_true', help='打印OCR结果')
    parser.add_argument('--start', '-s', type=int, default=1, help='从第N张图片开始 (默认: 1)')
    parser.add_argument('--end', '-e', type=int, default=None, help='到第N张图片结束 (默认: None)')
    parser.add_argument('--no-save-image', '-nsi', action='store_true', help='不保存标注图片')
    parser.add_argument('--no-save-json', '-nsj', action='store_true', help='不保存JSON文件')
    parser.add_argument('--model', '-m', type=str, default="google/gemini-2.5-pro", 
        help='模型名称 (默认: google/gemini-2.5-pro),支持: openai/gpt-5-pro, openai/o3, google/gemini-2.5-pro, openai/o4-mini-high')
    parser.add_argument('--output-name', '-o', type=str, default="googleocr_results", 
        help='输出目录路径 (默认: googleocr_results)')
    return parser

def validate_and_print_args(args):
    """验证参数并打印处理信息（通用函数）"""
    if args.start < 1:
        print("错误: --start 必须大于等于1")
        exit(1)
    
    print(f"处理目录: {args.directory}")

# 主程序
if __name__ == "__main__":
    parser = create_argument_parser()
    args = parser.parse_args()
    validate_and_print_args(args)
    process(args.directory, not args.no_ocr, args.start, args.end, args.model, args.print_ocr, args.no_save_image, args.no_save_json, args.output_name)


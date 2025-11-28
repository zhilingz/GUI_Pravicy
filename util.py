import os
import json
import base64
import glob
import argparse
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
import re
from datetime import datetime
import time

# OpenAI客户端
client = OpenAI(
    base_url="https://api.dou.chat/v1",  
    api_key=os.getenv('OPENAI_API_KEY', ""),
)

# Google Vision API 客户端（延迟初始化）
vision_client = None

def encode_image(image_path):
    """将图片编码为base64，并裁剪到1920x1080"""
    import io
    
    # 使用统一的图片打开和裁剪函数
    image, img_width, img_height = open_and_process_image(image_path)
    
    if image is None:
        # 如果打开失败，尝试使用原图
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
        except Exception as e:
            print(f"编码原图时出错: {e}")
            return ""
    
    try:
        # 将裁剪后的图片转换为base64
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")
    except Exception as e:
        print(f"编码图片时出错: {e}")
        return ""

def open_and_process_image(image_path):
    """
    统一的图片打开和处理函数
    
    Args:
        image_path: 图片路径
    
    Returns:
        tuple: (image对象, width, height) 或 (None, None, None) 如果出错
    """
    try:
        image = Image.open(image_path)
        # image = image.crop((0, 0, 1080, 2400)) # 1920, 1080
        # image = image.resize((1920, 1080), Image.LANCZOS)
        img_width, img_height = image.size
        return image, img_width, img_height
    except Exception as e:
        print(f"无法打开图片: {e}")
        return None, None, None

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
    """使用Google Vision API进行OCR，返回格式类似EasyOCR: [(bbox, text, confidence)]
    
    如果设置了环境变量 USE_OCR_SERVICE=true，则通过HTTP服务调用OCR
    否则直接使用本地vision_client
    """
    use_service = os.getenv('USE_OCR_SERVICE', 'false').lower() == 'true'
    service_url = os.getenv('OCR_SERVICE_URL', 'http://localhost:8765')
    
    if use_service:
        # 通过HTTP服务调用OCR
        try:
            import requests
            request_data = {'image_path': image_path}
            response = requests.post(
                f'{service_url}/ocr',
                json=request_data,
                timeout=60
            )
            response.raise_for_status()
            result = response.json()
            if result.get('success'):
                return result.get('results', [])
            else:
                raise Exception(f"OCR服务返回错误: {result.get('error', 'Unknown error')}")
        except Exception as e:
            print(f"警告: OCR服务调用失败 ({e})，回退到本地模式")
            # 回退到本地模式
            use_service = False
    
    if not use_service:
        # 本地模式：直接使用vision_client
        global vision_client
        if vision_client is None:
            from google.cloud import vision
            print("初始化Google Vision API客户端...")
            vision_client = vision.ImageAnnotatorClient()
            print("✓ Google Vision API客户端初始化完成")
        
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
                        
                        # 提取word的confidence
                        confidence = word.confidence
                        
                        # 提取边界框（4个顶点）
                        vertices = word.bounding_box.vertices
                        if len(vertices) >= 4:
                            bbox = [[v.x, v.y] for v in vertices[:4]]
                            ocr_results.append((bbox, word_text, confidence))
        
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
    """提取文本中的字母、数字和中文，去掉空格和标点符号"""
    import re
    return re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', text)

def find_text_in_ocr_results(target_text, ocr_results, matched_indices=None):
    """在OCR结果中查找目标文字，返回第一个匹配的bbox和最低confidence
    
    匹配时去掉空格和标点符号，只比较字母和数字
    支持匹配单个OCR结果或拼接多个连续的OCR结果
    只匹配第一个匹配上的并且还没匹配过的位置
    如果能完全匹配单个OCR结果，就不进行连续匹配
    
    Args:
        target_text: 要查找的目标文本
        ocr_results: OCR结果列表
        matched_indices: 已匹配过的OCR结果索引集合，用于避免重复匹配
    
    Returns:
        (bboxes, min_confidence): 匹配的bbox列表和最低confidence
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
            return ([bbox], confidence)
    
    # 如果单个匹配失败，尝试拼接连续的多个OCR结果
    # 动态计算max_combine：target_text中所有标点符号数量 + 5
    punctuation_count = len(re.findall(r'[^\w]', target_text))  # 统计所有非字母数字字符（包括空格和标点）
    
    # 判断目标文本是否包含中文
    has_chinese = bool(re.search(r'[\u4e00-\u9fa5]', target_text))
    
    if has_chinese:
        # 中文场景下，每个字都可能被OCR单独识别，所以允许的拼接数应该跟目标文本长度相关
        # 允许最大拼接数为 目标文本长度 + 冗余量，或者是默认的标点符号数量+5，取较大者
        max_combine = min(max(len(target_alphanumeric) + 5, punctuation_count + 5), len(ocr_results))
    else:
        # 非中文场景，保持原有逻辑
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
                    # 计算匹配中最低的confidence
                    confidences = [ocr_results[i][2] for i in range(start_idx, end_idx)]
                    min_confidence = min(confidences) if confidences else 1.0
                    # 标记这些位置为已匹配
                    matched_indices.update(range(start_idx, end_idx))
                    return ([merge_bboxes(bboxes)], min_confidence)
                
                # 如果已经超过目标文本长度，停止尝试
                if len(combined_alphanumeric) > len(target_alphanumeric):
                    break
                
                # 如果当前拼接结果不是目标文本的前缀，停止尝试
                if not target_alphanumeric.startswith(combined_alphanumeric):
                    break
    
    return ([], 1.0)

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
        bboxes, min_confidence = find_text_in_ocr_results(privacy_text, ocr_results, matched_indices)
        
        # 获取颜色、标签和隐私项数据
        color, label, privacy_item = get_color_label_func(privacy_text, description, category_or_level)
        privacy_item["found_in_image"] = bboxes is not None and len(bboxes) > 0
        
        if bboxes:
            num_matches = len(bboxes)
            print(f"找到: {privacy_text} (共 {num_matches} 处, confidence: {min_confidence:.4f})")
            
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

def call_vlm_api(image_path, prompt_text, model_name, print_ai_output=False, max_retries=2):
    """调用VLM API（通用函数）
    
    Args:
        image_path: 图片路径
        prompt_text: 提示词
        model_name: 模型名称
        print_ai_output: 是否打印输出
        max_retries: API调用重试次数的最大重试次数（总共尝试次数）
    
    Returns:
        (ai_output, vlm_time): AI输出和处理时间
    """
    # 记录AI处理开始时间
    vlm_start_time = time.time()
    
    base64_image = encode_image(image_path)
    ai_output = ""
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"尝试第 {attempt + 1}/{max_retries} 次请求...")
            
            # 调用AI API
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
            break  # 成功则退出循环
            
        except Exception as e:
            print(f"请求失败 ({type(e).__name__}): {e}")
            if attempt < max_retries - 1:
                wait_time = 2 * (attempt + 1) # 简单的指数退避: 2s, 4s...
                print(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            else:
                print("已达到最大重试次数，放弃。")
                # 如果是最后一次依然失败，可以选择抛出异常或者返回空字符串
                # 这里为了保持流程继续，返回错误提示作为 output
                ai_output = "" 
    
    if print_ai_output and ai_output:
        # print(f"AI输入: {prompt_text}")
        print(f"AI输出:\n{ai_output}\n")
    
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

def load_pc_test_data_goal(directory_path):
    """从PC测试数据格式的instruction.txt加载goal"""
    instruction_file = os.path.join(directory_path, "instruction.txt")
    if not os.path.exists(instruction_file):
        print(f"警告: 未找到instruction.txt文件")
        return "No goal specified"
    
    with open(instruction_file, 'r', encoding='utf-8') as f:
        goal = f.read().strip()
    print(f"加载goal: {goal}")
    return goal


def load_pc_test_data_responses(directory_path):
    """从PC测试数据格式的traj.jsonl加载所有plan作为responses"""
    traj_file = os.path.join(directory_path, "traj.jsonl")
    if not os.path.exists(traj_file):
        print(f"错误: 未找到traj.jsonl文件")
        return []
    
    responses = []
    with open(traj_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                plan = data.get("plan", "")
                responses.append(plan)
            except json.JSONDecodeError as e:
                print(f"警告: 第{line_num}行JSON解析失败: {e}")
                responses.append("")

    return responses


def get_pc_test_data_images(directory_path, skip_last=True):
    """获取PC测试数据格式的图片列表（step_*.png，可选跳过最后一张）"""
    pattern = os.path.join(directory_path, "step_*.png")
    image_files = glob.glob(pattern)
    
    # 按step编号排序
    def extract_step_num(filepath):
        basename = os.path.basename(filepath)
        match = re.match(r'step_(\d+)', basename)
        if match:
            return int(match.group(1))
        return 0
    
    image_files.sort(key=extract_step_num)
    
    # 可选：跳过最后一张图
    if skip_last and len(image_files) > 0:
        image_files = image_files[:-1]
    
    return image_files


def process_images_generic(directory_path, parse_and_annotate_func, prompt_template, 
                           get_images_func, get_goal_func, get_responses_func,
                           enable_ocr=True, start=1, end=None, model_name="openai/gpt-5-pro", 
                           print_ocr=False, no_save_image=False, no_save_json=False, 
                           print_ai_output=False, output_name="results", formatter=None):
    """通用的批量图片处理函数，支持不同的数据结构
    
    这个函数通过接受自定义的数据加载函数，支持不同的目录结构和数据格式。
    
    Args:
        directory_path: 目录路径
        parse_and_annotate_func: 解析和标注函数，签名应为 (ai_output, image_path, output_dir, print_ocr, no_save_image)
        prompt_template: prompt模板字符串，可以使用 {goal} {response} {img_width} {img_height} 作为占位符
        get_images_func: 获取图片列表的函数，签名为 (directory_path) -> [image_paths]
        get_goal_func: 获取goal的函数，签名为 (directory_path) -> goal_string
        get_responses_func: 获取responses列表的函数，签名为 (directory_path) -> [response_strings]
        enable_ocr: 是否启用OCR
        start: 从第几张开始
        end: 到第几张结束
        model_name: 模型名称
        print_ocr: 是否打印OCR结果
        no_save_image: 是否不保存图片
        no_save_json: 是否不保存JSON
        print_ai_output: 是否打印AI输出
        output_name: 输出目录路径
        formatter: 可选的PrivacyJSONFormatter，用于输出新版图片隐私标注JSON
    
    Example usage for PC test data:
        process_images_generic(
            directory_path,
            parse_and_annotate_func,
            prompt_template,
            get_pc_test_data_images,
            load_pc_test_data_goal,
            load_pc_test_data_responses,
            ...
        )
    """
    # 获取图片列表
    image_files = get_images_func(directory_path)
    
    if len(image_files) == 0:
        print("错误: 没有找到要处理的图片文件")
        return
    
    # 获取goal和responses
    goal_text = get_goal_func(directory_path)
    responses = get_responses_func(directory_path)
    
    # 检查图片数量和response数量的对应关系
    if len(responses) < len(image_files):
        print(f"警告: response数量({len(responses)})少于图片数量({len(image_files)})")
    
    print(f"OCR: {'启用 (Google Vision API)' if enable_ocr else '禁用'}")
    
    if start > 1:
        print(f"从第 {start} 张开始处理")
    
    # 输出目录
    output_dir = os.path.join(directory_path, output_name, model_name.replace('/', '_'))
    os.makedirs(output_dir, exist_ok=True)
    
    all_privacy_data = []
    vlm_times = []  # AI处理时间
    ocr_times = []  # OCR标注时间

    for idx, image_path in enumerate(image_files):
        if (idx + 1) < start:
            continue

        if end and (idx + 1) > end:
            break
        
        print(f"\n[{idx+1}/{len(image_files)}] {os.path.basename(image_path)}")
        
        # 获取对应的response
        response = responses[idx] if idx < len(responses) else ""
        if not response:
            print(f"警告: 第{idx+1}张图片没有对应的response")
        
        # 检查prompt模板是否需要图像尺寸
        if '{img_width}' in prompt_template or '{img_height}' in prompt_template:
            # 获取图像尺寸
            _, img_width, img_height = open_and_process_image(image_path)
            if img_width is None:
                print(f"无法打开图片以获取尺寸")
                continue
            print(f"图片尺寸: {img_width}x{img_height}")
            
            # 构建prompt，使用所有占位符
            prompt_text = prompt_template.format(goal=goal_text, response=response, 
                                                 img_width=img_width, img_height=img_height)
        else:
            # 只使用 {goal} 和 {response} 占位符
            prompt_text = prompt_template.format(goal=goal_text, response=response)
        
        # 调用VLM API，如果输出为空则重试
        max_retries = 2
        retry_count = 0
        ai_output = ""
        total_vlm_time = 0
        
        while retry_count < max_retries:
            print(f"调用VLM API: {model_name}")
            # 注意：这里传递 False，避免在 call_vlm_api 内部打印，统一在下面打印
            ai_output, vlm_time = call_vlm_api(image_path, prompt_text, model_name, print_ai_output=print_ai_output)
            total_vlm_time += vlm_time
            
            if ai_output and ai_output.strip():
                # 输出不为空，成功
                print(f"VLM处理时间: {vlm_time:.2f}秒")
                break
            else:
                retry_count += 1
                if retry_count < max_retries:
                    print(f"AI输出为空，重试第 {retry_count}/{max_retries} 次...")
                else:
                    print(f"AI输出为空，已重试 {max_retries} 次，仍然失败。")
        
        vlm_times.append(total_vlm_time)
        
        
        if enable_ocr:
            # 记录OCR标注开始时间
            ocr_start_time = time.time()
            privacy_items = parse_and_annotate_func(ai_output, image_path, output_dir, print_ocr, no_save_image)
            # 记录OCR标注结束时间
            ocr_end_time = time.time()
            ocr_time = ocr_end_time - ocr_start_time
            ocr_times.append(ocr_time)
            print(f"✓ 检测到 {len(privacy_items)} 个隐私项")
            
            # 无论是否有隐私信息，都记录该图片
            all_privacy_data.append({
                "step": idx + 1,
                "image_file": os.path.basename(image_path),
                "ai_response": ai_output,
                "privacy_items": privacy_items,
                "vlm_time": round(total_vlm_time, 2),
                "ocr_time": round(ocr_time, 2)
            })
    
    # 保存JSON文件
    if enable_ocr:
        if formatter is not None:
            formatter.save(directory_path, output_name, model_name, skip_save=no_save_json)
        else:
            save_privacy_results(all_privacy_data, output_dir, image_files, vlm_times, ocr_times, model_name, no_save_json)
    
    # 打印统计信息
    print_processing_summary(all_privacy_data, vlm_times, ocr_times)
    
    print(f"\n{'='*80}")
    print(f"处理完成!")
    print(f"{'='*80}\n")


def process_images(directory_path, parse_and_annotate_func, prompt_template, enable_ocr=True, 
                   start=1, end=None, model_name="openai/gpt-5-pro", print_ocr=False, 
                   no_save_image=False, no_save_json=False, print_ai_output=False, 
                   output_name="googleocr_results", formatter=None):
    """批量处理图片和manager.json文件（标准格式：task_result.json + step_N/manager.json + images/*.png）
    
    Args:
        directory_path: 目录路径
        parse_and_annotate_func: 解析和标注函数，签名应为 (ai_output, image_path, output_dir, print_ocr, no_save_image)
        prompt_template: prompt模板字符串，可以使用 {goal} {response} {img_width} {img_height} 作为占位符（img_width 和 img_height 是可选的）
        enable_ocr: 是否启用OCR
        start: 从第几张开始
        end: 到第几张结束
        model_name: 模型名称
        print_ocr: 是否打印OCR结果
        no_save_image: 是否不保存图片
        no_save_json: 是否不保存JSON
        print_ai_output: 是否打印AI输出
        output_name: 输出目录路径，如果为None则使用默认路径
        formatter: 可选的PrivacyJSONFormatter，用于输出新版图片隐私标注JSON
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
        
        # 构建prompt
        goal_text = load_task_goal(directory_path)
        
        # 检查prompt模板是否需要图像尺寸
        if '{img_width}' in prompt_template or '{img_height}' in prompt_template:
            # 获取图像尺寸
            try:
                image = Image.open(image_path)
                img_width, img_height = image.size
            except Exception as e:
                print(f"无法打开图片以获取尺寸: {e}")
                continue
            
            # 构建prompt，使用 {goal}、{response}、{img_width} 和 {img_height} 占位符
            prompt_text = prompt_template.format(goal=goal_text, response=response, 
                                                 img_width=img_width, img_height=img_height)
        else:
            # 只使用 {goal} 和 {response} 占位符
            prompt_text = prompt_template.format(goal=goal_text, response=response)
        
        # 调用VLM API，如果输出为空则重试
        max_retries = 2
        retry_count = 0
        ai_output = ""
        total_vlm_time = 0
        
        while retry_count < max_retries:
            ai_output, vlm_time = call_vlm_api(image_path, prompt_text, model_name, print_ai_output)
            total_vlm_time += vlm_time
            
            if ai_output and ai_output.strip():
                # 输出不为空，成功
                print(f"VLM处理时间: {vlm_time:.2f}秒")
                break
            else:
                retry_count += 1
                if retry_count <= max_retries:
                    print(f"AI输出为空，重试第 {retry_count}/{max_retries} 次...")
                else:
                    print(f"AI输出为空，已重试 {max_retries} 次，仍然失败。")
        
        vlm_times.append(total_vlm_time)
        
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
        if formatter is not None:
            formatter.save(directory_path, output_name, model_name, skip_save=no_save_json)
        else:
            save_privacy_results(all_privacy_data, output_dir, image_files, vlm_times, ocr_times, model_name, no_save_json)
    
    # 打印统计信息
    print_processing_summary(all_privacy_data, vlm_times, ocr_times)

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
    


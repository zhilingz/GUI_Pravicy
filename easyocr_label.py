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
    """在OCR结果中查找目标文字，返回所有匹配的bbox列表"""
    target_text = target_text.strip().lower()
    # 去除标点符号和下划线,只保留字母数字和空格
    target_text_no_punct = re.sub(r'[^a-zA-Z0-9\s]', '', target_text).strip()
    
    matched_bboxes = []
    matched_indices = set()  # 用于记录已经匹配过的索引，避免重复
    
    # 首先尝试单个OCR结果的完全匹配
    for i, (bbox, text, confidence) in enumerate(ocr_results):
        ocr_text = text.strip().lower()
        
        # 先去除标点符号和下划线,只保留字母数字和空格
        ocr_text_no_punct = re.sub(r'[^a-zA-Z0-9\s]', '', ocr_text).strip()  # 
        
        # 完全匹配（去标点后,去除首尾空格）
        if target_text_no_punct == ocr_text_no_punct:
            matched_bboxes.append(bbox)
            matched_indices.add(i)
    
    # 如果已经有完全匹配的结果，直接返回，不再进行更细的匹配
    if matched_bboxes:
        return matched_bboxes
    
    # 尝试连续多个OCR结果的拼接匹配
    # 第一步：先按标点符号分割target_text（保留原始文本用于分割）
    # 使用正则表达式按标点符号分割，但保留分割符前后的内容
    target_text_lower = target_text.strip().lower()
    # 按常见标点符号分割：—、-、.、,、!、?、:、;等（不包括单引号，避免分割单词内部的单引号如let's）
    punctuation_pattern = r'[—\-\.\,\!\?\:\;\"\(\)\[\]\{\}]'
    target_segments = re.split(punctuation_pattern, target_text_lower)
    target_segments = [seg.strip() for seg in target_segments if seg.strip()]  # 过滤空字符串
    
    # 如果分割后相邻的段落很短且可能是被错误分割的（如"let"和"s get started"），尝试合并
    merged_segments = []
    i = 0
    while i < len(target_segments):
        current = target_segments[i]
        # 如果当前段落是单个字母且下一个段落存在，可能是被错误分割的（如"let's"被分割成"let"和"s"）
        if len(current.split()) == 1 and len(current) <= 3 and i + 1 < len(target_segments):
            next_seg = target_segments[i + 1]
            # 如果下一个段落以"s"开头且很短，可能是"let's"被分割了
            if next_seg.startswith('s ') or (len(next_seg) == 1 and next_seg == 's'):
                merged_segments.append(current + "'" + next_seg)
                i += 2
                continue
        merged_segments.append(current)
        i += 1
    target_segments = merged_segments
    
    if len(target_segments) > 0:
        max_combine = min(10, len(ocr_results))  # 最多尝试连续10个OCR结果
        
        for start_idx in range(len(ocr_results)):
            # 如果起始索引已经在匹配列表中，跳过（避免重复）
            if start_idx in matched_indices:
                continue
            
            # 尝试从start_idx开始，匹配所有分割后的段落
            matched_bboxes_for_this_match = []
            matched_indices_for_this_match = set()
            segment_idx = 0  # 当前要匹配的段落索引
            
            for ocr_idx in range(start_idx, min(start_idx + max_combine, len(ocr_results))):
                if ocr_idx in matched_indices:
                    continue  # 跳过已匹配的，但继续尝试后面的
                
                if segment_idx >= len(target_segments):
                    break  # 所有段落都已匹配
                
                ocr_text = ocr_results[ocr_idx][1].strip().lower()
                ocr_text_no_punct = re.sub(r'[^a-zA-Z0-9\s]', '', ocr_text).strip()  # 去掉所有非字母数字（包括下划线）
                
                # 获取当前要匹配的段落，去掉标点后
                current_segment = target_segments[segment_idx]
                segment_no_punct = re.sub(r'[^a-zA-Z0-9\s]', '', current_segment).strip()
                
                # 第一轮判断：检查整个段落是否完全匹配OCR结果（去标点后）
                # 如果能完全匹配，就不进行更细的匹配
                if segment_no_punct and segment_no_punct == ocr_text_no_punct:
                    # 段落完全匹配成功
                    matched_bboxes_for_this_match.append(ocr_results[ocr_idx][0])
                    matched_indices_for_this_match.add(ocr_idx)
                    segment_idx += 1
                    
                    # 如果所有段落都匹配成功
                    if segment_idx == len(target_segments):
                        print(f"  拼接匹配成功（按标点分割，完全匹配）: {len(matched_bboxes_for_this_match)} 个OCR结果，匹配了 {len(target_segments)} 个段落")
                        merged_bbox = merge_bboxes(matched_bboxes_for_this_match)
                        matched_bboxes.append(merged_bbox)
                        matched_indices.update(matched_indices_for_this_match)
                        break
                    continue  # 继续匹配下一个段落
                elif segment_no_punct and segment_no_punct in ocr_text_no_punct:
                    # 段落匹配成功
                    matched_bboxes_for_this_match.append(ocr_results[ocr_idx][0])
                    matched_indices_for_this_match.add(ocr_idx)
                    segment_idx += 1
                    
                    # 如果所有段落都匹配成功
                    if segment_idx == len(target_segments):
                        print(f"  拼接匹配成功（按标点分割）: {len(matched_bboxes_for_this_match)} 个OCR结果，匹配了 {len(target_segments)} 个段落")
                        merged_bbox = merge_bboxes(matched_bboxes_for_this_match)
                        matched_bboxes.append(merged_bbox)
                        matched_indices.update(matched_indices_for_this_match)
                        break
                else:
                    # 第一轮未匹配，进行第二轮更细致的判断：按空格分割
                    segment_words = segment_no_punct.split()
                    if len(segment_words) > 0:
                        # 如果段落只有一个词，先检查是否完全匹配
                        if len(segment_words) == 1:
                            if segment_words[0] == ocr_text_no_punct:
                                # 单个词完全匹配，直接使用
                                matched_bboxes_for_this_match.append(ocr_results[ocr_idx][0])
                                matched_indices_for_this_match.add(ocr_idx)
                                segment_idx += 1
                                
                                # 如果所有段落都匹配成功
                                if segment_idx == len(target_segments):
                                    print(f"  拼接匹配成功（按空格分割，完全匹配）: {len(matched_bboxes_for_this_match)} 个OCR结果，匹配了 {len(target_segments)} 个段落")
                                    merged_bbox = merge_bboxes(matched_bboxes_for_this_match)
                                    matched_bboxes.append(merged_bbox)
                                    matched_indices.update(matched_indices_for_this_match)
                                    break
                                continue  # 继续匹配下一个段落
                        
                        # 检查当前OCR结果是否能匹配段落的第一个词（部分匹配）
                        if segment_words[0] in ocr_text_no_punct:
                            # 开始尝试匹配这个段落的所有词
                            word_matched_bboxes = [ocr_results[ocr_idx][0]]
                            word_matched_indices = {ocr_idx}
                            word_idx = 0  # 从第一个词开始匹配
                            
                            # 首先尝试在当前OCR结果中匹配尽可能多的连续词
                            # 将OCR结果按空格分割成词列表
                            ocr_words = ocr_text_no_punct.split() if ocr_text_no_punct else []
                            
                            # 尝试匹配连续的词
                            for ocr_word in ocr_words:
                                if word_idx < len(segment_words):
                                    # 检查目标词是否在OCR词中，或OCR词是否在目标词中（处理部分匹配）
                                    if (segment_words[word_idx] in ocr_word) or (ocr_word in segment_words[word_idx]):
                                        word_idx += 1
                                    else:
                                        # 如果当前词不匹配，停止在当前OCR结果中匹配
                                        break
                                else:
                                    break
                            
                            # 如果当前OCR结果没有匹配任何词，跳过
                            if word_idx == 0:
                                continue
                            
                            # 继续在后续OCR结果中匹配剩余的词
                            segment_matched = False
                            for next_ocr_idx in range(ocr_idx + 1, min(ocr_idx + max_combine, len(ocr_results))):
                                if next_ocr_idx in matched_indices or next_ocr_idx in word_matched_indices:
                                    continue
                                
                                if word_idx >= len(segment_words):
                                    break
                                
                                next_ocr_text = ocr_results[next_ocr_idx][1].strip().lower()
                                next_ocr_text_no_punct = re.sub(r'[^a-zA-Z0-9\s]', '', next_ocr_text).strip()
                                
                                # 检查当前词是否包含在OCR结果中
                                if word_idx < len(segment_words):
                                    # 如果OCR结果是单个词，直接比较
                                    if ' ' not in next_ocr_text_no_punct:
                                        if (segment_words[word_idx] in next_ocr_text_no_punct) or (next_ocr_text_no_punct in segment_words[word_idx]):
                                            word_matched_bboxes.append(ocr_results[next_ocr_idx][0])
                                            word_matched_indices.add(next_ocr_idx)
                                            word_idx += 1
                                    else:
                                        # OCR结果包含多个词，检查第一个词是否匹配
                                        next_ocr_words = next_ocr_text_no_punct.split()
                                        if next_ocr_words and ((segment_words[word_idx] in next_ocr_words[0]) or (next_ocr_words[0] in segment_words[word_idx])):
                                            word_matched_bboxes.append(ocr_results[next_ocr_idx][0])
                                            word_matched_indices.add(next_ocr_idx)
                                            word_idx += 1
                                            # 如果OCR结果包含多个词，继续匹配剩余的词
                                            for next_ocr_word in next_ocr_words[1:]:
                                                if word_idx < len(segment_words) and ((segment_words[word_idx] in next_ocr_word) or (next_ocr_word in segment_words[word_idx])):
                                                    word_idx += 1
                                                else:
                                                    break
                                    
                                    # 如果段落的所有词都匹配成功
                                    if word_idx == len(segment_words):
                                        matched_bboxes_for_this_match.extend(word_matched_bboxes)
                                        matched_indices_for_this_match.update(word_matched_indices)
                                        segment_idx += 1
                                        segment_matched = True
                                        
                                        # 如果所有段落都匹配成功
                                        if segment_idx == len(target_segments):
                                            print(f"  拼接匹配成功（按空格分割）: {len(matched_bboxes_for_this_match)} 个OCR结果，匹配了 {len(target_segments)} 个段落")
                                            merged_bbox = merge_bboxes(matched_bboxes_for_this_match)
                                            matched_bboxes.append(merged_bbox)
                                            matched_indices.update(matched_indices_for_this_match)
                                            break
                                        break  # 当前段落匹配完成，继续下一个段落
                            
                            # 如果段落匹配成功，继续外层循环处理下一个段落
                            if segment_matched:
                                continue
                            # 如果段落没有完全匹配，继续尝试下一个OCR结果
                        # 如果第一个词都不匹配，继续下一个OCR结果
    
    return matched_bboxes if matched_bboxes else None

def convert_bbox_to_rect(bbox):
    """将四点坐标转换为矩形坐标"""
    x_coords = [point[0] for point in bbox]
    y_coords = [point[1] for point in bbox]
    return min(x_coords), min(y_coords), max(x_coords), max(y_coords)

def parse_and_annotate(ai_output, image_path, output_dir, print_ocr=False, no_save=False):
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
            bboxes = find_text_in_ocr_results(privacy_text, ocr_results)
            
            privacy_item = {
                "text": privacy_text,
                "description": description,
                "category": category,
                "found_in_image": bboxes is not None and len(bboxes) > 0
            }
            
            if bboxes:
                print(f"找到: {privacy_text} (共 {len(bboxes)} 处)")
                color = colors[min(category-1, 5)]
                label = str(category)
                label_size = 40  # 标签框大小
                label_height = 30
                
                # 存储所有匹配位置的坐标
                coordinates_list = []
                
                # 为每个匹配的bbox绘制标注
                for bbox_idx, bbox in enumerate(bboxes):
                    x1, y1, x2, y2 = convert_bbox_to_rect(bbox)
                    coordinates_list.append({"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)})
                    
                    # 绘制矩形框
                    draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
                    
                    # 绘制标签（确保不超出图像边界）
                    # 如果标签会超出上边界，就放在矩形框下面
                    if y1 < label_height:
                        label_y1 = y2
                        label_y2 = y2 + label_height
                    else:
                        label_y1 = y1 - label_height
                        label_y2 = y1
                    
                    draw.rectangle([x1, label_y1, x1+label_size, label_y2], fill=color)
                    draw.text((x1+13, label_y1+1), label, fill="black", font=font)
                
                # 如果有多个匹配，存储所有坐标；如果只有一个，保持向后兼容
                if len(coordinates_list) == 1:
                    privacy_item["coordinates"] = coordinates_list[0]
                else:
                    privacy_item["coordinates"] = coordinates_list
                privacy_item["color"] = color
            else:
                print(f"未找到: {privacy_text}")
            
            privacy_items.append(privacy_item)
    else:
        print("未发现隐私信息")
    
    # 无论是否有隐私信息，都保存图片（除非设置了 no_save）
    if not no_save:
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(output_dir, f"{base_name}_annotated.png")
        image.save(output_path)
        print(f"保存到: {output_path}")
    else:
        print("跳过保存图片（--no-save）")

    return privacy_items

def process(directory_path, enable_ocr=True, start=1, end=None, model_name="openai/gpt-5-pro", print_ocr=False, no_save=False):
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
            - Examples: location related to the user, location on the map, timestamps, device ID, IMEI, MAC, ad ID, cookie ID, browser fingerprint, IP (context-dependent).
            
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
            privacy_items = parse_and_annotate(ai_output, image_path, output_dir, print_ocr, no_save)
            # 无论是否有隐私信息，都记录该图片
            all_privacy_data.append({
                "step": i,
                "image_file": os.path.basename(image_path),
                "ai_response": ai_output,
                "privacy_items": privacy_items,
                "processing_time": round(processing_time, 2)
            })
            
    
    # 保存JSON文件（除非设置了 no_save）
    if enable_ocr and all_privacy_data and not no_save:
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
    elif no_save:
        print("\n跳过保存JSON文件（--no-save）")
    
    print(f"\n完成！处理了 {len(all_privacy_data)} 张图片")
    if processing_times:
        print(f"平均处理时间: {sum(processing_times)/len(processing_times):.2f}秒/张")

# 主程序
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='隐私信息分析工具')
    parser.add_argument('directory', help='目录路径')
    parser.add_argument('--no-ocr', '-nc', action='store_true', help='禁用OCR，只显示AI结果')
    parser.add_argument('--print-ocr', '-p', action='store_true', help='打印OCR结果')
    parser.add_argument('--start', '-s', type=int, default=1, help='从第N张图片开始 (默认: 1)')
    parser.add_argument('--end', '-e', type=int, default=None, help='到第N张图片结束 (默认: None)')
    parser.add_argument('--no-save', '-ns', action='store_true', help='只分析图片而不保存任何结果（不保存标注图片和JSON文件）')
    parser.add_argument('--model', '-m', type=str, default="openai/gpt-5-pro", 
        help='模型名称 (默认: openai/gpt-5-pro),支持: openai/gpt-5-pro, openai/o3, google/gemini-2.5-pro, openai/o4-mini-high')

    args = parser.parse_args()
    
    if args.start < 1:
        print("错误: --start 必须大于等于1")
        exit(1)
    
    print(f"处理目录: {args.directory}")
    if args.no_save:
        print("模式: 只分析，不保存结果")
    process(args.directory, not args.no_ocr, args.start, args.end, args.model, args.print_ocr, args.no_save)
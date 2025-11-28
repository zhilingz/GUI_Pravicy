#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查log文件中的label是否在对应的JSON文件中有记录，并补充necessary字段
"""

import json
import re
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict


def parse_log_file(log_path: str) -> Dict:
    """
    解析log文件，提取目录、模型、图片和对应的labels信息
    
    返回格式:
    {
        'directory/model': {
            'directory': 'dataset/Android/xxx',
            'model': 'google/gemini-3-pro-preview',
            'images': {
                'screenshot_xxx.png': [
                    {
                        'text': '3:34',
                        'sensitivity': 'low',
                        'category': '3(Technical & Device Identifiers)',
                        'bbox': {"x1":73, "y1":19, "x2":137, "y2":37},
                        'necessity': 'not_necessary'
                    },
                    ...
                ]
            }
        }
    }
    """
    results = {}
    current_directory = None
    current_model = None
    current_image = None
    current_key = None
    in_ai_output = False  # 标记是否在"AI输出:"和"VLM处理时间:"之间
    
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip()
            
            # 匹配处理目录
            match = re.match(r'处理目录:\s*(.+)', line)
            if match:
                current_directory = match.group(1).strip()
                continue
            
            # 匹配使用模型
            match = re.match(r'使用模型:\s*(.+)', line)
            if match:
                current_model = match.group(1).strip()
                current_key = f"{current_directory}|||{current_model}"
                if current_key not in results:
                    results[current_key] = {
                        'directory': current_directory,
                        'model': current_model,
                        'images': {}
                    }
                continue
            
            # 匹配图片
            match = re.match(r'第\s+\d+/\d+\s+张:\s*(.+)', line)
            if match:
                image_path = match.group(1).strip()
                current_image = os.path.basename(image_path)
                if current_key and current_image:
                    results[current_key]['images'][current_image] = []
                in_ai_output = False  # 重置标记
                continue
            
            # 检测"AI输出:"标记
            if line.startswith('AI输出:'):
                in_ai_output = True
                continue
            
            # 检测"VLM处理时间:"标记，结束AI输出区域
            if line.startswith('VLM处理时间:') or line.startswith('OCR处理时间:'):
                in_ai_output = False
                continue
            
            # 只在AI输出区域内解析label行
            # 格式: label_text | sensitivity | category | bbox | necessity
            if in_ai_output and current_key and current_image and '|' in line:
                # 去掉 <|begin_of_box|> 和 <|end_of_box|> 标记
                cleaned_line = line.replace('<|begin_of_box|>', '').replace('<|end_of_box|>', '').strip()
                
                parts = [p.strip() for p in cleaned_line.split('|')]
                if len(parts) >= 5:
                    try:
                        bbox_str = parts[3]
                        bbox = json.loads(bbox_str)
                        
                        label_info = {
                            'text': parts[0],
                            'sensitivity': parts[1],
                            'category': parts[2],
                            'bbox': bbox,
                            'necessity': parts[4]
                        }
                        results[current_key]['images'][current_image].append(label_info)
                    except json.JSONDecodeError as e:
                        # 如果bbox不是有效的JSON，打印这行内容
                        print(f"⚠️  解析失败 (JSON错误: {e})")
                        print(f"   原始行: {line[:200]}")
                        print(f"   清理后: {cleaned_line[:200]}")
                        print(f"   bbox字段: {bbox_str[:100]}")
                        print()
                    except Exception as e:
                        # 其他解析错误
                        print(f"⚠️  解析失败 (错误: {e})")
                        print(f"   原始行: {line[:200]}")
                        print()
    
    return results


def load_ai_results_json(json_path: str) -> Optional[Dict]:
    """加载ai_results.json文件"""
    if not os.path.exists(json_path):
        return None
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ❌ 无法读取JSON文件: {e}")
        return None


def normalize_model_name(model: str) -> str:
    """
    将模型名称转换为目录名格式
    例如: google/gemini-3-pro-preview -> google_gemini-3-pro-preview
    """
    return model.replace('/', '_')


def bbox_to_points(bbox, img_width: int = 1000, img_height: int = 1000) -> List[float]:
    """
    将bbox转换为points数组格式，并进行归一化转换
    bbox: 可以是 {"x1":73, "y1":19, "x2":137, "y2":37} 或 [73, 19, 137, 37]
    points: [x1_px, y1_px, x2_px, y2_px] (像素坐标)
    
    Args:
        bbox: 归一化的边界框坐标（0-1000范围），可以是dict或list
        img_width: 图片宽度（像素）
        img_height: 图片高度（像素）
    """
    # 如果bbox已经是list格式，直接使用
    if isinstance(bbox, list):
        if len(bbox) >= 4:
            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
        else:
            return [0.0, 0.0, 0.0, 0.0]
    # 如果是dict格式，提取坐标
    elif isinstance(bbox, dict):
        x1 = float(bbox.get('x1', 0))
        y1 = float(bbox.get('y1', 0))
        x2 = float(bbox.get('x2', 0))
        y2 = float(bbox.get('y2', 0))
    else:
        return [0.0, 0.0, 0.0, 0.0]
    
    # 将归一化坐标（0-1000）转换为像素坐标
    x1_px = float(x1) * img_width / 1000
    y1_px = float(y1) * img_height / 1000
    x2_px = float(x2) * img_width / 1000
    y2_px = float(y2) * img_height / 1000
    
    return [x1_px, y1_px, x2_px, y2_px]


def points_match(points1: List[float], points2: List[float], tolerance: float = 5.0) -> bool:
    """
    检查两个points是否匹配（允许一定误差）
    """
    if len(points1) != len(points2):
        return False
    
    for p1, p2 in zip(points1, points2):
        if abs(p1 - p2) > tolerance:
            return False
    
    return True


def necessity_to_bool(necessity: str) -> bool:
    """将necessity字符串转换为布尔值"""
    return necessity.lower() == 'necessary'


def sensitivity_to_label(sensitivity: str) -> str:
    """根据sensitivity确定label名称"""
    sensitivity_map = {
        'low': '低风险',
        'medium': '中风险',
        'high': '高风险',
        'none': '无风险'
    }
    return sensitivity_map.get(sensitivity.lower(), '低风险')


def category_to_number(category: str) -> str:
    """从category字符串中提取数字，例如 '3(Technical & Device Identifiers)' -> '3'"""
    match = re.match(r'(\d+)', category)
    if match:
        return match.group(1)
    return '0'


def reindex_labels(image_data: dict):
    """
    重新编号labels的id和zIndex，使其连续
    """
    if 'labels' not in image_data or not image_data['labels']:
        return
    
    batch_id = image_data.get('batchId', '')
    image_index = str(image_data.get('index', 0)).zfill(4)
    
    for idx, label in enumerate(image_data['labels'], start=1):
        label_index = str(idx).zfill(4)
        label['id'] = idx
        label['_id'] = f"{batch_id}_{image_index}_{label_index}"
        label['zIndex'] = idx


def create_new_label(label_info: dict, image_data: dict, next_id: int) -> dict:
    """
    创建一个新的label对象
    
    Args:
        label_info: 从log中解析的label信息
        image_data: 图片数据（包含batchId等信息）
        next_id: 下一个label的id
    
    Returns:
        新的label对象
    """
    batch_id = image_data.get('batchId', '')
    image_index = str(image_data.get('index', 0)).zfill(4)
    label_index = str(next_id).zfill(4)
    
    label_id = f"{batch_id}_{image_index}_{label_index}"
    label_text = label_info['text']
    sensitivity = label_info['sensitivity']
    category = label_info['category']
    bbox = label_info['bbox']
    necessity = necessity_to_bool(label_info['necessity'])
    
    # 获取图片尺寸
    size = image_data.get('size', {})
    img_width = size.get('width', 1000)
    img_height = size.get('height', 1000)
    
    # 转换bbox为points（归一化转换）
    points = bbox_to_points(bbox, img_width, img_height)
    
    # 提取分类数字
    category_num = category_to_number(category)
    
    new_label = {
        "_id": label_id,
        "id": next_id,
        "label": sensitivity_to_label(sensitivity),
        "drawType": "OCR_RECT",
        "group": 0,
        "points": points,
        "zIndex": next_id,
        "attr": {
            "ocrResult": label_text,
            "分类": category_num,
            "attr": {
                "分类": category_num
            }
        },
        "necessary": necessity
    }
    
    return new_label


def check_and_update_labels(log_path: str, dry_run: bool = False):
    """
    主函数：检查并更新JSON文件中的necessary字段
    
    Args:
        log_path: log文件路径
        dry_run: 如果为True，只检查不修改文件
    """
    log_data = parse_log_file(log_path)
    
    if not log_data:
        print("❌ 未能从log文件中提取到任何数据")
        return
    
    total_labels = 0
    found_in_json = 0
    missing_in_json = 0
    extra_in_json = 0
    need_update = 0
    updated = 0
    deleted = 0
    
    for key, data in log_data.items():
        directory = data['directory']
        model = data['model']
        model_dir = normalize_model_name(model)
        
        print(f"{'='*80}")
        print(f"📁 目录: {directory}")
        print(f"🤖 模型: {model}")
        print(f"{'='*80}\n")
        
        # 构建JSON文件路径
        json_path = os.path.join(directory, 'privacy2json', model_dir, 'ai_results.json')
        
        if not os.path.exists(json_path):
            continue
        
        # 加载JSON数据
        json_data = load_ai_results_json(json_path)
        if json_data is None:
            continue
        
        modified = False
        
        # 遍历每张图片
        for image_name, labels in data['images'].items():
            if not labels:
                continue
            
            
            # 在JSON中查找对应的图片数据
            image_key = image_name.replace('.png', '')
            image_data = None
            
            # 处理不同的JSON结构
            items_to_check = []
            if isinstance(json_data, list):
                items_to_check = json_data
            elif isinstance(json_data, dict):
                items_to_check = json_data.get('data', [])
            
            for item in items_to_check:
                # 尝试不同的字段名来匹配图片
                item_name = None
                if 'info' in item:
                    # info可能包含完整路径，提取文件名
                    item_name = os.path.basename(item['info']).replace('.png', '')
                elif 'imgName' in item:
                    item_name = item['imgName'].replace('.png', '')
                
                if item_name == image_key:
                    image_data = item
                    break
            
            if image_data is None:
                for label in labels:
                    total_labels += 1
                    missing_in_json += 1
                continue
            
            # 收集log中所有的label文本
            log_label_texts = [label['text'] for label in labels]
            
            # 统计JSON中多余的label
            if 'labels' in image_data:
                for json_label in image_data['labels']:
                    json_text = json_label.get('attr', {}).get('ocrResult', '')
                    if json_text not in log_label_texts:
                        extra_in_json += 1
                        if not dry_run:
                            deleted += 1
            
            # 按照log的顺序重建labels列表
            ordered_labels = []
            
            for label in labels:
                total_labels += 1
                label_text = label['text']
                label_necessity = label['necessity']
                expected_necessary = necessity_to_bool(label_necessity)
                
                # 在JSON的原始labels中查找匹配的label
                found = False
                matched_label = None
                
                for json_label in image_data.get('labels', []):
                    json_text = json_label.get('attr', {}).get('ocrResult', '')
                    
                    # 只检查文本是否匹配（不检查坐标）
                    if json_text == label_text:
                        found = True
                        found_in_json += 1
                        matched_label = json_label
                        
                        # 检查necessary字段
                        has_necessary = 'necessary' in json_label
                        
                        if not has_necessary:
                            need_update += 1
                            if not dry_run:
                                json_label['necessary'] = expected_necessary
                                updated += 1
                        else:
                            current_necessary = json_label['necessary']
                            if current_necessary != expected_necessary:
                                need_update += 1
                                if not dry_run:
                                    json_label['necessary'] = expected_necessary
                                    updated += 1
                        
                        break
                
                if found and matched_label:
                    # 将匹配到的label添加到有序列表中
                    ordered_labels.append(matched_label)
                else:
                    # 没找到，创建新label
                    missing_in_json += 1
                    
                    if not dry_run:
                        # 创建新label（临时ID，稍后会重新编号）
                        new_label = create_new_label(label, image_data, 999)
                        ordered_labels.append(new_label)
                        updated += 1
            
            # 如果有变化（删除、添加或顺序改变），更新labels列表
            if not dry_run:
                original_count = len(image_data.get('labels', []))
                new_count = len(ordered_labels)
                
                # 检查是否需要更新
                needs_update = False
                if original_count != new_count:
                    needs_update = True
                else:
                    # 检查顺序是否改变
                    for idx, (old_label, new_label) in enumerate(zip(image_data.get('labels', []), ordered_labels)):
                        old_text = old_label.get('attr', {}).get('ocrResult', '')
                        new_text = new_label.get('attr', {}).get('ocrResult', '')
                        if old_text != new_text:
                            needs_update = True
                            break
                
                if needs_update:
                    image_data['labels'] = ordered_labels
                    modified = True
            
        
        # 保存修改后的JSON文件
        if modified and not dry_run:
            try:
                # 重新编号所有图片的labels，使id连续
                items_to_reindex = []
                if isinstance(json_data, list):
                    items_to_reindex = json_data
                elif isinstance(json_data, dict):
                    items_to_reindex = json_data.get('data', [])
                
                for item in items_to_reindex:
                    reindex_labels(item)
                
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(json_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"  ❌ 保存JSON文件时出错: {e}\n")
    
    # 打印统计信息
    print(f"\n{'='*80}")
    print(f"📊 统计报告")
    print(f"{'='*80}")
    print(f"总label数(log中): {total_labels}")
    print(f"在JSON中找到: {found_in_json} ({found_in_json/total_labels*100:.1f}%)" if total_labels > 0 else "在JSON中找到: 0")
    print(f"在JSON中缺失(需添加): {missing_in_json} ({missing_in_json/total_labels*100:.1f}%)" if total_labels > 0 else "在JSON中缺失: 0")
    print(f"JSON中多余(需删除): {extra_in_json}")
    print(f"需要更新necessary字段: {need_update}")
    
    if dry_run:
        print(f"\n⚠️  这是dry-run模式，未实际修改文件")
        print(f"如需实际更新，请运行: python {__file__} {log_path} --update")
    else:
        print(f"已添加/更新: {updated} 个label")
        print(f"已删除: {deleted} 个多余的label")
    
    print(f"{'='*80}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='检查log文件中的label是否在JSON中有记录，并补充necessary字段'
    )
    parser.add_argument(
        '--log_file',
        default='/public/zhangzhiling/code/GUI_Pravicy/log/privacy2json-266663.log',
        help='log文件路径'
    )
    parser.add_argument(
        '--update',
        action='store_true',
        help='实际更新JSON文件（默认为dry-run模式）'
    )
    
    args = parser.parse_args()
    
    dry_run = not args.update
    check_and_update_labels(log_path=args.log_file, dry_run=dry_run)


if __name__ == '__main__':
    main()


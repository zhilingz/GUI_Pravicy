#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统计日志文件中所有模型的VLM处理时间
"""

import re
from collections import defaultdict

def analyze_vlm_processing_time(log_file):
    """
    分析VLM处理时间
    
    Args:
        log_file: 日志文件路径
    
    Returns:
        dict: 每个模型的总处理时间（秒）
    """
    model_times = defaultdict(float)
    current_model = None
    
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            # 检测模型切换
            model_match = re.search(r'使用模型:\s*(.+)', line)
            if model_match:
                current_model = model_match.group(1).strip()
                continue
            
            # 检测VLM处理时间（排除"平均VLM处理时间"）
            if current_model and 'VLM处理时间:' in line and '平均' not in line:
                time_match = re.search(r'VLM处理时间:\s*([\d.]+)秒', line)
                if time_match:
                    time_seconds = float(time_match.group(1))
                    model_times[current_model] += time_seconds
    
    return model_times

def print_statistics(model_times):
    """
    打印统计结果
    
    Args:
        model_times: 每个模型的总处理时间（秒）
    """
    print("=" * 80)
    print("VLM处理时间统计（按小时）")
    print("=" * 80)
    print()
    
    # 计算总时间
    total_seconds = sum(model_times.values())
    total_hours = total_seconds / 3600
    
    # 按时间降序排序
    sorted_models = sorted(model_times.items(), key=lambda x: x[1], reverse=True)
    
    # 打印每个模型的统计
    for model, seconds in sorted_models:
        hours = seconds / 3600
        percentage = (seconds / total_seconds * 100) if total_seconds > 0 else 0
        print(f"模型: {model}")
        print(f"  总时间: {hours:.4f} 小时 ({seconds:.2f} 秒)")
        print(f"  占比: {percentage:.2f}%")
        print()
    
    # 打印总计
    print("-" * 80)
    print(f"总计: {total_hours:.4f} 小时 ({total_seconds:.2f} 秒)")
    print("=" * 80)

def main():
    log_file = '/public/zhangzhiling/code/GUI_Pravicy/log/privacy2json-266663.log'
    
    print(f"正在分析日志文件: {log_file}")
    print()
    
    model_times = analyze_vlm_processing_time(log_file)
    
    if not model_times:
        print("未找到VLM处理时间数据！")
        return
    
    print_statistics(model_times)

if __name__ == '__main__':
    main()


#!/usr/bin/env python3
"""
从log文件中提取所有"请求失败"的记录，并生成重新运行的sh脚本
"""

import re
import sys
from pathlib import Path
from collections import defaultdict


def parse_log_file(log_path):
    """解析log文件，找出所有请求失败的记录"""
    with open(log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    failed_tasks = []
    current_dir = None
    current_model = None
    
    for i, line in enumerate(lines):
        # 检测处理目录
        if '处理目录:' in line:
            match = re.search(r'处理目录:\s*(.+)', line)
            if match:
                current_dir = match.group(1).strip()
        
        # 检测使用的模型
        if '使用模型:' in line:
            match = re.search(r'使用模型:\s*(.+)', line)
            if match:
                current_model = match.group(1).strip()
        
        # 检测请求失败
        if '请求失败' in line:
            # 向上查找图片路径（格式：第 X/Y 张: path/to/image.png）
            image_path = None
            for j in range(i-1, max(0, i-10), -1):
                if '第 ' in lines[j] and ' 张:' in lines[j]:
                    match = re.search(r'第\s+\d+/\d+\s+张:\s*(.+)', lines[j])
                    if match:
                        image_path = match.group(1).strip()
                        break
            
            failed_tasks.append({
                'line': i + 1,
                'directory': current_dir,
                'model': current_model,
                'image': image_path,
                'error': line.strip()
            })
    
    return failed_tasks


def generate_retry_commands(failed_tasks):
    """根据失败任务生成重新运行的命令，按(目录, 模型)去重"""
    # 按(目录, 模型)分组
    task_groups = defaultdict(list)
    for task in failed_tasks:
        key = (task['directory'], task['model'])
        task_groups[key].append(task)
    
    commands = []
    for (directory, model), tasks in sorted(task_groups.items()):
        if directory and model:
            # 提取目录路径（从图片路径中提取）
            # 图片路径格式：dataset/Android/20251031_124801_YouTube_ Click second video on/images/xxx.png
            # 需要提取：dataset/Android/20251031_124801_YouTube_ Click second video on/
            if tasks[0]['image']:
                # 从图片路径中提取目录
                img_parts = tasks[0]['image'].split('/images/')
                if len(img_parts) > 0:
                    directory = img_parts[0]
            
            cmd = f"python privacy2json.py \"{directory}\" --model {model} -p"
            commands.append({
                'command': cmd,
                'directory': directory,
                'model': model,
                'fail_count': len(tasks)
            })
    
    return commands


def main():
    if len(sys.argv) < 2:
        print("用法: python extract_failed_tasks.py <log_file1> [log_file2] ...")
        print("示例: python extract_failed_tasks.py log/privacy2json-266663.log")
        sys.exit(1)
    
    log_files = sys.argv[1:]
    all_failed_tasks = []
    
    # 统计信息
    total_failures = 0
    
    for log_file in log_files:
        log_path = Path(log_file)
        if not log_path.exists():
            print(f"警告: 日志文件不存在: {log_file}")
            continue
        
        print(f"\n处理日志文件: {log_file}")
        failed_tasks = parse_log_file(log_path)
        total_failures += len(failed_tasks)
        all_failed_tasks.extend(failed_tasks)
        
        print(f"  找到 {len(failed_tasks)} 个请求失败记录")
    
    # 生成重试命令
    commands = generate_retry_commands(all_failed_tasks)
    
    # 输出统计信息
    print(f"\n{'='*60}")
    print(f"统计结果:")
    print(f"{'='*60}")
    print(f"总请求失败次数: {total_failures}")
    print(f"需要重新运行的任务数（去重后）: {len(commands)}")
    
    # 生成sh脚本
    output_script = "retry_failed_tasks.sh"
    with open(output_script, 'w', encoding='utf-8') as f:
        f.write("#!/bin/bash\n")
        f.write("# 自动生成的重试失败任务的脚本\n")
        f.write(f"# 生成时间: $(date)\n")
        f.write(f"# 总失败次数: {total_failures}\n")
        f.write(f"# 去重后任务数: {len(commands)}\n\n")
        
        for idx, cmd_info in enumerate(commands, 1):
            f.write(f"# 任务 {idx}/{len(commands)}\n")
            f.write(f"# 目录: {cmd_info['directory']}\n")
            f.write(f"# 模型: {cmd_info['model']}\n")
            f.write(f"# 失败次数: {cmd_info['fail_count']}\n")
            f.write(f"{cmd_info['command']}\n\n")
    
    print(f"\n已生成重试脚本: {output_script}")
    print(f"\n{'='*60}")
    print("任务详情:")
    print(f"{'='*60}")
    for idx, cmd_info in enumerate(commands, 1):
        print(f"\n任务 {idx}:")
        print(f"  目录: {cmd_info['directory']}")
        print(f"  模型: {cmd_info['model']}")
        print(f"  失败次数: {cmd_info['fail_count']}")
        print(f"  命令: {cmd_info['command']}")
    
    print(f"\n运行重试脚本: bash {output_script}")


if __name__ == "__main__":
    main()


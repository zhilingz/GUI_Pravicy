#!/bin/bash

# 先在log中输出自己的pid
echo "当前脚本的PID: $$"

# 初始化OCR服务（使用 source 获取并保留环境变量）
source ocr/ocr_service.sh

# 定义要处理的文件夹列表
# 自动搜索 data 文件夹下的所有子文件夹
DIRECTORIES=($(find data/mobile -maxdepth 1 -mindepth 1 -type d))
# DIRECTORIES=(
#     "data/mobile/20251031_134545_Google_Play_Books_Search_'AI'"
# )
#     "data/20251031_134545"
#     "data/20251031_140418"
#     "data/20251101_101324"
#     "data/20251102_043355"   
# )  

# 定义要使用的模型列表
MODELS=(
    "google/gemini-3-pro-preview"
    "google/gemini-2.5-pro"
    "anthropic/claude-sonnet-4.5" 
    "openai/chatgpt-4o-latest"
#"anthropic/claude-sonnet-4.5"  "openai/chatgpt-4o-latest" google/gemini-3-pro-preview
)

# 遍历每个文件夹
for dir in "${DIRECTORIES[@]}"; do
    echo "=================================="
    echo "处理目录: $dir"
    echo "=================================="
    
    # 检查目录是否存在
    if [ ! -d "$dir" ]; then
        echo "警告: 目录 $dir 不存在，跳过"
        continue
    fi
    
    # 遍历每个模型
    for model in "${MODELS[@]}"; do
        echo ""
        echo "----------------------------------"
        echo "使用模型: $model"
        echo "----------------------------------"

        echo "开始时间: $(date -d '+8 hour' '+%Y-%m-%d %H:%M:%S')"
        
        # 执行处理
        python level.py "$dir" --model "$model" -p
        
        # 检查执行状态
        if [ $? -eq 0 ]; then
            echo "✓ 完成: $dir - $model"
        else
            echo "✗ 失败: $dir - $model"
        fi
        
        echo ""
    done
done

echo "=================================="
echo "全部任务完成！"
echo "=================================="
echo "结束时间: $(date -d '+8 hour' '+%Y-%m-%d %H:%M:%S')"
# nohup bash level.sh > log/1118_1130.log 2>&1 &
# tail -f log/1118_1130.log
#!/bin/bash

# 定义要处理的文件夹列表
DIRECTORIES=(
    "data/20251031_134545"
    "data/20251031_140418"
    "data/20251101_101324"
    "data/20251102_043355"   
)  

# 定义要使用的模型列表
MODELS=(
    "google/gemini-2.5-pro"
    "openai/gpt-5-pro"
    "openai/o3"
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
        
        # 执行处理
        python label.py "$dir" --model "$model"
        
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

# nohup bash pipeline.sh > pipeline.log 2>&1 &
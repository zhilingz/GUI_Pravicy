#!/bin/bash
#SBATCH -p gpu3             # 在 gpu1 分区运行（不写默认为 cpu1）
#SBATCH -N 1                # 只在一个节点上运行任务
#SBATCH -c 4                # 申请 CPU 核心：4 个
#SBATCH --mem 10G           # 申请内存：10G
#SBATCH --gres gpu:1        # 分配 1 个 GPU（纯 CPU 任务不用写）
#SBATCH -o log/privacy2json-%j.log      # 输出 log 文件，%j会被自动替换为任务的ID（JobID）
#SBATCH -e log/privacy2json-%j.log      # 错误输出 log 文件，%j会被自动替换为任务的ID（JobID）
#SBATCH --nodelist=wmc-slave-g8

# 初始化conda
source ~/miniconda3/etc/profile.d/conda.sh   # 根据你的conda安装路径修改

echo "job begin"
# 打印 SBATCH 提交参数
scontrol show job ${SLURM_JOB_ID}
# 输出当前时间（上海市区时间）
echo "Current time: $(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M:%S')"

conda activate llm

# 显示GPU信息
nvidia-smi --query-gpu=gpu_name --format=csv,noheader

# 先在log中输出自己的pid
echo "当前脚本的PID: $$"

# 定义要处理的文件夹列表
# 自动搜索 data 文件夹下的所有子文件夹（支持带空格的目录名）
DIRECTORIES=()
while IFS= read -r -d '' dir; do
    DIRECTORIES+=("$dir")
done < <(find dataset/Android -maxdepth 1 -mindepth 1 -type d -print0)
# DIRECTORIES=(
#     "test_data/mobile/20251031_140418_Reddit_ Search 'r_TwoHotTakes'"
# )


# 定义要使用的模型列表
MODELS=(
    "google/gemini-3-pro-preview"
    "google/gemini-2.5-pro"
    "openai/gpt-5.1"
    "anthropic/claude-sonnet-4.5" 
    "x-ai/grok-4"
    "z-ai/glm-4.5v"
    # "openai/chatgpt-4o-latest"
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
        python privacy2json.py "$dir" --model "$model" -p
        
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
# nohup bash privacy2json.sh > log/1124_2400.log 2>&1 &
# tail -f log/1124_2400.log
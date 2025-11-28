#!/bin/bash

# 自动执行三个GROUP的privacy2json.sh脚本
# 并根据当前日期自动修改日志路径

# 获取当前日期，格式为 YYYYMMDD
DATE=$(date '+%Y%m%d')
LOG_DIR="log/privacy2json${DATE}"

echo "=================================================="
echo "开始执行所有GROUP的任务"
echo "当前日期: ${DATE}"
echo "日志目录: ${LOG_DIR}"
echo "=================================================="

# 创建日志目录（如果不存在）
mkdir -p "${LOG_DIR}"

# 遍历三个GROUP
for GROUP_NUM in 1 2 3; do
    echo ""
    echo "=================================================="
    echo "准备提交 GROUP ${GROUP_NUM} 的任务"
    echo "=================================================="
    
    # 创建临时脚本文件
    TEMP_SCRIPT="privacy2json_group${GROUP_NUM}_${DATE}.sh"
    
    # 复制原始脚本
    cp privacy2json.sh "${TEMP_SCRIPT}"
    
    # 使用sed修改GROUP参数
    sed -i "s/^GROUP=.*/GROUP=${GROUP_NUM}/" "${TEMP_SCRIPT}"
    
    # 使用sed修改日志路径（两行）
    sed -i "s|log/privacy2json[0-9]*/|${LOG_DIR}/|g" "${TEMP_SCRIPT}"
    
    echo "✓ 已创建临时脚本: ${TEMP_SCRIPT}"
    echo "  - GROUP 设置为: ${GROUP_NUM}"
    echo "  - 日志路径设置为: ${LOG_DIR}"
    
    # 提交任务
    echo "正在提交任务..."
    sbatch "${TEMP_SCRIPT}"
    
    if [ $? -eq 0 ]; then
        echo "✓ GROUP ${GROUP_NUM} 任务提交成功"
    else
        echo "✗ GROUP ${GROUP_NUM} 任务提交失败"
    fi
    
    # 稍微等待一下，避免提交过快
    sleep 2
done

echo ""
echo "=================================================="
echo "所有任务已提交完成！"
echo "=================================================="
echo "查看任务状态: squeue -u \$USER"
echo "查看日志目录: ls -lh ${LOG_DIR}"
echo ""
echo "临时脚本文件已创建，如需要可以手动删除："
echo "  rm privacy2json_group*_${DATE}.sh"
echo "=================================================="


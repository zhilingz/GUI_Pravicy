#!/bin/bash

# OCR服务初始化脚本
# 检查并启动Google OCR服务，设置环境变量

# OCR服务配置
OCR_SERVICE_PORT=${OCR_SERVICE_PORT:-8765}
OCR_SERVICE_URL="http://localhost:${OCR_SERVICE_PORT}"
OCR_SERVICE_LOG=${OCR_SERVICE_LOG:-log/ocr_service.log}

# 检查OCR服务是否已经开启
echo "检查OCR服务状态..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${OCR_SERVICE_URL}/health" || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ OCR服务已经在运行"
    USE_OCR_SERVICE="true"
else
    echo "OCR服务未运行，正在启动..."
    
    # 确保日志目录存在
    mkdir -p "$(dirname "$OCR_SERVICE_LOG")"
    
    # 启动OCR服务（后台运行）
    # 确保代理环境变量被传递（如果设置了的话）
    # Google Vision API需要通过代理连接
    # 使用 PYTHONUNBUFFERED 确保 Python 输出实时写入日志文件
    PYTHONUNBUFFERED=1 python "ocr/ocr_service.py" --port "${OCR_SERVICE_PORT}" > "${OCR_SERVICE_LOG}" 2>&1 &
    OCR_SERVICE_PID=$!
    
    # 等待服务启动（每5秒轮询一次，最多120秒）
    echo "等待OCR服务启动（最多120秒）..."
    MAX_WAIT=120
    INTERVAL=5
    WAITED=0
    HTTP_CODE="000"

    while [ "$WAITED" -lt "$MAX_WAIT" ]; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${OCR_SERVICE_URL}/health" || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            break
        fi
        sleep "$INTERVAL"
        WAITED=$((WAITED + INTERVAL))
    done
    
    # 根据最终健康检查结果，决定是否启用OCR服务模式
    if [ "$HTTP_CODE" = "200" ]; then
        echo "✓ OCR服务启动成功 (PID: $OCR_SERVICE_PID)"
        USE_OCR_SERVICE="true"
    else
        echo "✗ 在 ${MAX_WAIT} 秒内未检测到OCR服务健康，使用本地模式"
        USE_OCR_SERVICE="false"
    fi
fi

# 设置环境变量，让Python脚本使用OCR服务
export USE_OCR_SERVICE="${USE_OCR_SERVICE}"
export OCR_SERVICE_URL="${OCR_SERVICE_URL}"


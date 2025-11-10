# GUI Privacy 隐私信息分析工具

一个基于 AI 的 GUI 界面隐私信息检测与标注工具，用于自动识别和标注应用截图中的用户隐私数据。

## 📋 项目简介

本项目通过结合大语言模型（LLM）和光学字符识别（OCR）技术，自动分析移动应用截图中包含的隐私信息。系统能够识别6大类隐私数据，并在图像上进行可视化标注，同时生成详细的 JSON 格式分析报告。

## ✨ 主要功能

- 🤖 **多模型支持**：支持 GPT-5-Pro、O3、Gemini-2.5-Pro 等多种 AI 模型
- 🔍 **智能识别**：基于上下文的隐私信息智能识别
- 📊 **六大类别**：覆盖核心身份、联系财务、设备标识、行为追踪、敏感信息、画像推断
- 🎨 **可视化标注**：自动在截图上标注隐私信息位置
- 📈 **批量处理**：支持批量处理多个数据集和截图
- 💾 **结构化输出**：生成 JSON 格式的详细分析结果

## 🏗️ 项目结构

```
GUI_Pravicy/
├── label.py              # 主要处理脚本
├── pipeline.sh           # 批量处理流水线
├── api.txt              # API 密钥配置文件
├── log/                 # 日志文件目录
└── README.md
```

## 🔐 隐私信息分类

### 1. 核心身份标识符 (Core Identity Identifiers)
能够单独唯一识别个人的信息
- 真实姓名、身份证号、护照号、学号、工号
- 唯一映射到个人的账户/ID

### 2. 联系与财务信息 (Contact & Financial)
可直接联系个人或关联资金的信息
- 邮箱、电话、家庭住址
- 银行卡、支付账户

### 3. 技术与设备标识符 (Technical & Device Identifiers)
支持跨会话/设备追踪的技术信息
- 位置信息（城市、国家、街道等）
- 时间戳、设备ID、IMEI、MAC地址
- 广告ID、Cookie ID、浏览器指纹、IP地址

### 4. 行为与上下文轨迹 (Behavior & Context Traces)
记录用户行为的数据
- 用户搜索历史

### 5. 特殊敏感类别 (Special Categories - Sensitive)
高度敏感的个人信息（最高优先级）
- 健康/医疗数据
- 宗教信仰、政治观点、工会成员资格
- 性取向/性生活
- 生物特征/基因数据

### 6. 推断与画像 (Inferences & Profiling)
从原始数据推导的标签/评分/偏好
- 兴趣/偏好
- 信用/风险评分
- 受众细分、相似度评分

## 🚀 快速开始

### 环境要求

- Python 3.7+
- OpenAI API 密钥
- 相关依赖包（见下方安装说明）

### 安装依赖

```bash
pip install openai pillow easyocr
```

### 配置 API 密钥

设置环境变量：
```bash
export OPENAI_API_KEY="your_api_key_here"
```

或在 `api.txt` 文件中配置。

### 基本使用

#### 单个数据集处理

```bash
python label.py /path/to/your/dataset
```

#### 指定模型

```bash
python label.py /path/to/your/dataset --model "google/gemini-2.5-pro"
```

#### 自定义处理范围

```bash
# 处理第 3-10 张图片
python label.py /path/to/your/dataset --start 3 --end 10
```

#### 禁用 OCR（仅获取 AI 分析结果）

```bash
python label.py /path/to/your/dataset --no-ocr
```

#### 批量处理

使用流水线脚本批量处理多个数据集和模型：

```bash
bash pipeline.sh
```

后台运行：
```bash
nohup bash pipeline.sh > pipeline.log 2>&1 &
```

## 📝 命令行参数

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `directory` | - | 要处理的数据目录（必需） | - |
| `--model` | `-m` | 指定使用的 AI 模型 | `openai/gpt-5-pro` |
| `--start` | `-s` | 从第 N 张图片开始处理 | 1 |
| `--end` | `-e` | 到第 N 张图片结束 | None |
| `--no-ocr` | `-n` | 禁用 OCR，只显示 AI 结果 | False |
| `--print-ocr` | `-p` | 打印 OCR 识别结果 | False |

### 支持的模型

- `openai/gpt-5-pro`
- `openai/o3`
- `google/gemini-2.5-pro`
- `openai/o4-mini-high`

## 📤 输出格式

### 标注图像

系统会在原始截图上用彩色边框标注隐私信息：

- 🔴 红色 (1) - 核心身份标识符
- 🟠 橙色 (2) - 联系与财务信息
- 🟡 黄色 (3) - 技术与设备标识符
- 🟢 绿色 (4) - 行为与上下文轨迹
- 🟣 紫色 (5) - 特殊敏感类别
- 🔵 蓝色 (6) - 推断与画像

### JSON 结果

生成的 `privacy_results.json` 包含：

```json
{
  "summary": {
    "total_images": 17,
    "processed_images": 17,
    "date": "2025-11-10T12:34:56.789",
    "average_processing_time": 5.23,
    "model": "openai/gpt-5-pro"
  },
  "images": [
    {
      "step": 1,
      "image_file": "screenshot_xxx.png",
      "ai_response": "...",
      "privacy_items": [
        {
          "text": "john.smith@gmail.com",
          "description": "Email address",
          "category": 2,
          "found_in_image": true,
          "coordinates": {
            "x1": 100,
            "y1": 200,
            "x2": 300,
            "y2": 230
          },
          "color": "#FF8000"
        }
      ],
      "processing_time": 5.67
    }
  ]
}
```

## 🔬 工作原理

1. **读取数据**：加载指定目录中的截图和 manager.json 文件
2. **AI 分析**：将截图和上下文发送给 AI 模型进行隐私信息识别
3. **OCR 定位**：使用 EasyOCR 在图像中定位识别出的隐私文本
4. **可视化标注**：在原图上绘制彩色边框和类别标签
5. **结果保存**：生成标注图像和结构化 JSON 数据

## 📊 使用场景

- 📱 **移动应用隐私审计**：检查应用是否泄露用户隐私
- 🔍 **合规性检查**：验证应用是否符合 GDPR、CCPA 等隐私法规
- 🧪 **安全测试**：自动化隐私泄漏检测
- 📚 **研究分析**：批量分析应用的隐私数据收集行为

## ⚠️ 注意事项

1. 系统会排除以下内容：
   - AI 代理生成的内容（提示、搜索建议等）
   - 用户搜索查询和工具输出
   - 说明性/公开性/无实质性或与用户/操作者无关的信息

2. 当文本匹配多个类别时，优先级为：**5 > 1 > 2 > 3 > 4 > 6**

3. 确保有足够的 API 配额，处理大量图片可能消耗较多 tokens

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

本项目采用 MIT 许可证。

## 📧 联系方式

如有问题或建议，请通过 Issue 联系。

---

**最后更新**: 2025-11-10


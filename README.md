# GUI Privacy - Privacy Information Analysis Tool

[**Chinese Documentation (中文文档)**](./README_CN.md)

An AI-powered GUI privacy information detection and annotation tool for automatically identifying and labeling user privacy data in application screenshots.

## 📋 Overview

This project combines Large Language Models (LLM) and Optical Character Recognition (OCR) technology to automatically analyze privacy information in mobile application screenshots. The system can identify 6 major categories of privacy data, perform visual annotation on images, and generate detailed analysis reports in JSON format.

## ✨ Key Features

- 🤖 **Multi-Model Support**: Supports multiple AI models including GPT-5-Pro, O3, Gemini-2.5-Pro
- 🔍 **Intelligent Recognition**: Context-based intelligent privacy information identification
- 📊 **Six Categories**: Covers core identity, contact and financial, device identifiers, behavior traces, sensitive information, and profiling
- 🎨 **Visual Annotation**: Automatically annotates privacy information locations on screenshots
- 📈 **Batch Processing**: Supports batch processing of multiple datasets and screenshots
- 💾 **Structured Output**: Generates detailed analysis results in JSON format

## 🏗️ Project Structure

```
GUI_Pravicy/
├── label.py              # Main processing script
├── pipeline.sh           # Batch processing pipeline
├── api.txt              # API key configuration file
├── log/                 # Log file directory
└── README.md
```

## 🔐 Privacy Information Categories

### 1. Core Identity Identifiers
Information that can uniquely identify an individual on its own
- Real name, national ID, passport number, student ID, employee number
- Account/ID that uniquely maps to a person

### 2. Contact & Financial
Information that can directly contact a person or link to funds
- Email, phone number, home address
- Bank card, payment account

### 3. Technical & Device Identifiers
Technical information that enables cross-session/device tracking
- Location information (city, country, street, etc.)
- Timestamp, device ID, IMEI, MAC address
- Ad ID, Cookie ID, browser fingerprint, IP address

### 4. Behavior & Context Traces
Data recording user behavior
- User search history

### 5. Special Categories (Sensitive)
Highly sensitive personal information (highest priority)
- Health/medical data
- Religious beliefs, political views, union membership
- Sexual orientation/sex life
- Biometric/genetic data

### 6. Inferences & Profiling
Labels/scores/preferences derived from raw data
- Interests/preferences
- Credit/risk scores
- Audience segments, similarity scores

## 🚀 Quick Start

### Requirements

- Python 3.7+
- OpenAI API Key
- Required dependencies (see installation instructions below)

### Install Dependencies

```bash
pip install openai pillow easyocr
```

### Configure API Key

Set environment variable:
```bash
export OPENAI_API_KEY="your_api_key_here"
```

Or configure in `api.txt` file.

### Basic Usage

#### Process a Single Dataset

```bash
python label.py /path/to/your/dataset
```

#### Specify Model

```bash
python label.py /path/to/your/dataset --model "google/gemini-2.5-pro"
```

#### Custom Processing Range

```bash
# Process images 3-10
python label.py /path/to/your/dataset --start 3 --end 10
```

#### Disable OCR (Get AI Analysis Only)

```bash
python label.py /path/to/your/dataset --no-ocr
```

#### Batch Processing

Use the pipeline script to batch process multiple datasets and models:

```bash
bash pipeline.sh
```

Run in background:
```bash
nohup bash pipeline.sh > pipeline.log 2>&1 &
```

## 📝 Command Line Arguments

| Parameter | Short | Description | Default |
|-----------|-------|-------------|---------|
| `directory` | - | Data directory to process (required) | - |
| `--model` | `-m` | Specify AI model to use | `openai/gpt-5-pro` |
| `--start` | `-s` | Start from the Nth image | 1 |
| `--end` | `-e` | End at the Nth image | None |
| `--no-ocr` | `-n` | Disable OCR, show AI results only | False |
| `--print-ocr` | `-p` | Print OCR recognition results | False |

### Supported Models

- `openai/gpt-5-pro`
- `openai/o3`
- `google/gemini-2.5-pro`
- `openai/o4-mini-high`

## 📤 Output Format

### Annotated Images

The system annotates privacy information on original screenshots with colored borders:

- 🔴 Red (1) - Core Identity Identifiers
- 🟠 Orange (2) - Contact & Financial
- 🟡 Yellow (3) - Technical & Device Identifiers
- 🟢 Green (4) - Behavior & Context Traces
- 🟣 Purple (5) - Special Categories (Sensitive)
- 🔵 Blue (6) - Inferences & Profiling

### JSON Results

Generated `privacy_results.json` contains:

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

## 🔬 How It Works

1. **Load Data**: Load screenshots and manager.json files from specified directory
2. **AI Analysis**: Send screenshots and context to AI model for privacy information identification
3. **OCR Localization**: Use EasyOCR to locate identified privacy text in images
4. **Visual Annotation**: Draw colored borders and category labels on original images
5. **Save Results**: Generate annotated images and structured JSON data

## 📊 Use Cases

- 📱 **Mobile App Privacy Audit**: Check if apps leak user privacy
- 🔍 **Compliance Check**: Verify compliance with GDPR, CCPA, and other privacy regulations
- 🧪 **Security Testing**: Automated privacy leakage detection
- 📚 **Research Analysis**: Batch analyze app privacy data collection behavior

## ⚠️ Important Notes

1. The system excludes the following content:
   - Agent-generated content (prompts, search suggestions, etc.)
   - User search queries and tool outputs
   - Instructional/public/insubstantial information or information unrelated to the user/operator

2. When text matches multiple categories, priority order is: **5 > 1 > 2 > 3 > 4 > 6**

3. Ensure sufficient API quota, as processing large numbers of images may consume significant tokens

## 🤝 Contributing

Issues and Pull Requests are welcome!

## 📄 License

This project is licensed under the MIT License.

## 📧 Contact

For questions or suggestions, please contact us via Issues.

---

**Last Updated**: 2025-11-10

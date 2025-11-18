import os
import json
import glob
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
import re
from textwrap import dedent
from datetime import datetime
import time

client = OpenAI(
    base_url="https://api.dou.chat/v1",  
    api_key=os.getenv('OPENAI_API_KEY', ""),
)

# 从googleocr_label导入所有重复的函数
from googleocr_label import (
    process_privacy_matches,
    save_annotated_image,
    prepare_image_and_ocr,
    process_images,
    create_argument_parser,
    validate_and_print_args,
    load_task_goal
)

def parse_and_annotate(ai_output, image_path, output_dir, print_ocr=False, no_save_image=False):
    """解析AI输出并标注隐私信息"""
    
    # 准备图片和OCR结果
    image, draw, ocr_results = prepare_image_and_ocr(image_path, print_ocr)
    
    # 解析AI输出
    # 格式: text | description | level (level可以是: high, medium, low, none)
    pattern = r'([^|]+)\|\s*([^|]+)\|\s*([a-zA-Z]+)'
    matches = re.findall(pattern, ai_output)
    
    # level到颜色和标签的映射
    level_colors = {
        "high": "#FF0000",      # 红色
        "medium": "#FF8000",    # 橙色
        "low": "#FFFF00",       # 黄色
        "none": "#00FF00"       # 绿色
    }
    
    # 定义获取颜色和标签的函数
    def get_color_label(privacy_text, description, level):
        level_lower = level.strip().lower()
        color = level_colors.get(level_lower, "#00FF00")  # 默认绿色
        label = level_lower.upper()[:1]  # 显示level的第一个字符（H, M, L, N）
        privacy_item = {
            "text": privacy_text,
            "description": description,
            "level": level_lower
        }
        return color, label, privacy_item
    
    # 处理匹配并绘制标注
    privacy_items = process_privacy_matches(
        matches, ocr_results, image, draw, get_color_label,
        font_size=20, label_size=30, label_height=20, text_offset_x=7
    )
    
    # 保存标注后的图片
    save_annotated_image(image, image_path, output_dir, no_save_image)
    
    return privacy_items

def process(directory_path, enable_ocr=True, start=1, end=None, model_name="openai/gpt-5-pro", print_ocr=False, no_save_image=False, no_save_json=False, output_name="level"):
    """批量处理图片和manager.json文件（level版本）"""
    
    prompt_template = dedent("""\
        ### Agent's goal and response
        goal: {goal}
        response: {response}

        ### Role
        You are a privacy classifier.

        ### Task
        Given an app screenshot taken while the Agent is working toward its goal, and the Agent's goal and response above.
        First, extract ALL visible text from the screenshot.
        Then, for each meaningful text segment, identify what kind of information it is and classify its privacy risk level.

        ### Risk levels
        Use exactly these four labels: high, medium, low, none.

        - high: Information that can directly identify or contact the user/operator.
        Includes: real name, exact address or location, email address, phone number, ID/passport number, IP address, device ID, account ID, user ID, bank card number, password, authentication tokens.

        - medium: Information that can reasonably infer the user/operator's behavior, preferences, or identity, but does not directly identify them.
        Includes: Installed applications, browsing history, search history, call history, chat content, follow/subscribe lists, calendar/schedule, to-do list, shopping cart items, order history, nearby places in location, distance from "home" or "current location", company name, school name, job title, internal project names.

        - low: Technical or contextual information that only becomes privacy-relevant after analysis or correlation with other data.
        Includes: time, device parameters, recommended content, generic search queries without clear target, non-specific system messages, references to previously detected private info.

        - none: Public or generic content that anyone can find on the internet and that does not target the user/operator.
        Includes: other people's posts, news headlines, public ads, general app UI text, fixed icons, slogans, public creator profiles and posts, comments/bullets that are clearly public, generic help texts.

        ### Output format
        For each extracted text segment, output ONE line in this format:

        <original text> | <information type> | <risk level>

        - <information type>: a short description in English, e.g. "Email address", "Phone number", "Search query", "Company name", "App UI text".
        - <risk level>: one of "high", "medium", "low", "none".

        ### Rules
        - Please identify all the text.
        - If the same text appears multiple times in the screenshot, please identify all of them and do not ignore them.
    """)
    
    process_images(directory_path, parse_and_annotate, prompt_template, enable_ocr, 
                   start, end, model_name, print_ocr, no_save_image, no_save_json, print_ai_output=True, output_name=output_name)

# 主程序
if __name__ == "__main__":
    parser = create_argument_parser()
    args = parser.parse_args()
    validate_and_print_args(args)
    process(args.directory, not args.no_ocr, args.start, args.end, args.model, args.print_ocr, args.no_save_image, args.no_save_json, "level")


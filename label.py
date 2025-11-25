import re
from textwrap import dedent

# 从util导入所有通用函数
from util import (
    process_privacy_matches,
    save_annotated_image,
    prepare_image_and_ocr,
    process_images,
    create_argument_parser,
    validate_and_print_args
)

def parse_and_annotate(ai_output, image_path, output_dir, print_ocr=False, no_save_image=False):
    """解析AI输出并标注隐私信息"""
    
    # 准备图片和OCR结果
    image, draw, ocr_results = prepare_image_and_ocr(image_path, print_ocr)
    
    # 解析AI输出
    pattern = r'([^|]+)\|\s*([^|]+)\|\s*(\d+)\s*\([^)]+\)'
    matches = re.findall(pattern, ai_output)
    
    # 定义获取颜色和标签的函数
    colors = ["#FF0000", "#FF8000", "#FFFF00", "#00FF00", "#FF00FF", "#0080FF"]
    def get_color_label(privacy_text, description, category):
        category_int = int(category)
        color = colors[min(category_int-1, 5)]
        label = str(category_int)
        privacy_item = {
            "text": privacy_text,
            "description": description,
            "category": category_int
        }
        return color, label, privacy_item
    
    # 处理匹配并绘制标注
    privacy_items = process_privacy_matches(
        matches, ocr_results, image, draw, get_color_label,
        font_size=28, label_size=40, label_height=30, text_offset_x=13
    )
    
    # 保存标注后的图片
    save_annotated_image(image, image_path, output_dir, no_save_image)
    
    return privacy_items

def process(directory_path, enable_ocr=True, start=1, end=None, model_name="openai/gpt-5-pro", print_ocr=False, no_save_image=False, no_save_json=False, output_name="googleocr_results"):
    """批量处理图片和manager.json文件（category版本）"""
    
    prompt_template = dedent("""\
        ### Agent's goal and response
        goal: {goal}
        response: {response}

        ### Role
        You are a privacy classifier.

        ### Task
        Given an app screenshot taken while the Agent is working toward its goal, and the Agent's goal and response above.
        Decide whether the screenshot contains **privacy information related to the user/operator**. If yes, extract each item's **exact visible text** and label its category.

        ### Scope / Exclusions
        - Ignore agent-generated content (prompts, search suggestions, etc.).
        - Ignore User search queries and tool outputs.
        - Info that is instructional/public/insubstantial or unrelated to the user/operator is not privacy data.

        ### Categories
        1. **Core Identity Identifiers** — uniquely identify a person on their own. 
        - Examples: real name, national ID/passport/student/employee numbers, account/ID that uniquely maps to a person.
        
        2. **Contact & Financial** — directly contacts a person or links to funds. 
        - Examples: email, phone, home address, bank card, payment account.
        
        3. **Technical & Device Identifiers** — enable cross-session/device tracking. 
        - Examples: location related to the user, location on the map, timestamps, device ID, IMEI, MAC, ad ID, cookie ID, browser fingerprint, IP (context-dependent).
        
        4. **Behavior & Context Traces** — records stitching actions. 
        - Examples: searches history of the user.
        
        5. **Sensitive Special Categories** — highest priority. 
        - Examples: health/medical, religion, political views, union membership, sexual orientation/sex life, biometric/genetic data used for identification.
        
        6. **Inferences & Profiling** — labels/scores/preferences derived from raw data. 
        - Examples: interests/preferences, credit/risk scores, audience segments, similarity scores.

        ### Output
        - One item per line, format:
        `[exact_text_from_image] | [description] | [category_number]([Category Name])`
        - If none: output `No privacy information found`

        ### Examples
        john.smith@gmail.com | Email address | 2(Contact & Financial)
        Password123! | User password | 2(Contact & Financial)

        ### Notes
        - Use the **exact text** from the screenshot (verbatim). Do not include coordinates or boxes.
        - If a text matches multiple categories, apply priority: **5 > 1 > 2 > 3 > 4 > 6**.
    """)
    
    process_images(directory_path, parse_and_annotate, prompt_template, enable_ocr, 
                   start, end, model_name, print_ocr, no_save_image, no_save_json, print_ai_output=False, output_name=output_name)

# 主程序
if __name__ == "__main__":
    parser = create_argument_parser()
    args = parser.parse_args()
    validate_and_print_args(args)
    process(args.directory, not args.no_ocr, args.start, args.end, args.model, args.print_ocr, args.no_save_image, args.no_save_json, args.output_name)


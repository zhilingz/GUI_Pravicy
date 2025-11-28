import os
import re
import json
import glob
import hashlib
from textwrap import dedent
from PIL import Image, ImageDraw, ImageFont

# 从util导入所有通用函数
from util import (
    save_annotated_image,
    create_argument_parser,
    validate_and_print_args,
    process_images_generic,
    get_pc_test_data_images,
    load_pc_test_data_goal,
    load_pc_test_data_responses
)

RISK_LABEL_MAP = {
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
    "none": "无风险"
}

DRAW_TYPE = "OCR_RECT"


class PrivacyJSONFormatter:
    """负责将解析结果组织成图片隐私标注 JSON 的辅助类"""

    def __init__(self, base_directory):
        self.base_directory = os.path.abspath(base_directory)
        self.batch_id = hashlib.md5(self.base_directory.encode("utf-8")).hexdigest()[:24]
        self.directory_slug = os.path.basename(self.base_directory.rstrip(os.sep))
        self.results = []
        self.frame_counter = 0

    def _build_label(self, image_record_id, seq_id, payload):
        attr = {"ocrResult": payload["text"]}
        category_code = payload.get("category_code")
        risk = payload.get("risk", "none")
        necessity = payload.get("necessity", "not_necessary")
        if category_code:
            attr["分类"] = category_code
            attr["attr"] = {"分类": category_code}

        points = [round(value, 6) for value in payload["points"]]
        # 将necessity字符串转换为布尔值
        is_necessary = (necessity == "necessary")
        
        return {
            "_id": f"{image_record_id}_{seq_id:04d}",
            "id": seq_id,
            "label": RISK_LABEL_MAP.get(risk, risk),
            "drawType": DRAW_TYPE,
            "group": 0,
            "points": points,
            "zIndex": seq_id,
            "attr": attr,
            "necessary": is_necessary
        }

    def add_image_result(self, image_path, width, height, label_payloads):
        image_file = os.path.basename(image_path)
        rel_path = f"{self.directory_slug}/{image_file}"
        lens_frame = self.frame_counter
        image_record_id = f"{self.batch_id}_{lens_frame:04d}"
        labels = [
            self._build_label(image_record_id, idx, payload)
            for idx, payload in enumerate(label_payloads, 1)
        ]

        self.results.append({
            "batchId": self.batch_id,
            "_id": image_record_id,
            "lensFrame": lens_frame,
            "index": lens_frame,
            "info": rel_path,
            "size": {
                "width": width,
                "height": height
            },
            "labels": labels
        })
        self.frame_counter += 1

    def save(self, directory_path, output_name, model_name, skip_save=False):
        if skip_save:
            print("跳过保存图片隐私标注JSON（--no-save-json）")
            return

        target_dir = os.path.join(
            directory_path,
            output_name,
            model_name.replace('/', '_')
        )
        os.makedirs(target_dir, exist_ok=True)

        output_path = os.path.join(target_dir, "ai_results.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        print(f"保存图片隐私标注: {output_path}")


def parse_and_annotate(ai_output, image_path, output_dir, formatter, no_save_image=False):
    """解析LLM输出、绘制标注并收集JSON结果"""
    privacy_items = []
    label_payloads = []

    try:
        image = Image.open(image_path)
        img_width, img_height = image.size
    except Exception as e:
        print(f"无法打开图片: {e}")
        return privacy_items

    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 16)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        except Exception:
            font = ImageFont.load_default()

    colors = {
        "high": "red",
        "medium": "orange",
        "low": "yellow",
        "none": "green"
    }

    if not ai_output or not ai_output.strip():
        print("AI输出为空，跳过解析")
        lines = []
    else:
        lines = ai_output.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = line.rsplit('|', 4)
        if len(parts) != 5:
            print(f"字段数量不对({len(parts)}): {line[:100]}")
            continue

        text = parts[0].strip()
        risk = parts[1].strip().lower()
        category = parts[2].strip()
        coords_str = parts[3].strip()
        necessity = parts[4].strip().lower()
        
        if risk == "none":
            necessity = "not_necessary"

        try:
            coords = json.loads(coords_str)
            x1, y1, x2, y2 = coords['x1'], coords['y1'], coords['x2'], coords['y2']
            # 1500 800 -> 3416x1842
            scale_x = img_width/1505
            scale_y = img_height/812
            x1_px = x1 * scale_x
            y1_px = y1 * scale_y
            x2_px = x2 * scale_x
            y2_px = y2 * scale_y

            print(f"绘制归一化后坐标: [({x1_px:.1f}, {y1_px:.1f}), ({x2_px:.1f}, {y2_px:.1f})]")
            
            color = colors.get(risk, "green")
            
            # 对于 necessary 的框绘制双层边框
            if necessity == "necessary":
                draw.rectangle([x1_px, y1_px, x2_px, y2_px], outline=color, width=5)
                offset = 5
                draw.rectangle([x1_px + offset, y1_px + offset, x2_px - offset, y2_px - offset], 
                             outline=color, width=3)
            else:
                draw.rectangle([x1_px, y1_px, x2_px, y2_px], outline=color, width=3)

            # 提取分类数字
            category_match = re.search(r'(\d+)', category)
            category_code = category_match.group(1) if category_match else ""
            
            # 只显示风险等级首字母和分类数字
            risk_letter = risk.upper()[0]
            if category_code:
                label_text = f"{risk_letter}: {category_code}"
            else:
                label_text = f"{risk_letter}"
            bbox = font.getbbox(label_text)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            draw.rectangle([x1_px, y1_px - text_height - 4, x1_px + text_width + 4, y1_px], fill=color)

            text_color = "black" if risk in ["low", "none"] else "white"
            draw.text((x1_px + 2, y1_px - text_height - 4), label_text, fill=text_color, font=font)

            privacy_items.append({
                "text": text,
                "level": risk,
                "category": category,
                "coordinates": coords,
                "necessity": necessity,
                "found_in_image": True,
                "color": color
            })

            label_payloads.append({
                "text": text,
                "risk": risk,
                "category_code": category_code if risk != "none" and category_code else "",
                "necessity": necessity,
                "points": [x1_px, y1_px, x2_px, y2_px]
            })

        except json.JSONDecodeError:
            print(f"坐标解析失败: {coords_str}")
        except Exception as e:
            print(f"处理行出错: {line} -> {e}")

    save_annotated_image(image, image_path, output_dir, no_save_image)
    formatter.add_image_result(image_path, img_width, img_height, label_payloads)

    return privacy_items


def build_parser(formatter):
    """
    返回带状态的解析函数，负责解析LLM输出、绘制标注并收集JSON结果
    为了兼容 process_images_generic，签名需要为 (ai_output, image_path, output_dir, print_ocr, no_save_image)
    """
    def parse_func(ai_output, image_path, output_dir, print_ocr=False, no_save_image=False):
        return parse_and_annotate(ai_output, image_path, output_dir, formatter, no_save_image)
    return parse_func


def process_test_data(directory_path, model_name="openai/gpt-5-pro", start=1, end=None, 
                      no_save_image=False, no_save_json=False, output_name="privacy2json_hw_pc"):
    """
    处理测试数据目录（使用归一化坐标）
    1. 加载goal: 从 `instruction.txt` 文件读取任务目标
    2. 加载response 从 `traj.jsonl` 文件读取每个步骤的plan
    3. 处理图片 
       - 处理所有 `step_*.png` 图片（跳过最后一张）
       - `step_0.png` 对应第一个plan
       - 倒数第二张图对应最后一个plan
       - 最后一张图不做分析
    
    Args:
        start: 从第N张图片开始处理（默认：1）
        end: 到第N张图片结束（默认：None，处理所有）
    """
    
    # 准备prompt模板（告诉大模型图片尺寸）
    prompt_template = dedent("""\
        ### Image dimensions
        Image dimensions: {img_width}x{img_height}

        ### Agent's goal and response
        goal: {goal}
        response: {response}

        ### Role
        You are a privacy classifier.

        ### Task
        Given an app screenshot taken while the Agent is working toward its goal, and the Agent's goal and response above:
        1. First, scan the entire screenshot and identify ALL visible items (including text and non-text elements).
        2. Then, for each meaningful item or region, classify its privacy risk level.
        3. For items with privacy risk (high, medium, or low), assign one of the six categories below. 
        4. For each item, output its original content/description, risk level, privacy category (if applicable), and its precise coordinates in the screenshot.
        5. For each item, decide whether this information is **strictly necessary** for the Agent to achieve its goal. 
        "Strictly necessary" means that if this item were fully masked or removed, the Agent would not be able to correctly complete the task.

        ### Risk levels

        Use exactly these four labels: high, medium, low, none.

        - high: Information that can directly identify or contact a person.
        Includes: name/id, exact address or location, email address, phone number, ID/passport number, IP address, device ID, account ID, user ID, bank card number, password, authentication tokens.

        - medium: Information that can reasonably infer a person's behavior, preferences, or identity, but does not directly identify them.
        Includes: browsing history, search history, call history, chat content, follow/subscribe lists, calendar/schedule, to-do list, shopping cart items, order history, nearby places in location, distance from "home" or "current location", company name, school name, job title, internal project names.

        - low: Technical or contextual information that only becomes privacy-relevant after analysis or correlation with other data.
        Includes: time, device parameters, recommended content, installed applications, generic search queries without clear target, non-specific system messages, references to previously detected private info.

        - none: Public or generic content that anyone can find on the internet and that does not target a person.
        Includes: other people's names/ids, public posts, news headlines, public ads, general app UI text, fixed icons, slogans, public creator profiles and posts, comments/bullets that are clearly public, generic help texts.
        
        ### Privacy category

        1. **Core Identity Identifiers** — uniquely identify a person on their own. 
        - Examples: real name, national ID/passport/student/employee numbers, account/ID that uniquely maps to a person.

        2. **Contact & Financial** — directly contacts a person or links to funds. 
        - Examples: email, phone, home address, bank card, payment account.

        3. **Technical & Device Identifiers** — enable cross-session/device tracking. 
        - Examples: installed applications, location, timestamps, verification code, device ID, IMEI, MAC, ad ID, cookie ID, browser fingerprint, IP.

        4. **Behavior & Context Traces** — records stitching actions. 
        - Examples: searches history.

        5. **Sensitive Special Categories** — highest priority. 
        - Examples: health/medical, religion, political views, union membership, sexual orientation/sex life, biometric/genetic data used for identification.

        6. **Inferences & Profiling** — labels/scores/preferences derived from raw data. 
        - Examples: interests/preferences, credit/risk scores, audience segments, similarity scores.
        
        - If an item matches multiple categories, apply priority: **5 > 1 > 2 > 3 > 4 > 6**.

        ### Output format

        For each item, output one line in the following format (do NOT output the format template itself, only the actual data):

        [exact text or description] | [risk level] | [category number(Category Name)] | [coordinates JSON] | [necessity]

        Where:
        - First field: for textual items, the exact visible text from the screenshot (verbatim); for non-text items, a concise description of the visible content (e.g. "face of a person", "bank card image").
        - Second field: one of "high", "medium", "low", "none".
        - Third field: category number and name (1-6 above) for items with privacy risk (high/medium/low); use "-" for items with risk level "none".
        - Fourth field: precise pixel coordinates based on the actual image dimensions ({img_width}x{img_height}), as a JSON object like {{"x1":80, "y1":250, "x2":740, "y2":350}} where x1,y1 is the top-left corner and x2,y2 is the bottom-right corner. Use pixel coordinates where (0,0) is top-left and ({img_width},{img_height}) is bottom-right.
        - Fifth field: "necessary" if the item is strictly required for the Agent to correctly complete its goal; otherwise "not_necessary".

        ### Examples

        john.smith@gmail.com | high | 2(Contact & Financial) | {{"x1":80, "y1":250, "x2":740, "y2":350}} | necessary
        Search in mail | none | - | {{"x1":200, "y1":400, "x2":250, "y2":500}} | not_necessary

        ### Notes
        - For textual items, use the **exact text** from the screenshot (verbatim).
        - For non-text items, use a concise, clear description of the visible content.
        - Please identify all items in the screenshot.
        - If the same item appears multiple times in the screenshot, please identify all of them and do not ignore them.
    """)
    
    # 初始化formatter
    formatter = PrivacyJSONFormatter(directory_path)
    parser_func = build_parser(formatter)
    
    # 使用通用函数处理
    process_images_generic(
        directory_path,
        parser_func,
        prompt_template,
        get_pc_test_data_images,
        load_pc_test_data_goal,
        load_pc_test_data_responses,
        enable_ocr=True,
        start=start,
        end=end,
        model_name=model_name,
        no_save_image=no_save_image,
        no_save_json=no_save_json,
        print_ai_output=True,
        output_name=output_name,
        formatter=formatter
    )


if __name__ == "__main__":
    parser = create_argument_parser(description='测试数据隐私分析工具 (PC test_data格式，使用归一化坐标)')
    
    args = parser.parse_args()
    validate_and_print_args(args)
    
    process_test_data(
        args.directory,
        model_name=args.model,
        start=args.start,
        end=args.end,
        no_save_image=args.no_save_image,
        no_save_json=args.no_save_json,
        output_name="privacy2json_hw_pc"
    )


import os
import re
import json
import hashlib
from textwrap import dedent
from PIL import Image, ImageDraw, ImageFont

# 从util导入所有通用函数
from util import (
    save_annotated_image,
    process_images,
    create_argument_parser,
    validate_and_print_args
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
        if category_code:
            attr["分类"] = category_code
            attr["attr"] = {"分类": category_code}

        points = [round(value, 6) for value in payload["points"]]
        return {
            "_id": f"{image_record_id}_{seq_id:04d}",
            "id": seq_id,
            "label": RISK_LABEL_MAP.get(risk, risk),
            "drawType": DRAW_TYPE,
            "group": 0,
            "points": points,
            "zIndex": seq_id,
            "attr": attr
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


def build_parser(formatter):
    """
    返回带状态的解析函数，负责解析LLM输出、绘制标注并收集JSON结果
    """

    def parse_and_annotate(ai_output, image_path, output_dir, print_ocr=False, no_save_image=False):
        privacy_items = []
        label_payloads = []

        try:
            image = Image.open(image_path)
            img_width, img_height = image.size
            print(f"图片尺寸: {img_width}x{img_height}")
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
                print("未找到指定字体，使用默认字体")
                font = ImageFont.load_default()

        colors = {
            "high": "red",
            "medium": "orange",
            "low": "yellow",
            "none": "green"
        }

        if not ai_output or not ai_output.strip():
            print("AI输出为空，跳过文本解析，仅记录图片尺寸。")
            lines = []
        else:
            lines = ai_output.strip().split('\n')
            print(f"检测到 {len(lines)} 行数据，开始绘制...")

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
            
            # 调试信息
            if not coords_str.startswith('{'):
                print(f"坐标字段格式错误:\n  原始行: {line[:100]}\n  coords_str: {coords_str}")

            if risk == "none":
                necessity = "not_necessary"

            try:
                coords = json.loads(coords_str)
                x1, y1, x2, y2 = coords['x1'], coords['y1'], coords['x2'], coords['y2']

                x1_px = x1 * img_width / 1000
                y1_px = y1 * img_height / 1000
                x2_px = x2 * img_width / 1000
                y2_px = y2 * img_height / 1000

                # print(f"绘制归一化后坐标: [({x1_px:.1f}, {y1_px:.1f}), ({x2_px:.1f}, {y2_px:.1f})]")

                color = colors.get(risk, "green")
                
                # 对于 necessary 的框绘制双层边框，更加明显
                if necessity == "necessary":
                    # 绘制外层边框（加粗效果）
                    draw.rectangle([x1_px, y1_px, x2_px, y2_px], outline=color, width=5)
                    # 绘制内层边框（双层效果）
                    offset = 5
                    draw.rectangle([x1_px + offset, y1_px + offset, x2_px - offset, y2_px - offset], 
                                 outline=color, width=3)
                else:
                    # 普通单层边框
                    draw.rectangle([x1_px, y1_px, x2_px, y2_px], outline=color, width=3)

                # 提取分类数字（只提取一次，避免重复）
                category_match = re.search(r'(\d+)', category)
                category_code = category_match.group(1) if category_match else ""
                
                # 只显示风险等级首字母和分类数字
                risk_letter = risk.upper()[0]  # 只取第一个字母：H/M/L/N
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

    return parse_and_annotate

def process(directory_path, enable_ocr=True, start=1, end=None, model_name="openai/gpt-5-pro", print_ocr=False, no_save_image=False, no_save_json=False, output_name="privacy2json"):
    """批量处理图片和manager.json文件（直接坐标定位版）
    
    统一使用 0-1000 归一化坐标系统
    """
    
    # 统一使用 0-1000 归一化坐标
    prompt_template = dedent("""\
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
        Mark each such item as either "necessary" or "not_necessary".

        ### Risk levels

        Use exactly these four labels: high, medium, low, none.

        - high: Information that can directly identify or contact a person.
        Includes: name/id, exact address or location, email address, phone number, ID/passport number, IP address, device ID, account ID, user ID, bank card number, password, authentication tokens.

        - medium: Information that can reasonably infer a person's behavior, preferences, or identity, but does not directly identify them.
        Includes: Installed applications, browsing history, search history, call history, chat content, follow/subscribe lists, calendar/schedule, to-do list, shopping cart items, order history, nearby places in location, distance from "home" or "current location", company name, school name, job title, internal project names.

        - low: Technical or contextual information that only becomes privacy-relevant after analysis or correlation with other data.
        Includes: time, device parameters, recommended content, generic search queries without clear target, non-specific system messages, references to previously detected private info.

        - none: Public or generic content that anyone can find on the internet and that does not target a person.
        Includes: other people's names/ids, public posts, news headlines, public ads, general app UI text, fixed icons, slogans, public creator profiles and posts, comments/bullets that are clearly public, generic help texts.
        
        ### Privacy category

        1. **Core Identity Identifiers** — uniquely identify a person on their own. 
        - Examples: real name, national ID/passport/student/employee numbers, account/ID that uniquely maps to a person.

        2. **Contact & Financial** — directly contacts a person or links to funds. 
        - Examples: email, phone, home address, bank card, payment account.

        3. **Technical & Device Identifiers** — enable cross-session/device tracking. 
        - Examples: location related a person, location on the map, timestamps, device ID, IMEI, MAC, ad ID, cookie ID, browser fingerprint, IP (context-dependent).

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
        - Fourth field: precise coordinates in normalized coordinates (0-1000 scale), as a JSON object like {{"x1":80, "y1":250, "x2":740, "y2":350}} where x1,y1 is the top-left corner and x2,y2 is the bottom-right corner. Use a 0-1000 coordinate system where (0,0) is top-left and (1000,1000) is bottom-right.
        - Fifth field: "necessary" if the item is strictly required for the Agent to correctly complete its goal; otherwise "not_necessary".

        ### Examples

        john.smith@gmail.com | high | 2(Contact & Financial) | {{"x1":80, "y1":250, "x2":740, "y2":350}} | necessary
        Search in mail | none | - | {{"x1":200, "y1":400, "x2":250, "y2":500}} | not_necessary

        ### Notes
        - For textual items, use the **exact text** from the screenshot (verbatim).
        - For non-text items, use a concise, clear description of the visible content.
        - Please identify all privacy-relevant items in the screenshot.
        - If the same item appears multiple times in the screenshot, please identify all of them and do not ignore them.
    """)


    formatter = PrivacyJSONFormatter(directory_path)
    parser = build_parser(formatter)
    
    process_images(directory_path, parser, prompt_template, enable_ocr, 
                   start, end, model_name, print_ocr, no_save_image, no_save_json, 
                   print_ai_output=True, output_name=output_name, formatter=formatter)

if __name__ == "__main__":
    parser = create_argument_parser(description='隐私信息分析工具 (直接坐标定位版)')
    args = parser.parse_args()
    validate_and_print_args(args)
    process(args.directory, not args.no_ocr, args.start, args.end, args.model, args.print_ocr, args.no_save_image, args.no_save_json, "privacy2json")

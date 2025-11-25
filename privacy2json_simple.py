import os
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

        output_path = os.path.join(target_dir, "图片隐私标注.json")
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
            "private": "red",
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

            parts = [part.strip() for part in line.rsplit('|', 2)]

            if len(parts) != 3:
                continue

            text, risk, coords_str = parts
            risk = risk.lower()

            try:
                coords = json.loads(coords_str)
                x1, y1, x2, y2 = coords['x1'], coords['y1'], coords['x2'], coords['y2']

                x1_px = x1 * img_width / 1000
                y1_px = y1 * img_height / 1000
                x2_px = x2 * img_width / 1000
                y2_px = y2 * img_height / 1000

                print(f"绘制归一化后坐标: [({x1_px:.1f}, {y1_px:.1f}), ({x2_px:.1f}, {y2_px:.1f})]")

                color = colors.get(risk, "green")

                draw.rectangle([x1_px, y1_px, x2_px, y2_px], outline=color, width=3)

                label_text = risk.upper()
                bbox = font.getbbox(label_text)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                draw.rectangle([x1_px, y1_px - text_height - 4, x1_px + text_width + 4, y1_px], fill=color)

                text_color = "black" if risk in ["low", "none"] else "white"
                draw.text((x1_px + 2, y1_px - text_height - 4), label_text, fill=text_color, font=font)

                privacy_items.append({
                    "text": text,
                    "level": risk,
                    "category": "",
                    "coordinates": coords,
                    "found_in_image": True,
                    "color": color
                })

                label_payloads.append({
                    "text": text,
                    "risk": risk,
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

def process(directory_path, enable_ocr=True, start=1, end=None, model_name="openai/gpt-5-pro", print_ocr=False, no_save_image=False, no_save_json=False, output_name="privacy2json_simple"):
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
        2. Then, for each meaningful item or region, decide whether it contains privacy-sensitive information.
        3. For each item, output its original content/description, its privacy status, and its precise coordinates in the screenshot.

        ### Privacy risk

        Use exactly these two labels: private, none.

        - private: Information that has any privacy risk. This includes:
        * Information that can directly identify or contact the user/operator.
            Examples: name/id of the user/operator, exact address or location, email address, phone number,
            ID/passport number, IP address, device ID, account ID, user ID, bank card number, password,
            authentication tokens.
        * Information that can reasonably infer the user/operator's behavior, preferences, or identity.
            Examples: installed applications, browsing history, search history, call history, chat content,
            follow/subscribe lists, calendar/schedule, to-do list, shopping cart items, order history,
            nearby places in location, distance from "home" or "current location", company name, school name,
            job title, internal project names.
        * Technical or contextual information that becomes privacy-relevant when combined with other data.
            Examples: time, device parameters, recommended content, generic search queries without clear target,
            non-specific system messages, references to previously detected private info.
        * Sensitive special categories:
            health/medical, religion, political views, union membership, sexual orientation/sex life,
            biometric/genetic data used for identification.
        * Inferred attributes:
            interests/preferences, credit/risk scores, audience segments, similarity scores.

        - none: Public or generic content that anyone can find on the internet and that does not target the user/operator.
        Includes: other people's names/ids, public posts, news headlines, public ads, general app UI text,
        fixed icons, slogans, public creator profiles and posts, comments/bullets that are clearly public,
        generic help texts.

        ### Output format

        For each item, output one line in the following format (do NOT output the format template itself, only the actual data):

        [exact text or description] | [privacy status] | [coordinates JSON]

        Where:
        - First field: for textual items, the exact visible text from the screenshot (verbatim); for non-text items,
        a concise description of the visible content (e.g. "face of a person", "bank card image").
        - Second field: one of "private" or "none".
        - Third field: precise coordinates in normalized coordinates (0-1000 scale), as a JSON object like
        {{"x1":80, "y1":250, "x2":740, "y2":350}} where x1,y1 is the top-left corner and x2,y2 is the
        bottom-right corner. Use a 0-1000 coordinate system where (0,0) is top-left and (1000,1000) is bottom-right.

        ### Examples

        john.smith@gmail.com | private | {{"x1":80, "y1":250, "x2":740, "y2":350}}
        Search in mail | none | {{"x1":200, "y1":400, "x2":250, "y2":500}}

        ### Notes
        - For textual items, use the **exact text** from the screenshot (verbatim).
        - For non-text items, use a concise, clear description of the visible content.
        - Please identify all items in the screenshot.
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
    process(args.directory, not args.no_ocr, args.start, args.end, args.model, args.print_ocr, args.no_save_image, args.no_save_json, "privacy2json_simple")

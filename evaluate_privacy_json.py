import argparse
import json
import os
from typing import Dict, List, Optional, Tuple, Set

from urllib.parse import urlparse

RISK_LABELS = {"高风险", "中风险", "低风险"}
IOU_THRESHOLD = 0.6


def load_annotations(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_filename(info: str) -> Optional[str]:
    if not info:
        return None

    info = info.strip()
    parsed = urlparse(info)
    candidate = parsed.path if parsed.scheme else info
    candidate = candidate.split("?")[0]
    basename = os.path.basename(candidate.strip("/"))
    return basename or None


def build_entry_map(entries: List[dict]) -> Dict[str, dict]:
    mapping: Dict[str, dict] = {}
    for entry in entries:
        keys = build_lookup_keys(entry)
        for key in keys:
            mapping[key] = entry
    return mapping


def build_lookup_keys(entry: dict) -> List[str]:
    keys: List[str] = []
    filename = extract_filename(entry.get("info", ""))
    if filename:
        keys.append(f"file::{filename}")
    if entry.get("index") is not None:
        keys.append(f"index::{entry['index']}")
    if entry.get("lensFrame") is not None:
        keys.append(f"lens::{entry['lensFrame']}")
    return keys


def get_matching_entry(gt_entry: dict, ai_map: Dict[str, dict]) -> Optional[dict]:
    for key in build_lookup_keys(gt_entry):
        if key in ai_map:
            return ai_map[key]
    return None


def to_rect(points: List[float]) -> Tuple[float, float, float, float]:
    if len(points) != 4:
        raise ValueError("points 必须包含 4 个数值 [x1, y1, x2, y2]")
    x1, y1, x2, y2 = points
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def compute_iou(box_a: List[float], box_b: List[float]) -> float:
    ax1, ay1, ax2, ay2 = to_rect(box_a)
    bx1, by1, bx2, by2 = to_rect(box_b)

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)

    union_area = area_a + area_b - inter_area
    if union_area == 0:
        return 0.0
    return inter_area / union_area


def find_best_match(
    gt_label: dict, ai_labels: List[dict], ai_entry_id: str, used_ai: Set[Tuple[str, str]]
) -> Optional[Tuple[dict, str, float, bool]]:
    gt_attr = gt_label.get("attr", {})
    target_text = gt_attr.get("ocrResult", "").strip()
    if not target_text:
        return None

    candidates = []
    for idx, ai_label in enumerate(ai_labels):
        ai_attr = ai_label.get("attr", {})
        ai_text = ai_attr.get("ocrResult", "").strip()
        if ai_label.get("label") not in RISK_LABELS:
            continue
        if ai_text != target_text:
            continue

        ai_label_id = ai_label.get("_id") or f"{ai_entry_id}_{idx}"
        if (ai_entry_id, ai_label_id) in used_ai:
            continue

        try:
            iou_value = compute_iou(gt_label.get("points", []), ai_label.get("points", []))
        except Exception:
            continue

        candidates.append((iou_value, ai_label, ai_label_id))

    if not candidates:
        return None

    iou_value, best_label, best_label_id = max(candidates, key=lambda item: item[0])
    gt_category = str(gt_attr.get("分类", "")).strip()
    ai_category = str(best_label.get("attr", {}).get("分类", "")).strip()
    meets_category = gt_category == ai_category
    meets_risk = best_label.get("label") == gt_label.get("label")
    meets_iou = iou_value >= IOU_THRESHOLD
    strict_match = meets_category and meets_risk and meets_iou

    if strict_match:
        used_ai.add((ai_entry_id, best_label_id))

    return best_label, best_label_id, iou_value, strict_match


def evaluate(gt_path: str, ai_path: str, output_path: Optional[str] = None) -> None:
    gt_entries = load_annotations(gt_path)
    ai_entries = load_annotations(ai_path)
    ai_map = build_entry_map(ai_entries)

    total_gt = 0
    total_ai = 0
    matched = 0
    used_ai_labels: Set[Tuple[str, str]] = set()

    for ai_entry in ai_entries:
        for ai_label in ai_entry.get("labels", []):
            if ai_label.get("label") in RISK_LABELS:
                total_ai += 1

    detailed_entries: List[dict] = []

    for gt_entry in gt_entries:
        ai_entry = get_matching_entry(gt_entry, ai_map)
        if ai_entry is None:
            ai_entry_id = f"missing_{gt_entry.get('index')}"
            ai_labels = []
            ai_image_found = False
        else:
            ai_entry_id = ai_entry.get("_id") or f"entry_{ai_entry.get('index')}"
            ai_labels = ai_entry.get("labels", [])
            ai_image_found = True

        entry_record = {
            "info": gt_entry.get("info"),
            "index": gt_entry.get("index"),
            "lensFrame": gt_entry.get("lensFrame"),
            "size": gt_entry.get("size"),
            "labels": []
        }

        for gt_label in gt_entry.get("labels", []):
            if gt_label.get("label") not in RISK_LABELS:
                continue
            total_gt += 1
            gt_attr = gt_label.get("attr", {}) or {}
            gt_category = str(gt_attr.get("分类", "")).strip()

            label_record = {
                "gt_label_id": gt_label.get("_id"),
                "ocrResult": gt_attr.get("ocrResult", ""),
                "gt_risk": gt_label.get("label"),
                "gt_category": gt_category,
                "ai_matched": False,
            "ai_label_id": "",
            "ai_risk": "",
            "ai_category": "",
                "iou": 0.0,
            "ai_image_found": ai_image_found,
            "ai_ocrResult": ""
            }

            if ai_image_found:
                match = find_best_match(gt_label, ai_labels, ai_entry_id, used_ai_labels)
            else:
                match = None

            if match is not None:
                ai_label, _, iou_value, strict_match = match
                ai_attr = ai_label.get("attr", {}) or {}
                label_record.update({
                    "ai_label_id": ai_label.get("_id") or "",
                    "ai_risk": ai_label.get("label") or "",
                    "ai_category": str(ai_attr.get("分类", "")).strip(),
                    "ai_ocrResult": ai_attr.get("ocrResult", "") or "",
                    "iou": round(iou_value, 6)
                })
                if strict_match:
                    matched += 1
                    label_record["ai_matched"] = True

            entry_record["labels"].append(label_record)

        if entry_record["labels"]:
            detailed_entries.append(entry_record)

    precision = matched / total_ai if total_ai else 0.0
    recall = matched / total_gt if total_gt else 0.0

    print("=== 评估结果 ===")
    print(f"GT风险项总数: {total_gt}")
    print(f"AI风险项总数: {total_ai}")
    print(f"匹配成功数: {matched}")
    print(f"精确率 (Precision): {precision:.4f}")
    print(f"召回率 (Recall): {recall:.4f}")

    if output_path is None:
        ai_dir = os.path.dirname(os.path.abspath(ai_path))
        output_path = os.path.join(ai_dir, "ai_vs_gt_detailed.json")

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(detailed_entries, f, ensure_ascii=False, indent=2)
    print(f"详细匹配结果已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="比较人工与AI图片隐私标注结果的风险项精确率与召回率")
    parser.add_argument("--gt", "-g", default="test_data/图片隐私标注.json", help="人工标注JSON路径")
    parser.add_argument("--ai", "-a", default="test_data/mobile/20251031_140418_Reddit_ Search 'r_TwoHotTakes'/privacy2json/google_gemini-3-pro-preview/ai_results.json", help="AI标注JSON路径")
    parser.add_argument("--output", "-o", help="保存详细匹配结果的JSON路径（默认与AI文件同目录）")
    args = parser.parse_args()

    evaluate(args.gt, args.ai, args.output)


if __name__ == "__main__":
    main()


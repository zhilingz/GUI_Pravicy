import argparse
import json
from enum import Enum

from google.cloud import vision
from google.protobuf.json_format import MessageToDict
from PIL import Image, ImageDraw



class FeatureType(Enum):
    PAGE = 1
    BLOCK = 2
    PARA = 3
    WORD = 4
    SYMBOL = 5


def draw_boxes(image, bounds, color):
    """Draws a border around the image using the hints in the vector list.

    Args:
        image: the input image object.
        bounds: list of coordinates for the boxes.
        color: the color of the box.

    Returns:
        An image with colored bounds added.
    """
    draw = ImageDraw.Draw(image)

    for bound in bounds:
        draw.polygon(
            [
                bound.vertices[0].x,
                bound.vertices[0].y,
                bound.vertices[1].x,
                bound.vertices[1].y,
                bound.vertices[2].x,
                bound.vertices[2].y,
                bound.vertices[3].x,
                bound.vertices[3].y,
            ],
            None,
            color,
        )
    return image


def get_document_bounds(image_file, feature):
    """Finds the document bounds given an image and feature type.

    Args:
        image_file: path to the image file.
        feature: feature type to detect.

    Returns:
        List of coordinates for the corresponding feature type.
    """
    client = vision.ImageAnnotatorClient()

    bounds = []

    with open(image_file, "rb") as image_file:
        content = image_file.read()

    image = vision.Image(content=content)

    response = client.document_text_detection(image=image)
    document = response.full_text_annotation

    # Collect specified feature bounds by enumerating all document features
    for page in document.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    for symbol in word.symbols:
                        if feature == FeatureType.SYMBOL:
                            bounds.append(symbol.bounding_box)

                    if feature == FeatureType.WORD:
                        bounds.append(word.bounding_box)

                if feature == FeatureType.PARA:
                    bounds.append(paragraph.bounding_box)

            if feature == FeatureType.BLOCK:
                bounds.append(block.bounding_box)

    # The list `bounds` contains the coordinates of the bounding boxes.
    return bounds, response


def render_doc_text(filein, fileout):
    """Outlines document features (blocks, paragraphs and words) given an image.
    Creates separate images for each color and a combined image.

    Args:
        filein: path to the input image.
        fileout: path to the output image (combined image).
    """
    # Load original image
    original_image = Image.open(filein)
    
    # Get bounds for each feature type
    bounds_block, response = get_document_bounds(filein, FeatureType.BLOCK)
    bounds_para, _ = get_document_bounds(filein, FeatureType.PARA)
    bounds_word, _ = get_document_bounds(filein, FeatureType.WORD)
    
    # Create separate images for each color
    image_blue = original_image.copy()
    image_blue = draw_boxes(image_blue, bounds_block, "blue")
    
    image_red = original_image.copy()
    image_red = draw_boxes(image_red, bounds_para, "red")
    
    image_yellow = original_image.copy()
    image_yellow = draw_boxes(image_yellow, bounds_word, "yellow")

    # Create combined image (horizontal layout)
    # Get the width and height of individual images
    img_width = original_image.width
    img_height = original_image.height
    
    # Create a new image with 3 times the width
    combined_image = Image.new('RGB', (img_width * 3, img_height))
    
    # Paste images side by side
    combined_image.paste(image_blue, (0, 0))
    combined_image.paste(image_red, (img_width, 0))
    combined_image.paste(image_yellow, (img_width * 2, 0))
    
    # Save combined image
    combined_image.save(fileout)
    print(f"Saved combined image: {fileout}")

    # Convert protobuf response to dict and save as JSON
    response_dict = MessageToDict(response._pb)
    json_file = fileout.replace('.png', '.json')
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(response_dict, f, ensure_ascii=False, indent=2)
    print(f"Response saved to: {json_file}")

    
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-detect_file", default="/public/zhangzhiling/code/GUI_Pravicy/data/mobile/20251031_121653_Gmail__View_third_email_in_Sen/images/screenshot_2025-10-31-44252-b1145cb5.png", help="The image for text detection.")
    parser.add_argument("-out_file", default="ocr/test.png", help="Optional output file")
    args = parser.parse_args()

    render_doc_text(args.detect_file, args.out_file)

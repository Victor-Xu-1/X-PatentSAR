"""
Image preprocessing module for OCSR engines.

Preprocesses structure crop images to improve OCSR recognition quality:
- Add padding around structure
- Convert to grayscale
- Binarize (Otsu's method)
- Normalize to white background
- Resize to fixed long edge
"""

import os
import tempfile
from typing import Optional

import cv2
import numpy as np
from PIL import Image


def preprocess_structure_image(
    image_path: str,
    output_dir: str,
    padding: int = 20,
    long_edge: int = 1024,
) -> str:
    """Preprocess a structure image for better OCSR recognition.

    Steps:
    1. Read image
    2. Add white padding around structure
    3. Convert to grayscale
    4. Binarize using Otsu's method
    5. Normalize to white background
    6. Resize so longest edge = long_edge
    7. Save to output_dir

    If preprocessing fails at any step, falls back to the original image.

    Args:
        image_path: Path to original structure crop image.
        output_dir: Directory to save preprocessed image.
        padding: White padding in pixels around the structure.
        long_edge: Target size for the longest edge after resize.

    Returns:
        Path to preprocessed image (or original if preprocessing failed).
    """
    try:
        os.makedirs(output_dir, exist_ok=True)

        # Read image
        img = cv2.imread(image_path)
        if img is None:
            # Try with PIL as fallback
            pil_img = Image.open(image_path)
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            if img is None:
                return image_path  # Fallback to original

        # Step 1: Add white padding
        if padding > 0:
            img = cv2.copyMakeBorder(
                img,
                padding,
                padding,
                padding,
                padding,
                cv2.BORDER_CONSTANT,
                value=[255, 255, 255],  # White
            )

        # Step 2: Convert to grayscale
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()

        # Step 3: Binarize using Otsu's method
        # First, invert if background is dark (normalize to white background)
        mean_val = np.mean(gray)
        if mean_val < 128:
            # Dark background - invert
            gray = cv2.bitwise_not(gray)

        # Otsu binarization
        _, binary = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        # Step 4: Normalize to white background (binary already does this)
        # The binary image has white (255) background and black (0) foreground

        # Step 5: Resize to fixed long edge
        h, w = binary.shape[:2]
        if max(h, w) > 0:
            scale = long_edge / max(h, w)
            if scale != 1.0:
                new_w = int(w * scale)
                new_h = int(h * scale)
                binary = cv2.resize(
                    binary,
                    (new_w, new_h),
                    interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
                )

        # Save preprocessed image
        basename = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(output_dir, f"{basename}_preprocessed.png")
        cv2.imwrite(output_path, binary)

        if os.path.isfile(output_path):
            return output_path
        else:
            return image_path  # Fallback to original

    except Exception as e:
        # If preprocessing fails, return original image path
        return image_path


def is_valid_image(image_path: str) -> bool:
    """Check if a file is a valid, readable image.

    Args:
        image_path: Path to image file.

    Returns:
        True if the image can be opened and read.
    """
    try:
        with Image.open(image_path) as img:
            img.verify()
        return True
    except Exception:
        return False


def get_image_info(image_path: str) -> dict:
    """Get basic info about an image file.

    Args:
        image_path: Path to image file.

    Returns:
        dict with width, height, format, mode, size_bytes.
    """
    try:
        with Image.open(image_path) as img:
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "size_bytes": os.path.getsize(image_path),
            }
    except Exception as e:
        return {"error": str(e)}

"""测试 SAM3 CPU 推理速度和分割效果。

用 date-picker 的日历截图测试文本提示分割。
"""
import sys
import time

# 清除 Hermes 环境污染
sys.path = [p for p in sys.path if "hermes" not in p.lower()]

import torch
from PIL import Image
from transformers import Sam3Model, Sam3Processor

MODEL_PATH = "models/sam3"
TEST_IMAGE = "outputs/bench/click-button_0/screenshots/step1_163817_before.png"

print("加载 SAM3 模型...")
t0 = time.time()
model = Sam3Model.from_pretrained(MODEL_PATH, torch_dtype=torch.float32)
model.eval()
t1 = time.time()
print(f"模型加载耗时: {t1 - t0:.1f}s")

processor = Sam3Processor.from_pretrained(MODEL_PATH)
t2 = time.time()
print(f"Processor 加载耗时: {t2 - t1:.1f}s")

# 加载测试图片
image = Image.open(TEST_IMAGE).convert("RGB")
print(f"图片尺寸: {image.size}")

# 文本提示分割
prompts = ["button", "text", "icon", "input field"]
for prompt in prompts:
    print(f"\n--- 提示: '{prompt}' ---")
    t3 = time.time()
    inputs = processor(images=image, text=prompt, return_tensors="pt")
    t4 = time.time()
    print(f"预处理: {t4 - t3:.1f}s")

    with torch.no_grad():
        outputs = model(**inputs)
    t5 = time.time()
    print(f"推理: {t5 - t4:.1f}s")

    results = processor.post_process_instance_segmentation(
        outputs, threshold=0.5, mask_threshold=0.5,
        target_sizes=inputs.get("original_sizes").tolist()
    )[0]
    t6 = time.time()
    print(f"后处理: {t6 - t5:.1f}s")
    print(f"总耗时: {t6 - t3:.1f}s")
    print(f"找到 {len(results['masks'])} 个对象")
    for i, (score, box) in enumerate(zip(results["scores"], results["boxes"])):
        print(f"  [{i}] score={score:.3f} box={box.tolist()}")

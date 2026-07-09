"""RegionCUA OmniParser 依赖安装脚本。

自动检测 GPU 环境，选择合适的 torch 版本：
- NVIDIA GPU (CUDA) → torch+cu118
- AMD GPU (ROCm, Linux only) → torch+rocm
- AMD GPU (Windows, DirectML 不支持 ultralytics) → torch CPU
- 无 GPU → torch CPU

用法：
  python scripts/install_omniparser.py
  python scripts/install_omniparser.py --force   # 强制重装
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


def detect_gpu() -> str:
    """检测 GPU 类型，返回 'cuda' / 'rocm' / 'cpu'。

    PyTorch ROCm 只发布 Linux 版本，Windows 上 AMD GPU 无法用 ROCm。
    DirectML 虽然支持 AMD GPU 但 ultralytics 不兼容 DirectML 后端。
    所以 Windows AMD GPU 只能走 CPU。
    """
    system = platform.system()

    # 检查 NVIDIA CUDA
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        if result.returncode == 0:
            return "cuda"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 检查 AMD ROCm（仅 Linux）
    if system == "Linux":
        try:
            result = subprocess.run(["rocminfo"], capture_output=True, timeout=5)
            if result.returncode == 0 and b"gfx" in result.stdout:
                return "rocm"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # 检查 AMD GPU（Windows，走 CPU）
    if system == "Windows":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # 检查是否有 AMD 显卡（通过 EnumDisplayDevices）
            # 但无论如何 Windows AMD 走 CPU（ROCm 不支持 Windows）
            return "cpu"
        except Exception:
            pass

    return "cpu"


def get_torch_install_cmd(gpu_type: str, force: bool = False) -> list[str]:
    """根据 GPU 类型返回 uv pip install 命令。"""
    base = ["uv", "pip", "install"]
    if force:
        base.append("--reinstall")

    if gpu_type == "cuda":
        return base + [
            "torch", "torchvision",
            "--index-url", "https://download.pytorch.org/whl/cu118"
        ]
    elif gpu_type == "rocm":
        return base + [
            "torch", "torchvision",
            "--index-url", "https://download.pytorch.org/whl/rocm6.0"
        ]
    else:  # cpu
        return base + [
            "torch", "torchvision",
            "--index-url", "https://download.pytorch.org/whl/cpu"
        ]


def main(force: bool = False) -> None:
    gpu = detect_gpu()
    system = platform.system()

    print("=" * 60)
    print("RegionCUA OmniParser 依赖安装")
    print("=" * 60)
    print(f"系统: {system} {platform.machine()}")
    print(f"GPU 检测: {gpu}")

    if gpu == "cpu" and system == "Windows":
        print()
        print("注意: Windows AMD GPU 无法使用 ROCm（仅 Linux 发布）。")
        print("      DirectML 不兼容 ultralytics，故使用 CPU 推理。")
        print("      CPU 推理速度足够 YOLO + OCR（每张图 1-3 秒）。")
    print()

    # 1. 安装 torch
    cmd = get_torch_install_cmd(gpu, force)
    print(f"[1/3] 安装 torch ({gpu})...")
    print(f"  命令: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("torch 安装失败！")
        sys.exit(1)

    # 2. 安装 ultralytics + easyocr
    print()
    print("[2/3] 安装 ultralytics + easyocr...")
    cmd = ["uv", "pip", "install", "ultralytics", "easyocr"]
    if force:
        cmd.append("--reinstall")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("ultralytics/easyocr 安装失败！")
        sys.exit(1)

    # 3. 下载 OmniParser YOLO 权重
    print()
    print("[3/3] 下载 OmniParser V2 YOLO 权重...")
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        # 清理 hermes 路径
        sys.path = [p for p in sys.path if "hermes" not in p.lower()]
        from region_cua.vision.omniparser import _download_yolo_weights
        path = _download_yolo_weights()
        print(f"  权重路径: {path} ({path.stat().st_size // 1024 // 1024}MB)")
    except Exception as exc:
        print(f"  下载失败: {exc}")
        print("  请手动下载: https://huggingface.co/microsoft/OmniParser-v2.0")
        print("  放到: ~/.cache/omniparser/icon_detect/model.pt")

    # 验证
    print()
    print("=" * 60)
    print("验证安装...")
    try:
        import torch
        print(f"  torch: {torch.__version__}")
        import ultralytics
        print(f"  ultralytics: {ultralytics.__version__}")
        import easyocr
        print(f"  easyocr: {easyocr.__version__}")
        print()
        print("✅ 安装完成！可用 region-cua mcp 启动 MCP 服务器。")
    except ImportError as exc:
        print(f"  ❌ 验证失败: {exc}")


if __name__ == "__main__":
    force = "--force" in sys.argv or "-f" in sys.argv
    main(force=force)

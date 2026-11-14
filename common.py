"""Hằng số và hàm dùng chung cho toàn bộ app."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
SETTINGS_FILE = BASE / "settings.json"
FFMPEG = shutil.which("ffmpeg") or str(BASE / "ffmpeg.exe")
NOWIN = 0x08000000 if os.name == "nt" else 0  # ẩn cửa sổ CMD khi gọi ffmpeg
SR = 24000  # sample rate của track lồng tiếng
MODELS_DIR = BASE / "models"  # nơi tải model TTS offline

# Các engine TTS: khóa -> tên hiển thị
ENGINES = {
    "edge": "Edge TTS (online, nhiều giọng)",
    "gtts": "gTTS Google (online, 1 giọng)",
    "sherpa": "Sherpa-ONNX (offline)",
}

# Tên hiển thị -> (tên ngôn ngữ gửi cho AI, danh sách giọng Edge TTS)
LANGS = {
    "Tiếng Việt": ("Vietnamese", ["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"]),
    "English": ("English", ["en-US-AriaNeural", "en-US-GuyNeural"]),
    "Thai": ("Thai", ["th-TH-PremwadeeNeural", "th-TH-NiwatNeural"]),
    "Indonesian": ("Indonesian", ["id-ID-GadisNeural", "id-ID-ArdiNeural"]),
}


def run(cmd, cwd=None):
    """Chạy lệnh ngoài (ffmpeg...), báo lỗi kèm phần cuối stderr."""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NOWIN)
    if p.returncode != 0:
        raise RuntimeError(f"Lỗi lệnh {Path(cmd[0]).name}:\n{p.stderr[-1500:]}")
    return p


def extract_url(text):
    """Lấy link http(s) đầu tiên trong đoạn chia sẻ Douyin."""
    m = re.search(r"https?://[^\s一-鿿]+", text)
    if not m:
        raise ValueError("Không tìm thấy link trong nội dung đã nhập.")
    return m.group(0).rstrip(".,;)]}>\"'")


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(segs, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}\n\n")

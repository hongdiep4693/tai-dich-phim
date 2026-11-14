"""Nhận dạng lời thoại tiếng Trung bằng Groq Whisper."""
from pathlib import Path

from groq_api import groq_request


def transcribe(pool, model, audio_path):
    """Trả về list {start, end, text} theo thứ tự thời gian."""
    audio_bytes = Path(audio_path).read_bytes()  # đọc 1 lần để thử lại/đổi key vẫn gửi đủ
    r = groq_request(pool, "audio/transcriptions",
                     files={"file": ("audio.mp3", audio_bytes, "audio/mpeg")},
                     data={"model": model, "response_format": "verbose_json",
                           "language": "zh", "temperature": "0"})
    segs = [{"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
            for s in r.json().get("segments", []) if s["text"].strip()]
    if not segs:
        raise RuntimeError("Không nhận dạng được lời thoại nào trong video.")
    return segs

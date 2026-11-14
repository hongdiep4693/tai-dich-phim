"""Lồng tiếng bằng Edge TTS và ghép các câu thành một track âm thanh."""
import asyncio
import re
import wave

import edge_tts
import numpy as np

from common import SR
from ffmpeg_utils import to_wav


def _speakable(text):
    """Câu phải có ít nhất 1 chữ/số, nếu chỉ toàn dấu câu/emoji thì Edge TTS không trả âm thanh."""
    return bool(re.search(r"\w", text or "", re.UNICODE))


async def _tts_all(segs, voice, rate, pitch, outdir):
    """Trả về dict {chỉ số câu: lý do lỗi} cho những câu không đọc được."""
    sem = asyncio.Semaphore(3)
    failed = {}

    async def one(i, text):
        text = (text or "").replace("\n", " ").strip()
        if not _speakable(text):
            failed[i] = "câu rỗng hoặc chỉ có dấu câu, bỏ qua"
            return
        async with sem:
            last = None
            for a in range(4):
                try:
                    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(
                        str(outdir / f"s{i:04d}.mp3"))
                    return
                except Exception as e:
                    last = e
                    await asyncio.sleep(1.5 * (a + 1))
            failed[i] = f"{type(last).__name__}: {last}"

    await asyncio.gather(*(one(i, s["text"]) for i, s in enumerate(segs)))
    return failed


def synthesize(segs, voice, tts_rate, tts_pitch, workdir, log):
    """Đọc từng câu thành s0000.mp3, s0001.mp3... Câu lỗi sẽ bị bỏ qua (có báo trong log)."""
    for old in workdir.glob("s[0-9][0-9][0-9][0-9].mp3"):  # xóa file cũ của lần chạy trước
        old.unlink()
    failed = asyncio.run(_tts_all(segs, voice, f"{tts_rate:+d}%", f"{tts_pitch:+d}Hz", workdir))
    for i in sorted(failed):
        log(f"  ⚠ Câu {i + 1} không có tiếng: {failed[i]} | nội dung: {segs[i]['text']!r}")
    if len(failed) == len(segs):
        raise RuntimeError(
            "Edge TTS không đọc được câu nào. Kiểm tra mạng/giọng đọc, "
            "hoặc cập nhật: pip install -U edge-tts (bản .exe thì build lại).\n"
            f"Lỗi đầu tiên: {failed[min(failed)]}")


def compose_dub(segs, workdir, out_wav, max_speedup):
    """Đặt từng câu đúng mốc thời gian, tăng tốc nhẹ nếu dài hơn khoảng trống."""
    placed, cursor = [], 0
    for i, s in enumerate(segs):
        mp3, wav = workdir / f"s{i:04d}.mp3", workdir / f"s{i:04d}.wav"
        if not mp3.exists():  # câu này đọc lỗi -> để im lặng
            continue
        nxt = segs[i + 1]["start"] if i + 1 < len(segs) else s["end"] + 3
        avail = max(nxt - s["start"], s["end"] - s["start"], 0.5)
        data = to_wav(mp3, wav)
        dur = len(data) / SR
        if dur > avail:
            data = to_wav(mp3, wav, min(dur / avail, max_speedup))
        pos = max(int(s["start"] * SR), cursor)
        placed.append((pos, data))
        cursor = pos + len(data)
    total = np.zeros(cursor + SR, dtype=np.int32)
    for pos, data in placed:
        total[pos:pos + len(data)] += data
    total = np.clip(total, -32768, 32767).astype(np.int16)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(total.tobytes())

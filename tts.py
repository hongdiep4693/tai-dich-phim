"""Lồng tiếng bằng Edge TTS và ghép các câu thành một track âm thanh."""
import asyncio
import wave

import edge_tts
import numpy as np

from common import SR
from ffmpeg_utils import to_wav


async def _tts_all(segs, voice, rate, pitch, outdir):
    sem = asyncio.Semaphore(4)

    async def one(i, text):
        async with sem:
            for a in range(4):
                try:
                    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(
                        str(outdir / f"s{i:04d}.mp3"))
                    return
                except Exception:
                    await asyncio.sleep(1 + a)
            raise RuntimeError(f"Edge TTS lỗi ở câu {i + 1}")

    await asyncio.gather(*(one(i, s["text"]) for i, s in enumerate(segs)))


def synthesize(segs, voice, tts_rate, tts_pitch, workdir):
    """Đọc từng câu thành s0000.mp3, s0001.mp3... trong workdir."""
    asyncio.run(_tts_all(segs, voice, f"{tts_rate:+d}%", f"{tts_pitch:+d}Hz", workdir))


def compose_dub(segs, workdir, out_wav, max_speedup):
    """Đặt từng câu đúng mốc thời gian, tăng tốc nhẹ nếu dài hơn khoảng trống."""
    placed, cursor = [], 0
    for i, s in enumerate(segs):
        mp3, wav = workdir / f"s{i:04d}.mp3", workdir / f"s{i:04d}.wav"
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

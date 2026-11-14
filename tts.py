"""Lồng tiếng: Edge TTS (online), gTTS (online), Sherpa-ONNX (offline) và ghép thành một track.

Mỗi engine ghi file cho từng câu vào thư mục làm việc:
  s0000.mp3      (Edge TTS, gTTS)
  s0000.raw.wav  (Sherpa-ONNX)
rồi compose_dub() ghép lại đúng mốc thời gian.
"""
import asyncio
import os
import re
import tarfile
import time
import wave
from pathlib import Path

import edge_tts
import numpy as np
import requests

from common import ENGINES, SR
from ffmpeg_utils import to_wav

GTTS_LANG = {"Tiếng Việt": "vi", "English": "en", "Thai": "th", "Indonesian": "id"}
SHERPA_DEFAULT_MODEL = "vits-piper-vi_VN-vais1000-medium"


def _speakable(text):
    """Câu phải có ít nhất 1 chữ/số, nếu chỉ toàn dấu câu/emoji thì TTS không trả âm thanh."""
    return bool(re.search(r"\w", text or "", re.UNICODE))


def _clean(text):
    return (text or "").replace("\n", " ").strip()


# ----------------------------------------------------------------- Edge TTS
async def _tts_all(segs, voice, rate, pitch, outdir):
    """Trả về dict {chỉ số câu: lý do lỗi} cho những câu không đọc được."""
    sem = asyncio.Semaphore(3)
    failed = {}

    async def one(i, text):
        text = _clean(text)
        if not _speakable(text):
            failed[i] = "câu rỗng hoặc chỉ có dấu câu, bỏ qua"
            return
        final = outdir / f"s{i:04d}.mp3"
        part = outdir / f"s{i:04d}.part"  # ghi ra file tạm, chỉ đổi tên khi tải đủ
        async with sem:
            last = None
            for a in range(4):
                try:
                    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(part))
                    if part.stat().st_size < 500:
                        raise RuntimeError("file âm thanh rỗng hoặc bị cắt")
                    os.replace(part, final)
                    return
                except Exception as e:
                    last = e
                    part.unlink(missing_ok=True)
                    await asyncio.sleep(1.5 * (a + 1))
            failed[i] = f"{type(last).__name__}: {last}"

    await asyncio.gather(*(one(i, s["text"]) for i, s in enumerate(segs)))
    return failed


def _synth_edge(segs, c, outdir, log):
    return asyncio.run(_tts_all(segs, c["voice"], f"{int(c['tts_rate']):+d}%",
                                f"{int(c['tts_pitch']):+d}Hz", outdir))


# ----------------------------------------------------------------- gTTS
def _synth_gtts(segs, c, outdir, log):
    try:
        from gtts import gTTS
    except ImportError:
        raise RuntimeError("Chưa cài gTTS: pip install gTTS")
    lang = GTTS_LANG.get(c["lang"], "vi")
    failed = {}
    for i, s in enumerate(segs):
        text = _clean(s["text"])
        if not _speakable(text):
            failed[i] = "câu rỗng hoặc chỉ có dấu câu, bỏ qua"
            continue
        part, final = outdir / f"s{i:04d}.part", outdir / f"s{i:04d}.mp3"
        last = None
        for a in range(3):
            try:
                gTTS(text=text, lang=lang).save(str(part))
                if part.stat().st_size < 500:
                    raise RuntimeError("file âm thanh rỗng hoặc bị cắt")
                os.replace(part, final)
                last = None
                break
            except Exception as e:
                last = e
                part.unlink(missing_ok=True)
                time.sleep(1.5 * (a + 1))
        if last:
            failed[i] = f"{type(last).__name__}: {last}"
        time.sleep(0.3)  # tránh bị Google giới hạn tốc độ
    return failed


# ----------------------------------------------------------------- Sherpa-ONNX (offline)
def _find_sherpa(model_dir):
    root = Path(model_dir or "")
    if not root.is_dir():
        raise RuntimeError(f"Chưa có thư mục model Sherpa ({model_dir!r}). "
                           "Bấm 'Tải model tiếng Việt' hoặc chọn thư mục đã giải nén.")

    def first(pattern):
        hits = sorted(root.rglob(pattern))
        return hits[0] if hits else None
    onnx, tokens = first("*.onnx"), first("tokens.txt")
    data, lex = first("espeak-ng-data"), first("lexicon.txt")
    if not onnx or not tokens:
        raise RuntimeError("Thư mục model thiếu file .onnx hoặc tokens.txt.")
    return onnx, tokens, (data if data and data.is_dir() else None), lex


def _synth_sherpa(segs, c, outdir, log):
    try:
        import sherpa_onnx
    except ImportError:
        raise RuntimeError("Chưa cài sherpa-onnx: pip install sherpa-onnx")
    onnx, tokens, data, lex = _find_sherpa(c.get("sherpa_dir"))
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(onnx), lexicon=str(lex) if lex else "",
                data_dir=str(data) if data else "", tokens=str(tokens)),
            provider="cpu", debug=False, num_threads=2),
        max_num_sentences=1)
    if not cfg.validate():
        raise RuntimeError("Cấu hình model Sherpa không hợp lệ, kiểm tra lại thư mục model.")
    engine = sherpa_onnx.OfflineTts(cfg)
    try:
        sid = int(str(c.get("sherpa_sid", "0")).strip() or 0)
    except ValueError:
        sid = 0
    speed = min(2.0, max(0.5, 1 + int(c["tts_rate"]) / 100))
    failed = {}
    for i, s in enumerate(segs):
        text = _clean(s["text"])
        if not _speakable(text):
            failed[i] = "câu rỗng hoặc chỉ có dấu câu, bỏ qua"
            continue
        try:
            audio = engine.generate(text, sid=sid, speed=speed)
            samples = np.asarray(audio.samples, dtype=np.float32)
            if samples.size < 100:
                raise RuntimeError("model không trả về âm thanh")
            pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
            with wave.open(str(outdir / f"s{i:04d}.raw.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(int(audio.sample_rate))
                w.writeframes(pcm.tobytes())
        except Exception as e:
            failed[i] = f"{type(e).__name__}: {e}"
    return failed


def download_sherpa_model(dest_root, log, name=SHERPA_DEFAULT_MODEL):
    """Tải và giải nén model Sherpa-ONNX từ GitHub (k2-fsa). Trả về thư mục model."""
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    target = dest_root / name
    if target.is_dir() and any(target.rglob("*.onnx")):
        log(f"Model đã có sẵn: {target}")
        return target
    url = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{name}.tar.bz2"
    tmp = dest_root / f"{name}.tar.bz2"
    log(f"Đang tải {url}")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total, done, next_pct = int(r.headers.get("content-length", 0)), 0, 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total and done * 100 / total >= next_pct:
                    log(f"  {done >> 20}/{total >> 20} MB")
                    next_pct += 25
    log("Đang giải nén…")
    root = dest_root.resolve()
    with tarfile.open(tmp, "r:bz2") as tf:
        for m in tf.getmembers():  # chặn đường dẫn thoát ra ngoài thư mục đích
            base = root / Path(m.name).parent
            dest = (root / m.name).resolve()
            link_ok = True
            if m.issym() or m.islnk():
                link_ok = (base / m.linkname).resolve().is_relative_to(root)
            if not dest.is_relative_to(root) or not link_ok:
                raise RuntimeError("Gói model chứa đường dẫn không an toàn, đã dừng.")
        tf.extractall(dest_root)
    tmp.unlink(missing_ok=True)
    return target


# ----------------------------------------------------------------- điều phối + ghép track
_ENGINES = {"edge": _synth_edge, "gtts": _synth_gtts, "sherpa": _synth_sherpa}
_PATTERNS = ("s[0-9][0-9][0-9][0-9].mp3", "s[0-9][0-9][0-9][0-9].part",
             "s[0-9][0-9][0-9][0-9].raw.wav")


def synthesize(segs, c, workdir, log):
    """Đọc từng câu bằng engine đã chọn. Câu lỗi bị bỏ qua (có báo trong log)."""
    for pattern in _PATTERNS:
        for old in workdir.glob(pattern):  # xóa file cũ của lần chạy trước
            old.unlink()
    engine = c.get("tts_engine", "edge")
    log(f"Engine TTS: {ENGINES.get(engine, engine)}")
    failed = _ENGINES[engine](segs, c, workdir, log)
    for i in sorted(failed):
        log(f"  ⚠ Câu {i + 1} không có tiếng: {failed[i]} | nội dung: {segs[i]['text']!r}")
    if len(failed) == len(segs):
        raise RuntimeError(
            "TTS không đọc được câu nào. Kiểm tra mạng/giọng đọc/model; với Edge TTS hãy cập nhật: "
            "pip install -U edge-tts (bản .exe thì build lại).\n"
            f"Lỗi đầu tiên: {failed[min(failed)]}")


def _source(workdir, i):
    for name in (f"s{i:04d}.mp3", f"s{i:04d}.raw.wav"):
        p = workdir / name
        if p.exists():
            return p
    return None


def compose_dub(segs, workdir, out_wav, max_speedup, log):
    """Đặt từng câu đúng mốc thời gian, tăng tốc nhẹ nếu dài hơn khoảng trống."""
    placed, cursor = [], 0
    for i, s in enumerate(segs):
        src, wav = _source(workdir, i), workdir / f"s{i:04d}.wav"
        if src is None:  # câu này đọc lỗi -> để im lặng
            continue
        nxt = segs[i + 1]["start"] if i + 1 < len(segs) else s["end"] + 3
        avail = max(nxt - s["start"], s["end"] - s["start"], 0.5)
        try:
            data = to_wav(src, wav)
            dur = len(data) / SR
            if dur > avail:
                data = to_wav(src, wav, min(dur / avail, max_speedup))
        except Exception as e:  # file âm thanh hỏng -> bỏ qua câu này, không dừng cả quy trình
            log(f"  ⚠ Câu {i + 1}: file âm thanh hỏng, để im lặng ({str(e).splitlines()[-1][:80]})")
            continue
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

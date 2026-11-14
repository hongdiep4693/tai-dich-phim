"""Chạy toàn bộ quy trình: tải -> nhận dạng -> ngữ cảnh -> dịch -> TTS -> render."""
import json
import shutil
import time
from pathlib import Path

from common import LANGS, extract_url, write_srt
from douyin import download_video, resolve_douyin
from ffmpeg_utils import extract_audio, render
from groq_api import KeyPool
from transcribe import transcribe
from translate import build_context, translate_all
from tts import compose_dub, synthesize


def pipeline(c, log, step):
    """c: dict cấu hình từ giao diện. log(msg), step(tên, % tiến độ)."""
    outroot = Path(c["outdir"])
    pool = KeyPool(c["api_key"])
    log(f"Đang dùng {len(pool)} Groq API key (xoay vòng theo thứ tự).")
    lang = LANGS[c["lang"]][0]

    if c["local_video"]:
        vid = "local"
        work = outroot / f"local_{int(time.time())}"
        work.mkdir(parents=True, exist_ok=True)
        video = work / "video.mp4"
        shutil.copy(c["local_video"], video)
    else:
        step("Lấy link", 5)
        url = extract_url(c["text"])
        log(f"Link: {url}")
        url, vid = resolve_douyin(url)
        log(f"Link video: {url}")
        work = outroot / vid
        work.mkdir(parents=True, exist_ok=True)
        step("Tải video", 10)
        video = download_video(url, vid, work, c, log)
    log(f"Video: {video}")

    step("Trích âm thanh + nhận dạng", 25)
    audio = work / "audio.mp3"
    extract_audio(video, audio)
    segs = transcribe(pool, c["whisper"], audio)
    log(f"Nhận dạng được {len(segs)} câu thoại.")
    (work / "segments_zh.json").write_text(json.dumps(segs, ensure_ascii=False, indent=1), "utf-8")

    step("Phân tích cốt truyện & nhân vật", 40)
    ctx = build_context(pool, c["model"], segs, lang)
    (work / "context.json").write_text(json.dumps(ctx, ensure_ascii=False, indent=1), "utf-8")
    log("Tóm tắt: " + str(ctx.get("summary", ""))[:300])
    log("Nhân vật: " + ", ".join(f"{x.get('zh')}→{x.get('translated')}" for x in ctx.get("characters", [])))

    step("Dịch phụ đề", 55)
    tr = translate_all(pool, c["model"], segs, ctx, lang, log)
    write_srt(tr, work / "sub.srt")

    step("Lồng tiếng Edge TTS", 70)
    synthesize(tr, c, work, log)
    dub = work / "dub.wav"
    compose_dub(tr, work, dub, c["max_speedup"], log)

    step("Render video cuối", 85)
    final = work / f"final_{vid}.mp4"
    render(video, dub, work, final, c)
    step("Xong", 100)
    log(f"HOÀN TẤT: {final}")
    return final

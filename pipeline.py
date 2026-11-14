"""Chạy toàn bộ quy trình: tải -> nhận dạng -> ngữ cảnh -> dịch -> TTS -> render."""
import json
import os
import re
import shutil
import time
from pathlib import Path

import requests
import yt_dlp

from common import FFMPEG, LANGS, extract_url, write_srt
from ffmpeg_utils import extract_audio, render
from groq_api import KeyPool
from transcribe import transcribe
from translate import build_context, translate_all
from tts import compose_dub, synthesize


def resolve_douyin(url):
    """Mở link rút gọn v.douyin.com, trả về (link video chuẩn, id video)."""
    ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")
    r = requests.get(url, headers={"User-Agent": ua}, allow_redirects=True, timeout=20)
    m = re.search(r"/(?:video|note)/(\d+)", r.url)
    return (f"https://www.douyin.com/video/{m.group(1)}", m.group(1)) if m else (r.url, "video")


def download_video(url, work, c):
    opts = {"outtmpl": str(work / "video.%(ext)s"), "format": "bv*+ba/b",
            "merge_output_format": "mp4", "quiet": True, "no_warnings": True,
            "noplaylist": True, "overwrites": True}
    if FFMPEG and os.path.isabs(FFMPEG):
        opts["ffmpeg_location"] = FFMPEG
    if c["cookies"]:
        opts["cookiefile"] = c["cookies"]
    elif c["browser"] != "none":
        opts["cookiesfrombrowser"] = (c["browser"],)
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([url])
    except Exception as e:
        raise RuntimeError(
            f"Tải video thất bại: {e}\nThử: chọn cookies.txt / trình duyệt đã đăng nhập Douyin, "
            "build lại để cập nhật yt-dlp, hoặc dùng nút 'Chọn video có sẵn'.")
    return next(work.glob("video.*"))


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
        video = download_video(url, work, c)
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
    synthesize(tr, c["voice"], c["tts_rate"], c["tts_pitch"], work)
    dub = work / "dub.wav"
    compose_dub(tr, work, dub, c["max_speedup"])

    step("Render video cuối", 85)
    final = work / f"final_{vid}.mp4"
    render(video, dub, work, final, c)
    step("Xong", 100)
    log(f"HOÀN TẤT: {final}")
    return final

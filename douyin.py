"""Lấy link chuẩn và tải video Douyin.

Thứ tự thử:
  1. Trang chia sẻ iesdouyin.com (không cần cookies) - lấy link phát không logo.
  2. yt-dlp (có thể cần cookies mới của Douyin).
"""
import json
import os
import re

import requests
import yt_dlp

from common import FFMPEG

UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")


def resolve_douyin(url):
    """Mở link rút gọn v.douyin.com, trả về (link video chuẩn, id video)."""
    r = requests.get(url, headers={"User-Agent": UA_MOBILE}, allow_redirects=True, timeout=20)
    m = re.search(r"/(?:video|note)/(\d+)", r.url)
    return (f"https://www.douyin.com/video/{m.group(1)}", m.group(1)) if m else (r.url, "video")


def _save(url, dest):
    headers = {"User-Agent": UA_MOBILE, "Referer": "https://www.douyin.com/"}
    with requests.get(url, headers=headers, stream=True, timeout=60, allow_redirects=True) as r:
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        size = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                size += len(chunk)
    if size < 100_000:
        raise RuntimeError("file tải về quá nhỏ, có thể không phải video")


def download_via_share_page(vid, work):
    """Đọc dữ liệu trong trang chia sẻ và tải file mp4 trực tiếp."""
    r = requests.get(f"https://www.iesdouyin.com/share/video/{vid}/",
                     headers={"User-Agent": UA_MOBILE}, timeout=20)
    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", r.text, re.S)
    if not m:
        raise RuntimeError("không thấy dữ liệu video trong trang chia sẻ")
    data = json.loads(m.group(1))
    item = None
    for v in data.get("loaderData", {}).values():
        info = v.get("videoInfoRes") if isinstance(v, dict) else None
        if info and info.get("item_list"):
            item = info["item_list"][0]
            break
    if not item:
        raise RuntimeError("trang chia sẻ không trả về video (video bị xóa hoặc bị giới hạn)")
    dest = work / "video.mp4"
    last = None
    for u in item["video"]["play_addr"]["url_list"]:
        try:
            _save(u.replace("playwm", "play"), dest)  # playwm = có logo, play = không logo
            return dest
        except Exception as e:
            last = e
    raise RuntimeError(f"không tải được file video: {last}")


def download_via_ytdlp(url, work, c):
    opts = {"outtmpl": str(work / "video.%(ext)s"), "format": "bv*+ba/b",
            "merge_output_format": "mp4", "quiet": True, "no_warnings": True,
            "noplaylist": True, "overwrites": True}
    if FFMPEG and os.path.isabs(FFMPEG):
        opts["ffmpeg_location"] = FFMPEG
    if c["cookies"]:
        opts["cookiefile"] = c["cookies"]
    elif c["browser"] != "none":
        opts["cookiesfrombrowser"] = (c["browser"],)
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([url])
    return next(work.glob("video.*"))


def download_video(url, vid, work, c, log):
    errors = []
    try:
        log("Tải bằng trang chia sẻ (không cần cookies)…")
        return download_via_share_page(vid, work)
    except Exception as e:
        errors.append(f"trang chia sẻ: {e}")
        log(f"  Không được ({e}). Chuyển sang yt-dlp…")
    try:
        return download_via_ytdlp(url, work, c)
    except Exception as e:
        errors.append(f"yt-dlp: {e}")
    raise RuntimeError(
        "Tải video thất bại.\n- " + "\n- ".join(errors) +
        "\n\nCách xử lý: (1) dùng cookies.txt xuất từ trình duyệt đã mở douyin.com "
        "(Chrome mới hay lỗi khi đọc cookies trực tiếp, nên ưu tiên cookies.txt hoặc Firefox); "
        "(2) hoặc tải video về máy rồi dùng nút 'Chọn video có sẵn'.")

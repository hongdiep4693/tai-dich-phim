"""Mọi thao tác gọi ffmpeg: tách âm thanh, đổi wav, render video cuối."""
import wave

import numpy as np

from common import FFMPEG, SR, run


def extract_audio(video, out_mp3):
    """Tách âm thanh mono 16kHz nhẹ để gửi cho Whisper."""
    run([FFMPEG, "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "48k", str(out_mp3)])


def to_wav(src, dst, tempo=1.0):
    """Đổi mp3 sang wav mono SR Hz (có thể tăng tốc), trả về mảng int16."""
    cmd = [FFMPEG, "-y", "-i", str(src), "-ar", str(SR), "-ac", "1"]
    if tempo > 1.001:
        cmd += ["-filter:a", f"atempo={tempo:.4f}"]
    run(cmd + [str(dst)])
    with wave.open(str(dst)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def render(video, dub, workdir, out, c):
    """Burn phụ đề, trộn tiếng, đổi pitch/tempo, xóa metadata -> file mp4 cuối."""
    pitch, tempo = c["pitch"], c["tempo"]
    vf = []
    if c["burn"]:
        style = (f"FontName={c['font']},FontSize={c['fontsize']},Bold=1,"
                 "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,"
                 f"Outline=2,Shadow=0,Alignment=2,MarginV={c['margin']}")
        vf.append(f"subtitles=sub.srt:force_style='{style}'")  # chạy với cwd=workdir
    if abs(tempo - 1) > 1e-3:
        vf.append(f"setpts=PTS/{tempo:.4f}")
    vf.append("format=yuv420p")

    if c["orig_vol"] > 0:
        a = (f"[0:a]volume={c['orig_vol']}[o];[1:a]volume=1.0[d];"
             "[o][d]amix=inputs=2:duration=first:normalize=0[m]")
    else:
        a = "[1:a]anull[m]"
    chain = []
    if abs(pitch - 1) > 1e-3:
        chain.append(f"aresample=44100,asetrate={int(44100 * pitch)},aresample=44100")
    atempo = tempo / pitch if abs(pitch - 1) > 1e-3 else tempo
    if abs(atempo - 1) > 1e-3:
        chain.append(f"atempo={atempo:.4f}")
    a += ";[m]" + (",".join(chain) if chain else "anull") + "[a]"
    fc = f"[0:v]{','.join(vf)}[v];{a}"

    cmd = [FFMPEG, "-y", "-i", str(video), "-i", str(dub), "-filter_complex", fc,
           "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
    if c["strip_meta"]:
        cmd += ["-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact",
                "-flags:v", "+bitexact", "-flags:a", "+bitexact"]
    run(cmd + [str(out)], cwd=workdir)

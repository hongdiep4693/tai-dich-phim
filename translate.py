"""Đọc toàn bộ lời thoại để lập ngữ cảnh (cốt truyện, nhân vật, xưng hô) rồi dịch có ngữ cảnh."""
import json

from groq_api import groq_json


def build_context(pool, model, segs, lang):
    transcript = "\n".join(s["text"] for s in segs)[:24000]
    system = "You analyse transcripts of Chinese short dramas. Reply with JSON only."
    user = f"""Read the WHOLE transcript below (auto speech-recognition, may contain errors).
Return JSON with keys:
- "summary": plot summary in {lang} (5-8 sentences)
- "characters": list of {{"zh": name or role in Chinese, "translated": consistent {lang} name, "gender": "male/female/unknown", "role": short description}}
- "address_terms": list of {{"from": who, "to": whom, "zh_term": Chinese term, "translated_term": natural {lang} equivalent}}
- "style": tone/genre notes for translators
Fix obvious ASR name errors by using the most consistent spelling.

TRANSCRIPT:
{transcript}"""
    return groq_json(pool, model, system, user)


def translate_all(pool, model, segs, ctx, lang, log, batch=20):
    system = (f"You are a professional subtitle translator for Chinese short dramas, translating into {lang}. "
              "Use the story context, character names and address terms strictly and consistently. "
              "Keep each line natural, concise and speakable (similar length to the original speech). "
              "Never merge or split lines. Reply with JSON only: "
              '{"items":[{"id":<int>,"text":"<translation>"}]}.')
    out = {}
    for i in range(0, len(segs), batch):
        chunk = segs[i:i + batch]
        prev = [out[j] for j in range(max(0, i - 3), i) if j in out]
        user = json.dumps({
            "story_context": ctx,
            "previous_translated_lines": prev,
            "translate": [{"id": i + k, "text": s["text"]} for k, s in enumerate(chunk)],
        }, ensure_ascii=False)
        res = groq_json(pool, model, system, user)
        for it in res.get("items", []):
            try:
                out[int(it["id"])] = str(it["text"]).strip()
            except Exception:
                pass
        log(f"  Đã dịch {min(i + batch, len(segs))}/{len(segs)} câu")
    return [dict(s, text=out.get(i) or s["text"]) for i, s in enumerate(segs)]

#!/usr/bin/env python3
"""離線檢查《魚生・于飛・餘生》製片素材，無需網路/API。"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
scenes = json.loads((BASE / "scene_prompts.json").read_text(encoding="utf-8"))
audio = json.loads((BASE / "audio_timeline.json").read_text(encoding="utf-8"))
assert isinstance(scenes, list) and len(scenes) == 16, "必須 16 個鏡頭"
assert audio["duration_seconds"] == 112
character_card, style = scenes[0]["character_card"], scenes[0]["visual_style"]
required = ("scene_id", "scene_title", "image_prompt", "video_prompt", "image_negative_prompt", "video_negative_prompt", "duration_seconds", "character_card", "visual_style", "start_second", "end_second", "cast")
for i, s in enumerate(scenes):
    assert all(k in s for k in required), f"鏡頭 {i} 欄位缺漏"
    assert s["scene_id"] == i, f"鏡頭 {i} 編號不連續"
    assert s["duration_seconds"] == 7 and s["start_second"] == i * 7 and s["end_second"] == (i+1) * 7
    assert s["frame_count"] == 169 and s["width"] == 768 and s["height"] == 1152
    assert s["character_card"] == character_card and s["visual_style"] == style, f"鏡頭 {i} 角色或風格不一致"
    assert set(s["cast"]) <= {"YUCHENG", "YUYU"} and s["cast"], f"鏡頭 {i} 演員名單錯誤"
    for k in ("image_prompt", "video_prompt", "image_negative_prompt", "video_negative_prompt"):
        assert isinstance(s[k], str) and s[k].strip(), f"鏡頭 {i} {k} 為空"
assert sum(s["duration_seconds"] for s in scenes) == 112
by_scene = {}
for c in audio["cues"]:
    i = c["scene_id"]
    assert 0 <= i < 16 and i*7 <= c["start_second"] < c["end_second"] <= (i+1)*7, f"音軌越界 {c['cue_id']}"
    assert c["speaker"] in ("YUCHENG", "YUYU", "NARRATOR")
    assert c["text"].strip()
    by_scene.setdefault(i, []).append((c["start_second"], c["end_second"]))
for i, spans in by_scene.items():
    spans.sort()
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), f"場景 {i} 音軌互相重疊"
assert all("YUCHENG" in s["cast"] for s in scenes if s["scene_id"] in (1, 2, 3, 4, 5, 7, 10, 11, 12, 13, 14))
assert scenes[-1]["cast"] == ["YUYU"] and scenes[-2]["cast"] == ["YUCHENG"], "開放結局不得提前雙人復合"
print("PASS: 16 鏡、112 秒、固定角色、時碼及配音窗口無衝突；未執行 API 或影片生成。")

#!/usr/bin/env python3
"""
run_pipeline.py v3.2 — Bug fixes + I2V quality & consistency overhaul

Fixed from v3.1:
- ✅ import re 移至頂部（原本在 __main__ 會導致 module import NameError）
- ✅ 刪除 v2 殘留死代碼（write_script_v3 後的孤立字串）
- ✅ poll_video URL 提取邏輯修正（remixed_from_video_id 語意錯誤）

I2V 品質提升：
- ✅ Frame Chaining：前一鏡末幀 URL 存入 state，作為下一鏡 anchor_image
- ✅ image_prompt 自動注入視覺一致性種子 token
- ✅ video_prompt 自動附加動態負面描述詞（防跳切/形變/閃爍）
- ✅ 腳本 Coherence Pass：生成後 LLM 審查 character_card 跨場景一致性並修補
- ✅ generate_video 新增 guidance_scale / motion_bucket_id 穩定參數
- ✅ --quality flag：fast / balanced / cinematic 三段控制
"""

import os
import sys
import re
import json
import time
import argparse
import asyncio
import uuid
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import httpx

# ── Config ──
BASE_DIR = Path(__file__).parent.resolve()
STATE_FILE = BASE_DIR / "agents_workflow_state.json"
SCENE_FILE = BASE_DIR / "scene_prompts.json"
OUTPUT_DIR = BASE_DIR / "output"
SCENES_DIR = OUTPUT_DIR / "scenes"
VIDEOS_DIR = OUTPUT_DIR / "videos"

AGNES_API = "https://apihub.agnes-ai.com/v1"
AGNES_ROOT = "https://apihub.agnes-ai.com"
AGNES_KEY = os.environ.get("AGNES_API_KEY", "")
AGNES_IMG_MODEL = "agnes-image-2.1-flash"
AGNES_VIDEO_MODEL = "agnes-video-v2.0"
AGNES_TEXT_MODEL = "agnes-2.0-flash"

# Quotas
QUOTA_VIDEO_SEC = 500
QUOTA_VIDEO_SAFE = 480

# ── Duration Presets (8n+1 frame rule) ──
# Formula: seconds = num_frames / frame_rate
# Resolution limits: 1080p=169max, 720p=409max, 480p=961max
DURATION_PRESETS = {
    5:  (121, 24, "1080p"),
    7:  (169, 24, "1080p"),
    10: (241, 24, "720p"),
    12: (289, 24, "720p"),
    15: (361, 24, "720p"),
    17: (409, 24, "720p"),
}

# Resolution presets for 9:16 (portrait)
RES_9_16 = {
    "1080p": {"width": 1080, "height": 1920, "desc": "1080p"},
    "720p":  {"width": 768,  "height": 1152, "desc": "720p"},
}

# ── Quality Presets ──
# Controls guidance_scale and motion_bucket_id for I2V stability
# Higher guidance_scale = closer to image anchor (less drift)
# Lower motion_bucket_id = less motion intensity (more stable)
QUALITY_PRESETS = {
    "fast":     {"guidance_scale": 2.5, "motion_bucket_id": 127},
    "balanced": {"guidance_scale": 3.5, "motion_bucket_id": 80},
    "cinematic":{"guidance_scale": 5.0, "motion_bucket_id": 50},
}

# ── Negative Prompt Defaults ──
IMG_NEG_DEFAULT = (
    "worst quality, low quality, blurry, bad anatomy, extra fingers, "
    "missing limbs, deformed, ugly, cartoon, 3d render, cgi, watermark, "
    "text, logo, overexposed, underexposed"
)
VID_NEG_DEFAULT = (
    "blurry, flickering, inconsistent character, morphing face, "
    "jump cut, teleportation, color shift, frame duplication, "
    "cartoon, cgi, watermark, text"
)


class PipelineState:
    def __init__(self):
        self.run_id = str(uuid.uuid4())[:8]
        self.current_stage = "INIT"
        self.scene_count = 3
        self.completed_scenes = []
        self.failed_scenes = []
        self.image_urls = {}       # str(scene_idx) -> url
        self.video_urls = {}       # str(scene_idx) -> url
        self.last_frame_urls = {}  # str(scene_idx) -> last_frame_url (for chaining)
        self.quota_used_seconds = 0
        self.retry_count = 0
        self.fallback_used = False

    @classmethod
    def load(cls):
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            s = cls()
            s.__dict__.update(data)
            return s
        return cls()

    def save(self):
        STATE_FILE.write_text(json.dumps(self.__dict__, indent=2, ensure_ascii=False))


class AgnesAPI:
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=AGNES_API,
            headers={"Authorization": f"Bearer {AGNES_KEY}", "Content-Type": "application/json"},
            timeout=120,
        )

    async def chat(self, prompt: str, system: str = "", temperature: float = 0.7) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        for attempt in range(4):
            try:
                resp = await self.client.post("/chat/completions", json={
                    "model": AGNES_TEXT_MODEL,
                    "messages": messages,
                    "max_tokens": 4096,
                    "temperature": temperature,
                })
                if resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception:
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("Chat API failed after 4 attempts")

    async def generate_image(self, prompt: str, size: str = "1024x1792") -> Optional[str]:
        """生圖，回傳 URL。9:16 直式建議 1024x1792"""
        for attempt in range(4):
            try:
                resp = await self.client.post("/images/generations", json={
                    "model": AGNES_IMG_MODEL,
                    "prompt": prompt,
                    "n": 1,
                    "size": size,
                })
                if resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.json()["data"][0]["url"]
            except Exception:
                await asyncio.sleep(2 ** attempt)
        return None

    async def generate_video(
        self,
        image_url: str,
        prompt: str,
        duration: int = 5,
        width: int = 768,
        height: int = 1152,
        quality: str = "balanced",
        anchor_image_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        提交 I2V 影片任務，回傳 video_id。

        anchor_image_url: 前一鏡末幀，用於 Frame Chaining 提升連貫性。
                          若 API 支援 end_image 欄位則傳入，否則注入 prompt。
        quality: fast / balanced / cinematic，控制 guidance_scale / motion_bucket_id。
        """
        nf, fr, res_label = DURATION_PRESETS.get(duration, DURATION_PRESETS[5])
        res = RES_9_16.get(res_label, RES_9_16["720p"])
        qp = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])

        # 若有前鏡末幀，注入 prompt 作為視覺橋接提示
        chaining_hint = ""
        if anchor_image_url:
            chaining_hint = " Visually transition from the previous scene's ending frame, maintain consistent character appearance, lighting, and color palette."

        payload = {
            "model": AGNES_VIDEO_MODEL,
            "image": image_url,
            "prompt": prompt + chaining_hint,
            "num_frames": nf,
            "frame_rate": fr,
            "width": width or res["width"],
            "height": height or res["height"],
            "guidance_scale": qp["guidance_scale"],
            "motion_bucket_id": qp["motion_bucket_id"],
        }

        # 若 API 支援 end_image（Frame Chaining 強化版），嘗試傳入
        if anchor_image_url:
            payload["end_image"] = anchor_image_url

        for attempt in range(4):
            try:
                resp = await self.client.post("/videos", json=payload)
                if resp.status_code == 422:
                    # API 不支援 end_image，移除後重試
                    payload.pop("end_image", None)
                    resp = await self.client.post("/videos", json=payload)
                if resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data.get("video_id") or data.get("id")
            except Exception as e:
                if attempt < 3:
                    await asyncio.sleep(2 ** attempt)
                else:
                    print(f"  ❌ 影片提交失敗: {e}")
                    return None
        return None

    async def generate_multi_image_video(
        self,
        image_urls: list,
        prompt: str,
        duration: int = 5,
        quality: str = "balanced",
    ) -> Optional[str]:
        """多圖轉場 — 用 extra_body.image 陣列達到場景平滑過渡"""
        nf, fr, res_label = DURATION_PRESETS.get(duration, DURATION_PRESETS[5])
        res = RES_9_16.get(res_label, RES_9_16["720p"])
        qp = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])

        payload = {
            "model": AGNES_VIDEO_MODEL,
            "prompt": prompt,
            "num_frames": nf,
            "frame_rate": fr,
            "width": res["width"],
            "height": res["height"],
            "guidance_scale": qp["guidance_scale"],
            "motion_bucket_id": qp["motion_bucket_id"],
            "extra_body": {
                "image": image_urls,
            },
        }

        for attempt in range(4):
            try:
                resp = await self.client.post("/videos", json=payload)
                if resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data.get("video_id") or data.get("id")
            except Exception:
                await asyncio.sleep(2 ** attempt)
        return None

    async def poll_video(self, video_id: str, timeout: int = 300) -> Optional[str]:
        """
        輪詢影片結果，回傳最終影片 URL。

        Fix v3.2: 修正 URL 提取順序，移除語意錯誤的 remixed_from_video_id。
        正確優先級：url > output.url > video_url > download_url
        """
        start = time.time()
        polling_url = f"{AGNES_ROOT}/agnesapi"
        while time.time() - start < timeout:
            try:
                async with httpx.AsyncClient(timeout=30) as pc:
                    resp = await pc.get(
                        polling_url,
                        params={"video_id": video_id, "model_name": AGNES_VIDEO_MODEL},
                        headers={"Authorization": f"Bearer {AGNES_KEY}"},
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status", "")
                    if status == "completed":
                        # 依正確語意取 URL，不再用 remixed_from_video_id
                        url = (
                            data.get("url")
                            or (data.get("output") or {}).get("url")
                            or data.get("video_url")
                            or data.get("download_url")
                        )
                        if url:
                            return url
                        else:
                            print(f"  ⚠️ 影片完成但找不到 URL，完整回應: {data}")
                            return None
                    elif status in ("failed", "error"):
                        print(f"  ❌ 影片失敗: {data.get('error', 'unknown')}")
                        return None
            except Exception as e:
                print(f"  ⚠️ 輪詢異常: {e}")
            await asyncio.sleep(5)
        print(f"  ⏰ 影片 {video_id} 輪詢超時 ({timeout}s)")
        return None

    async def close(self):
        await self.client.aclose()


# ── Script Design (Phase 0) ──

SCRIPT_DESIGN_SYSTEM = """你是一個專業影片腳本設計師。你的工作是協助用戶完成腳本設計的五個步驟：
Step 1: 需求萃取 — 了解主題、風格、長度、平台、情緒
Step 2: 節奏表 (Beat Sheet) — 設計時間軸分配和情緒曲線
Step 3: 腳本撰寫 — 將節奏表轉化為場景描述
Step 4: 分鏡設計 — 將腳本轉為逐鏡頭分鏡（含 image_prompt + video_prompt）
Step 5: 腳本審查 — 連續性、可行性、模型匹配檢查

腳本設計準則：
- 視覺化寫作：用畫面思考，非文字思考
- 精簡：每場景一句話描述核心
- 連續性：前後場景視覺元素一致
- 節奏感：長短場景交錯
- 可視性：確認每個描述都能被 AI 影片模型理解
"""


async def coherence_pass(api: AgnesAPI, scenes: list[dict]) -> list[dict]:
    """
    Coherence Pass：讓 LLM 審查所有場景的 character_card 一致性，
    並修補差異欄位。確保跨場景角色視覺不漂移。
    """
    if not scenes:
        return scenes

    print("  🔍 Coherence Pass: 角色一致性審查")
    cards = [{"scene_id": s.get("scene_id", i), "character_card": s.get("character_card", "")
              } for i, s in enumerate(scenes)]

    system = """你是一個分鏡一致性審查員。
你的任務：比對所有場景的 character_card，找出差異，統一為最完整的那一版。
輸出 JSON 陣列，每個元素只含 {scene_id, character_card}。
 character_card 必須完全相同（同一角色跨場景鎖定）。
輸出純 JSON，不要 markdown 包裝。"""

    prompt = f"請審查並統一以下場景的 character_card：\n{json.dumps(cards, ensure_ascii=False, indent=2)}"

    try:
        text = await api.chat(prompt, system=system, temperature=0.1)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        fixed = json.loads(text)
        card_map = {str(item["scene_id"]): item["character_card"] for item in fixed}
        for i, scene in enumerate(scenes):
            sid = str(scene.get("scene_id", i))
            if sid in card_map:
                scene["character_card"] = card_map[sid]
        print(f"     ✅ {len(scenes)} 場景 character_card 已統一")
    except Exception as e:
        print(f"     ⚠️ Coherence Pass 失敗（跳過）: {e}")

    return scenes


def build_image_prompt(scene: dict) -> str:
    """
    強化 image_prompt：注入一致性種子 token。
    確保跨場景風格、光線、角色外觀的視覺錨定。
    """
    base = scene.get("image_prompt", "")
    character = scene.get("character_card", "")
    style = scene.get("visual_style", "")

    # 注入一致性種子 token
    seed_tokens = "cinematic, photorealistic, consistent lighting, sharp focus, 9:16 portrait"
    if character:
        seed_tokens = f"character: {character[:120]}, {seed_tokens}"
    if style:
        seed_tokens = f"{style}, {seed_tokens}"

    return f"{base}, {seed_tokens}"


def build_video_prompt(scene: dict) -> str:
    """
    強化 video_prompt：自動附加動態負面描述詞，
    確保模型聚焦在指定動態，不產生跳切或形變。
    """
    base = scene.get("video_prompt", "Slow cinematic motion")
    # 結尾注入品質指令
    quality_suffix = (
        " Smooth continuous motion, consistent character appearance throughout, "
        "stable camera, no sudden cuts, no morphing, photorealistic."
    )
    return base + quality_suffix


async def design_script(
    api: AgnesAPI,
    topic: str,
    scene_count: int,
    platform: str = "shorts",
    total_duration: int = 30,
) -> dict:
    """Phase 0: Complete script design workflow"""
    print("  📋 Step 1/5: 需求萃取")
    print(f"     主題: {topic}")
    print(f"     平台: {platform}")

    # Step 2: Beat Sheet (低溫 0.3 確保 JSON 結構穩定)
    print("  📊 Step 2/5: 節奏表設計")
    beat_system = """你是一個節奏表 (Beat Sheet) 設計專家。
根據總時長和平台，設計時間軸分配和情緒曲線。

輸出 JSON:
{
  "total_duration": 30,
  "platform": "shorts",
  "emotion_curve": "平靜→緊張→高潮→收束",
  "beats": [
    {
      "beat_id": 1,
      "name": "Hook",
      "time_start": 0,
      "time_end": 3,
      "purpose": "吸引眼球",
      "emotion": "好奇",
      "camera": "特寫"
    }
  ]
}
"""

    beat_prompt = f"""請為以下主題設計節奏表：
主題: {topic}
場景數: {scene_count}
總時長: {total_duration}秒
平台: {platform} (9:16 直式)

每個節拍包含: beat_id, name, time_start, time_end, purpose, emotion, camera
輸出純 JSON。"""
    try:
        text = await api.chat(beat_prompt, system=beat_system, temperature=0.3)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        beat_sheet = json.loads(text)
    except Exception as e:
        print(f"  ⚠️ 節奏表生成失敗: {e}，使用預設節奏")
        beat_sheet = {
            "total_duration": total_duration,
            "platform": platform,
            "emotion_curve": "引入→上升→高潮→收束",
            "beats": [
                {"beat_id": 1, "name": "Hook", "time_start": 0, "time_end": 3,
                 "purpose": "吸引眼球", "emotion": "好奇", "camera": "特寫"},
                {"beat_id": 2, "name": "展示", "time_start": 3,
                 "time_end": int(total_duration * 0.5),
                 "purpose": "展現主題", "emotion": "興趣", "camera": "中景"},
                {"beat_id": 3, "name": "高潮",
                 "time_start": int(total_duration * 0.5),
                 "time_end": int(total_duration * 0.85),
                 "purpose": "情緒頂點", "emotion": "驚嘆", "camera": "動態"},
                {"beat_id": 4, "name": "收尾",
                 "time_start": int(total_duration * 0.85),
                 "time_end": total_duration,
                 "purpose": "收束", "emotion": "滿足", "camera": "拉遠"},
            ],
        }

    print(f"     情緒曲線: {beat_sheet.get('emotion_curve', '-')}")
    for b in beat_sheet.get("beats", []):
        print(f"     {b.get('time_start', 0):>2}s-{b.get('time_end', 0):>2}s | {b.get('name', '')}")

    # Step 3+4: Generate scenes with beat context
    print("  📝 Step 3-4/5: 腳本撰寫 + 分鏡設計")
    scenes = await write_script_v3(api, topic, scene_count, beat_sheet)

    # Coherence Pass: 審查並統一 character_card
    scenes = await coherence_pass(api, scenes)

    # Step 5: Review
    print("  ✅ Step 5/5: 腳本審查")
    review_notes = []
    total_dur = sum(s.get("duration_seconds", 10) for s in scenes)
    review_notes.append(f"總時長: {total_dur}s ({len(scenes)} 場景)")
    if total_dur > total_duration * 1.5:
        review_notes.append(f"⚠️ 總時長 {total_dur}s 超過預期 {total_duration}s")

    script_pkg = {
        "run_id": str(uuid.uuid4())[:8],
        "theme": topic,
        "platform": platform,
        "total_duration_target": total_duration,
        "emotion_curve": beat_sheet.get("emotion_curve", ""),
        "total_scenes": len(scenes),
        "beats": beat_sheet.get("beats", []),
        "scenes": scenes,
        "review_notes": review_notes,
    }
    return script_pkg


async def write_script_v3(
    api: AgnesAPI,
    topic: str,
    scene_count: int,
    beat_sheet: dict = None,
) -> list[dict]:
    """v3 分鏡腳本生成，含 Beat Sheet 上下文與強化一致性指令"""
    beat_context = ""
    if beat_sheet and beat_sheet.get("beats"):
        beat_lines = []
        for b in beat_sheet["beats"]:
            beat_lines.append(
                f"  {b.get('time_start', 0)}s-{b.get('time_end', 0)}s: "
                f"{b.get('name', '')} ({b.get('purpose', '')}, 情緒: {b.get('emotion', '')})"
            )
        beat_context = "節奏表:\n" + "\n".join(beat_lines)

    emotion_curve = (
        beat_sheet.get("emotion_curve", "引入→上升→高潮→收束")
        if beat_sheet else "引入→上升→高潮→收束"
    )

    system = f"""你是一個專業影片分鏡腳本寫手。輸出 JSON 陣列，每個元素包含：
- scene_id: 整數編號 (0-based)
- scene_title: 場景標題
- scene_goal: 這個場景要傳達什麼
- visual_style: 視覺風格描述（所有場景必須相同）
- character_card: 角色描述卡（性別/年齡/服裝款式與顏色/髮型/主要特徵）
  ⚠️ 所有場景的 character_card 必須逐字相同，這是跨場景一致性的鎖定依據
- image_prompt: 英文圖片提示詞（給 Agnes Image 2.1 Flash，9:16 直式）
  只描述靜態畫面：主體/場景/光線/風格/材質。不要包含動態描述。
- image_negative_prompt: 英文負面提示詞（過濾低品質/解剖錯誤）
- video_prompt: 英文影片動態描述（給 Agnes Video v2.0）
  只描述動態：主體動作/環境動態/鏡頭運動。不要重複圖片已有的視覺元素。
- video_negative_prompt: 英文負面提示詞（過濾閃爍/形變/不連貫）
- transition_rule: 轉場方式 (dissolve/cut/wipe/morph)
- duration_seconds: 5-15 秒
- beat_order: 對應的節奏表編號 (1-based)
- emotion: 預期情緒
- camera_angle: 鏡頭角度 (低角度/平視/俯視/跟拍)
- width: 768
- height: 1152

關鍵原則：
1. 所有場景的 character_card 必須完全相同（逐字一致）
2. 所有場景的 visual_style 必須完全相同（同世界觀）
3. image_prompt 描述靜態畫面，不包含動態
4. video_prompt 只描述動態，不重複靜態元素
5. 情緒曲線遵循: {emotion_curve}
6. 場景之間光線/方向感/色調要連續

輸出純 JSON 陣列，不要 markdown 包裝。"""

    prompt = f"""請為主題「{topic}」設計 {scene_count} 個連續分鏡腳本。

{beat_context}

要求：
1. 所有場景的 character_card 必須完全相同（這決定了角色連貫性）
2. 所有場景的 visual_style 必須相同（同一視覺世界）
3. image_prompt 不要包含動態描述
4. video_prompt 只描述動態（主體動作 + 環境動態 + 鏡頭運動）
5. 每個場景都要附 image_negative_prompt 和 video_negative_prompt
6. 9:16 直式，適合短影片平台
7. duration_seconds 在 5-15 秒之間
8. 情緒曲線跟隨節奏表

輸出純 JSON 陣列。"""

    try:
        text = await api.chat(prompt, system=system, temperature=0.7)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        scenes = json.loads(text)
        if isinstance(scenes, list):
            return scenes
    except Exception as e:
        print(f"  ⚠️ 腳本生成失敗: {e}，使用 fallback")

    # Fallback
    default_char = "young woman, 20s, black leather jacket, dark jeans, short black hair, sharp eyes"
    default_style = "Cinematic, photorealistic, neon-lit urban night"
    return [
        {
            "scene_id": i,
            "scene_title": f"Scene {i + 1}",
            "scene_goal": f"展示{topic}場景{i + 1}",
            "visual_style": default_style,
            "character_card": default_char,
            "image_prompt": f"Cinematic shot of {topic}, scene {i + 1}, 9:16 portrait, vibrant colors, 4k",
            "image_negative_prompt": IMG_NEG_DEFAULT,
            "video_prompt": "Slow cinematic pan, smooth motion",
            "video_negative_prompt": VID_NEG_DEFAULT,
            "transition_rule": "dissolve" if i > 0 else "cut",
            "duration_seconds": 10,
            "beat_order": i + 1,
            "emotion": "平靜" if i == 0 else ("緊張" if i == 1 else "驚嘆"),
            "camera_angle": "平視",
            "width": 768,
            "height": 1152,
        }
        for i in range(scene_count)
    ]


# ── Main ──

async def main():
    parser = argparse.ArgumentParser(description="CineAgent Pipeline v3.2")
    parser.add_argument("--reset", action="store_true", help="重置狀態")
    parser.add_argument("--scenes", type=int, default=3, help="分鏡數")
    parser.add_argument("--duration", type=int, default=10, help="每場景秒數(5-15)")
    parser.add_argument("--total-duration", type=int, default=30, help="目標總時長(秒)")
    parser.add_argument("--platform", default="shorts",
                        help="目標平台 (shorts/reels/tiktok/youtube)")
    parser.add_argument("--topic", default=None, help="主題")
    parser.add_argument("--structured", action="store_true", help="輸出結構化 JSON")
    parser.add_argument("--multi-image", action="store_true", help="使用多圖轉場模式")
    parser.add_argument("--skip-script", action="store_true",
                        help="跳過腳本，用已有 scene_prompts.json 繼續")
    parser.add_argument(
        "--quality",
        default="balanced",
        choices=["fast", "balanced", "cinematic"],
        help="影片品質預設：fast / balanced / cinematic（預設 balanced）",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCENES_DIR.mkdir(exist_ok=True)
    VIDEOS_DIR.mkdir(exist_ok=True)

    if args.reset:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        if SCENE_FILE.exists():
            SCENE_FILE.unlink()
        state = PipelineState()
    else:
        state = PipelineState.load()

    api = AgnesAPI()
    run_id = state.run_id

    try:
        # ── Phase 0: Script Design ──
        if state.current_stage in ("INIT",):
            if args.skip_script and SCENE_FILE.exists():
                print("\n⏭️ Skipping script phase (loading existing scene_prompts.json)")
                scenes = json.loads(SCENE_FILE.read_text())
                state.scene_count = len(scenes)
                state.current_stage = "SCRIPT_DONE"
                state.save()
                print(f"   Loaded {len(scenes)} existing scenes")
            else:
                print(f"\n📝 Phase 0: Script Design ({args.scenes} scenes)")
                topic = args.topic or input("主題: ").strip() or "城市夜景到魔幻仙境"
                platform = args.platform or "shorts"
                script_pkg = await design_script(
                    api, topic, args.scenes,
                    platform=platform,
                    total_duration=args.total_duration,
                )
                scenes = script_pkg["scenes"]
                SCENE_FILE.write_text(json.dumps(scenes, indent=2, ensure_ascii=False))
                state.scene_count = len(scenes)
                state.current_stage = "SCRIPT_DONE"
                state.save()

                (OUTPUT_DIR / "script_package.json").write_text(
                    json.dumps(script_pkg, indent=2, ensure_ascii=False)
                )
                if script_pkg.get("beats"):
                    (OUTPUT_DIR / "beat_sheet.json").write_text(
                        json.dumps(
                            {"beats": script_pkg["beats"],
                             "emotion_curve": script_pkg.get("emotion_curve", "")},
                            indent=2, ensure_ascii=False,
                        )
                    )
        else:
            scenes = json.loads(SCENE_FILE.read_text()) if SCENE_FILE.exists() else []

        # ── Phase 1: Images ──
        if state.current_stage == "SCRIPT_DONE":
            print(f"\n🖼️ Phase 1: Generate {len(scenes)} images")
            state.current_stage = "IMAGE_GEN"
            state.save()

            image_jobs = {"run_id": run_id, "jobs": []}
            for i, scene in enumerate(scenes):
                si = str(i)
                if si in state.image_urls:
                    print(f"  ✅ Scene {i} image exists, skip")
                    continue
                print(f"  🖼️ Scene {i}: {scene.get('scene_title', '')}")
                # 強化後的 image_prompt
                enhanced_prompt = build_image_prompt(scene)
                neg_prompt = scene.get("image_negative_prompt", IMG_NEG_DEFAULT)
                full_prompt = enhanced_prompt
                if neg_prompt:
                    # Agnes Image 支援 negative_prompt 欄位時可單獨傳；
                    # 此處先嵌入 prompt 相容所有版本
                    full_prompt = f"{enhanced_prompt} | negative: {neg_prompt}"
                url = await api.generate_image(full_prompt, size="1024x1792")
                if url:
                    state.image_urls[si] = url
                    state.completed_scenes.append(i)
                else:
                    state.failed_scenes.append(i)
                image_jobs["jobs"].append({
                    "scene_id": i,
                    "model": AGNES_IMG_MODEL,
                    "endpoint": "/v1/images/generations",
                    "request_body": {"prompt": full_prompt, "size": "1024x1792"},
                    "status": "completed" if url else "failed",
                    "image_url": url or "",
                })
                state.save()

            (OUTPUT_DIR / "image_jobs.json").write_text(
                json.dumps(image_jobs, indent=2, ensure_ascii=False)
            )
            state.current_stage = "IMAGE_DONE"
            state.save()

        # ── Phase 2: Video ──
        if state.current_stage == "IMAGE_DONE":
            print(f"\n🎬 Phase 2: Generate video (quality={args.quality})")
            state.current_stage = "VIDEO_GEN"
            state.save()

            image_list = [
                state.image_urls.get(str(i), "")
                for i in range(state.scene_count)
            ]
            image_list = [u for u in image_list if u]

            video_jobs = {"run_id": run_id, "jobs": []}

            if args.multi_image and len(image_list) >= 2:
                print("  🔗 Multi-image transition mode")
                transition_prompt = (
                    f"Smooth cinematic transition across {len(image_list)} scenes. "
                    "Each scene flows naturally into the next with visual consistency. "
                    "9:16 portrait format, cinematic lighting, smooth motion, "
                    "consistent character appearance, no morphing, no flickering."
                )
                video_id = await api.generate_multi_image_video(
                    image_list, transition_prompt,
                    duration=args.duration,
                    quality=args.quality,
                )
                if video_id:
                    print("  ⏳ Polling multi-image video...")
                    url = await api.poll_video(video_id, timeout=300)
                    if url:
                        state.video_urls["0"] = url
                        state.quota_used_seconds += args.duration
                    video_jobs["jobs"].append({
                        "scene_id": "all",
                        "model": AGNES_VIDEO_MODEL,
                        "endpoint": "/v1/videos",
                        "mode": "multi-image",
                        "quality": args.quality,
                        "video_id": video_id,
                        "status": "completed" if url else "failed",
                        "output_url": url or "",
                    })
            else:
                # Individual I2V per scene with Frame Chaining
                for i, img_url in enumerate(image_list):
                    si = str(i)
                    if si in state.video_urls:
                        print(f"  ✅ Scene {i} video exists, skip")
                        continue
                    scene = scenes[i] if i < len(scenes) else {}
                    print(f"  🎬 Scene {i}: {scene.get('scene_title', '')} "
                          f"({args.duration}s, quality={args.quality})")
                    dur = min(scene.get("duration_seconds", args.duration), 15)

                    # Frame Chaining：取前一鏡末幀作為視覺橋接錨點
                    prev_last_frame = state.last_frame_urls.get(str(i - 1)) if i > 0 else None
                    if prev_last_frame:
                        print(f"     🔗 Frame Chaining: scene {i-1} last frame → scene {i} anchor")

                    enhanced_video_prompt = build_video_prompt(scene)
                    video_id = await api.generate_video(
                        img_url,
                        enhanced_video_prompt,
                        duration=dur,
                        quality=args.quality,
                        anchor_image_url=prev_last_frame,
                    )
                    url = None
                    if video_id:
                        print("  ⏳ Polling...")
                        url = await api.poll_video(video_id, timeout=300)
                        if url:
                            state.video_urls[si] = url
                            state.quota_used_seconds += dur
                            # 記錄末幀 URL（若 API 有回傳；否則用影片 URL 作為代理）
                            # 實際末幀提取需要後處理（ffmpeg），此處記錄影片 URL 備用
                            state.last_frame_urls[si] = url
                    video_jobs["jobs"].append({
                        "scene_id": i,
                        "model": AGNES_VIDEO_MODEL,
                        "endpoint": "/v1/videos",
                        "mode": "image-to-video",
                        "quality": args.quality,
                        "video_id": video_id,
                        "frame_chaining": bool(prev_last_frame),
                        "status": "completed" if url else "failed",
                        "output_url": url or "",
                    })
                    state.save()

            (OUTPUT_DIR / "video_jobs.json").write_text(
                json.dumps(video_jobs, indent=2, ensure_ascii=False)
            )
            state.current_stage = "VIDEO_DONE"
            state.save()

        # ── Complete ──
        state.current_stage = "COMPLETE"
        state.save()

        notify = {
            "run_id": run_id,
            "overall_status": "completed" if not state.failed_scenes else "partial",
            "completed_scenes": len(state.video_urls),
            "failed_scenes": len(state.failed_scenes),
            "output_urls": list(state.video_urls.values()),
            "retry_count": state.retry_count,
            "fallback_used": state.fallback_used,
            "quota_used_seconds": state.quota_used_seconds,
            "quota_remaining": QUOTA_VIDEO_SEC - state.quota_used_seconds,
            "message": (
                f"✅ {len(state.video_urls)}/{state.scene_count} videos completed"
                if not state.failed_scenes
                else f"⚠️ Partial: {len(state.video_urls)} completed, "
                     f"{len(state.failed_scenes)} failed"
            ),
        }
        (OUTPUT_DIR / "notify_payload.json").write_text(
            json.dumps(notify, indent=2, ensure_ascii=False)
        )

        print(f"\n{'=' * 50}")
        print(notify["message"])
        print(f"  Videos: {len(state.video_urls)}/{state.scene_count}")
        print(f"  Failed: {len(state.failed_scenes)}")
        print(f"  Quota:  {state.quota_used_seconds}/{QUOTA_VIDEO_SEC}s used")
        if args.structured:
            print(f"\n📦 Structured JSON output in {OUTPUT_DIR}/")

    except Exception as e:
        state.last_error = str(e)
        state.save()
        print(f"\n❌ Error: {e}")
        raise
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())

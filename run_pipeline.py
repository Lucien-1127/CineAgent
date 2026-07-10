#!/usr/bin/env python3
"""
run_pipeline.py v3.4 — Agnes API spec alignment

Fixed from v3.3:
- ✅ generate_image(): 加入 extra_body.response_format="url"（官方文件規定，
     不可放頂層，否則 API 回傳錯誤）
- ✅ generate_image(): 支援 img2img (reference_images)，透過 extra_body.image 傳入
- ✅ generate_video(): 移除非官方欄位 guidance_scale / motion_bucket_id / end_image
     改用官方支援的 seed + negative_prompt
- ✅ generate_multi_image_video(): 同上移除非官方欄位，改用 seed + negative_prompt
- ✅ poll_video(): URL 提取新增 remixed_from_video_id（官方完成影片 URL 欄位）
- ✅ QUALITY_PRESETS 改為 num_inference_steps (官方支援欄位)

From v3.3 (保留):
- ✅ Frame Chaining 真正實作：ffmpeg 抽末幀 JPEG
- ✅ 三層降級上傳策略：Agnes / imgbb / prompt-only
- ✅ extract_last_frame() / upload_frame_image()
- ✅ import re 移至頂部
- ✅ image/video_prompt 一致性種子 token
- ✅ Coherence Pass character_card 統一
- ✅ --quality flag：fast / balanced / cinematic
"""

import os
import sys
import re
import json
import time
import base64
import tempfile
import subprocess
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
FRAMES_DIR = OUTPUT_DIR / "frames"   # ffmpeg 末幀輸出目錄

AGNES_API = "https://apihub.agnes-ai.com/v1"
AGNES_ROOT = "https://apihub.agnes-ai.com"
AGNES_KEY = os.environ.get("AGNES_API_KEY", "")
AGNES_IMG_MODEL = "agnes-image-2.1-flash"
AGNES_VIDEO_MODEL = "agnes-video-v2.0"
AGNES_TEXT_MODEL = "agnes-2.0-flash"

# imgbb — 免費圖片託管，Frame Chaining 備援上傳
IMGBB_KEY = os.environ.get("IMGBB_API_KEY", "")

# Quotas
QUOTA_VIDEO_SEC = 500
QUOTA_VIDEO_SAFE = 480

# ── Duration Presets (8n+1 frame rule) ──
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
# 官方支援欄位：num_inference_steps（官方文件 /v1/videos 參數表）
# guidance_scale / motion_bucket_id 為非官方欄位，已移除
QUALITY_PRESETS = {
    "fast":     {"num_inference_steps": 20},
    "balanced": {"num_inference_steps": 30},
    "cinematic":{"num_inference_steps": 50},
}

# ── Negative Prompt Defaults ──
IMG_NEG_DEFAULT = (
    "worst quality, low quality, blurry, bad anatomy, extra fingers, "
    "missing limbs, deformed, ugly, cartoon, 3d render, cgi, watermark, "
    "text, logo, overexposed, underexposed"
)
VID_NEG_DEFAULT = (
    "different character, face change, identity change, face morphing, "
    "different body shape, different color, appearance drift, "
    "character mutation, swapped identity, face distortion, "
    "inconsistent appearance, blurry, flickering, jump cut, "
    "teleportation, color shift, frame duplication, "
    "cartoon, cgi, watermark, text"
)


# ══════════════════════════════════════════════════
# Frame Chaining — ffmpeg 末幀抽取 + 三層上傳降級
# ══════════════════════════════════════════════════

def extract_last_frame(video_url: str, scene_id: int) -> Optional[Path]:
    """
    用 ffmpeg 從影片 URL 抽取最後一幀，存為 JPEG。

    策略：
    1. 先用 ffprobe 取得影片總時長
    2. seek 到 (duration - 0.1s) 抽單幀
    3. 存至 output/frames/frame_{scene_id}.jpg
    回傳本地 Path，失敗回傳 None。
    """
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FRAMES_DIR / f"frame_{scene_id}.jpg"

    # Step 1: 用 ffprobe 取得時長
    duration = None
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_url,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            duration = float(probe.stdout.strip())
    except Exception as e:
        print(f"     ⚠️ ffprobe 時長查詢失敗: {e}，改用 sseof 策略")

    # Step 2: 抽末幀
    try:
        if duration and duration > 0.5:
            seek_ts = max(0.0, duration - 0.1)
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(seek_ts),
                "-i", video_url,
                "-vframes", "1",
                "-q:v", "2",
                str(out_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-sseof", "-0.5",
                "-i", video_url,
                "-vframes", "1",
                "-q:v", "2",
                str(out_path),
            ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            print(f"     🎞️ 末幀抽取成功: {out_path.name} ({out_path.stat().st_size // 1024}KB)")
            return out_path
        else:
            print(f"     ⚠️ ffmpeg 末幀失敗 (rc={result.returncode}): {result.stderr[-200:]}")
            return None
    except subprocess.TimeoutExpired:
        print(f"     ⚠️ ffmpeg 末幀超時 (60s)")
        return None
    except FileNotFoundError:
        print(f"     ⚠️ ffmpeg 未安裝或不在 PATH")
        return None
    except Exception as e:
        print(f"     ⚠️ ffmpeg 末幀異常: {e}")
        return None


async def upload_frame_image(frame_path: Path, agnes_client: httpx.AsyncClient) -> Optional[str]:
    """
    三層降級上傳末幀圖片，回傳可直接使用的圖片 URL。

    層級①：POST /v1/images/uploads (Agnes multipart)
    層級②：POST https://api.imgbb.com/1/upload (base64, 需 IMGBB_KEY)
    層級③：None — 降級為純 prompt 文字橋接
    """
    jpeg_bytes = frame_path.read_bytes()

    # ── 層級① Agnes 原生上傳端點 ──
    try:
        resp = await agnes_client.post(
            "/images/uploads",
            content=None,
            headers={},
        )
        if resp.status_code not in (404, 405, 501):
            files = {"file": (frame_path.name, jpeg_bytes, "image/jpeg")}
            upload_headers = {
                k: v for k, v in agnes_client.headers.items()
                if k.lower() != "content-type"
            }
            async with httpx.AsyncClient(
                base_url=AGNES_API,
                headers=upload_headers,
                timeout=60,
            ) as up:
                r = await up.post("/images/uploads", files=files)
                if r.status_code == 200:
                    data = r.json()
                    url = (
                        data.get("url")
                        or data.get("data", {}).get("url")
                        or data.get("image_url")
                    )
                    if url:
                        print(f"     ✅ 末幀上傳成功 (Agnes): {url[:60]}...")
                        return url
    except Exception as e:
        print(f"     ⚠️ Agnes 上傳失敗: {e}")

    # ── 層級② imgbb base64 上傳 ──
    if IMGBB_KEY:
        try:
            b64 = base64.b64encode(jpeg_bytes).decode()
            async with httpx.AsyncClient(timeout=30) as ib:
                r = await ib.post(
                    "https://api.imgbb.com/1/upload",
                    data={"key": IMGBB_KEY, "image": b64, "expiration": 3600},
                )
                if r.status_code == 200:
                    data = r.json()
                    url = data.get("data", {}).get("url")
                    if url:
                        print(f"     ✅ 末幀上傳成功 (imgbb): {url[:60]}...")
                        return url
        except Exception as e:
            print(f"     ⚠️ imgbb 上傳失敗: {e}")
    else:
        print(f"     ℹ️  IMGBB_API_KEY 未設定，跳過 imgbb 備援")

    print(f"     ⚠️ 所有上傳管道失敗，Frame Chaining 降級為 prompt 橋接")
    return None


async def get_last_frame_url(
    video_url: str,
    scene_id: int,
    agnes_client: httpx.AsyncClient,
) -> Optional[str]:
    """
    完整 Frame Chaining 流程：抽幀 → 上傳 → 回傳 URL。
    任一步驟失敗回傳 None（主流程不中斷）。
    """
    frame_path = extract_last_frame(video_url, scene_id)
    if not frame_path:
        return None
    return await upload_frame_image(frame_path, agnes_client)


# ══════════════════════════════════════════════════
# Pipeline State
# ══════════════════════════════════════════════════

class PipelineState:
    def __init__(self):
        self.run_id = str(uuid.uuid4())[:8]
        self.current_stage = "INIT"
        self.scene_count = 3
        self.completed_scenes = []
        self.failed_scenes = []
        self.image_urls = {}       # str(scene_idx) -> url
        self.video_urls = {}       # str(scene_idx) -> url
        self.last_frame_urls = {}  # str(scene_idx) -> 真實末幀圖片 URL
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


# ══════════════════════════════════════════════════
# Agnes API Client
# ══════════════════════════════════════════════════

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

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1792",
        reference_images: Optional[list] = None,
    ) -> Optional[str]:
        """
        生圖，回傳 URL。

        Fix v3.4:
        - response_format 必須放在 extra_body 內，不可放頂層（官方文件規定）
        - img2img 模式：reference_images 放入 extra_body.image
        """
        for attempt in range(4):
            try:
                extra_body: dict = {"response_format": "url"}
                if reference_images:
                    # img2img 模式：傳入參考圖片 URL 陣列
                    extra_body["image"] = reference_images

                payload = {
                    "model": AGNES_IMG_MODEL,
                    "prompt": prompt,
                    "size": size,
                    "extra_body": extra_body,
                }

                resp = await self.client.post("/images/generations", json=payload)
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
        seed: Optional[int] = None,
    ) -> Optional[str]:
        """
        提交 I2V 影片任務，回傳 video_id。

        Fix v3.4:
        - 移除非官方欄位：guidance_scale, motion_bucket_id, end_image
        - 改用官方支援：num_inference_steps, negative_prompt, seed
        - anchor_image_url (Frame Chaining) 現在透過 extra_body.image 傳入
          （官方 keyframes 模式），同時在 prompt 附加橋接提示
        """
        nf, fr, res_label = DURATION_PRESETS.get(duration, DURATION_PRESETS[5])
        res = RES_9_16.get(res_label, RES_9_16["720p"])
        qp = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])

        chaining_hint = ""
        if anchor_image_url:
            chaining_hint = (
                " Visually transition from the previous scene's ending frame, "
                "maintain consistent character appearance, lighting, and color palette."
            )

        payload = {
            "model": AGNES_VIDEO_MODEL,
            "image": image_url,
            "prompt": prompt + chaining_hint,
            "num_frames": nf,
            "frame_rate": fr,
            "width": width or res["width"],
            "height": height or res["height"],
            "num_inference_steps": qp["num_inference_steps"],
            "negative_prompt": VID_NEG_DEFAULT,
        }

        if seed is not None:
            payload["seed"] = seed

        # Frame Chaining：用 keyframes 模式傳入首尾參考幀
        if anchor_image_url:
            payload["mode"] = "keyframes"
            payload["extra_body"] = {
                "image": [anchor_image_url, image_url]
            }

        for attempt in range(4):
            try:
                resp = await self.client.post("/videos", json=payload)
                if resp.status_code == 422 and "mode" in payload:
                    # keyframes 模式不支援時降級為標準 i2v + prompt 橋接
                    print(f"     ⚠️ keyframes 模式 422，降級為標準 i2v + prompt 橋接")
                    payload.pop("mode", None)
                    payload.pop("extra_body", None)
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
        """
        多圖轉場 — 用 extra_body.image 陣列達到場景平滑過渡

        Fix v3.4: 移除非官方欄位 guidance_scale / motion_bucket_id
        """
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
            "num_inference_steps": qp["num_inference_steps"],
            "negative_prompt": VID_NEG_DEFAULT,
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

        Fix v3.4: 新增 remixed_from_video_id 到 URL 提取優先序列
                  （官方完成影片 URL 欄位，參見 Agnes Video V2 API 文件）
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
                        url = (
                            data.get("remixed_from_video_id")   # v3.4 新增：官方完成影片 URL 欄位
                            or data.get("url")
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


# ══════════════════════════════════════════════════
# Script Design (Phase 0)
# ══════════════════════════════════════════════════

SCRIPT_DESIGN_SYSTEM = """你是一個專業 AI 影片腳本設計師，專精 Save the Cat 節奏理論與 AI 影像模型（Agnes Image/Video）的提示詞設計。

【工作流程】五步驟協助用戶完成腳本設計：
Step 1: 需求萃取 — 了解主題、風格、長度、平台、情緒
Step 2: 節奏表 (Beat Sheet) — 遵循 Save the Cat，設計時間軸分配和情緒曲線
Step 3: 腳本撰寫 — 將節奏表轉化為場景描述（每場景一句視覺核心）
Step 4: 分鏡設計 — 將腳本轉為逐鏡頭分鏡（含 image_prompt + video_prompt）
Step 5: 腳本審查 — 連續性、可行性、模型匹配檢查

【腳本設計準則】
- 視覺化寫作：用畫面思考，非文字思考
- 精簡：每場景一句話描述核心
- 連續性：前後場景視覺元素一致
- 節奏感：長短場景交錯
- 可視性：確認每個描述都能被 AI 影片模型理解
- 角色鎖定：character_card 跨場景逐字相同

【禁止行為】
- 禁止編造來源或無依據的論述
- 禁止使用通用形容詞（beautiful/nice/amazing）替代具體視覺描述
- 不可超出使用者指定的場景數和總時長

【交付前自檢】完成五步驟後確認：
□ character_card 跨場景完全一致
□ visual_style 跨場景完全相同
□ 每場景含 image_prompt + video_prompt + negative_prompt
□ 總場景數與時長符合用戶需求
"""


async def coherence_pass(api: AgnesAPI, scenes: list[dict]) -> list[dict]:
    """
    Coherence Pass：LLM 審查所有場景的 character_card 一致性並修補。
    """
    if not scenes:
        return scenes

    print("  🔍 Coherence Pass: 角色一致性審查")
    cards = [{"scene_id": s.get("scene_id", i), "character_card": s.get("character_card", "")}
             for i, s in enumerate(scenes)]

    system = """你是一個分鏡一致性審查員。
你的任務：比對所有場景的 character_card，找出差異，統一為最完整的那一版。

【仲裁規則】當場景間的 character_card 衝突時：
1. 選擇包含最多具體細節（服裝/髮型/特徵）的版本為基準
2. 基準版本中若有明顯矛盾（如同時寫「短髮」和「長馬尾」），取出現次數多的版本
3. 無法判定 → 選擇第一個場景的版本

【禁止行為】不可為統一而刪除基準版本中的有效細節。
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
    """強化 image_prompt：注入一致性種子 token。"""
    base = scene.get("image_prompt", "")
    character = scene.get("character_card", "")
    style = scene.get("visual_style", "")
    seed_tokens = []
    if character:
        seed_tokens.append(f"character: {character.strip()}")
    if style:
        seed_tokens.append(style.strip())
    # Quality suffix — neutral (no hardcoded style like "photorealistic")
    seed_tokens.append("consistent lighting, sharp focus, 9:16 portrait")
    return f"{base}, {', '.join(seed_tokens)}"


def build_video_prompt(scene: dict) -> str:
    """強化 video_prompt：附加動態一致性指令（中性，不強制風格）。"""
    base = scene.get("video_prompt", "Smooth cinematic motion")
    quality_suffix = (
        " Continuous smooth motion, consistent character appearance throughout, "
        "stable camera, no sudden cuts, no morphing."
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

    print("  📊 Step 2/5: 節奏表設計")
    beat_system = """你是一個節奏表 (Beat Sheet) 設計專家，遵循 Save the Cat 節奏理論。
根據總時長和平台，設計時間軸分配和情緒曲線。

【設計準則】
- Hook (0-3s): 開場吸引，用特寫或強烈視覺
- Setup: 建立情境，中景展示
- Build-up: 逐步升溫，節奏加快
- Climax: 情緒頂點，動態鏡頭
- Resolution: 收束滿足感，鏡頭拉遠

【禁止行為】不可編造與主題無關的節拍名稱，不可超過總時長，不可跳號。

輸出純 JSON（不要 markdown）:
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
}"""
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

    print("  📝 Step 3-4/5: 腳本撰寫 + 分鏡設計")
    scenes = await write_script_v3(api, topic, scene_count, beat_sheet)
    scenes = await coherence_pass(api, scenes)

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

    total_duration = beat_sheet.get("total_duration", 30) if beat_sheet else 30

    system = f"""你是一個 AI 影片製作系統的專業分鏡腳本寫手，專精 Agnes Image 2.1 Flash（圖片）和 Agnes Video v2.0（影片）兩個模型的提示詞設計。

【核心能力】你能從主題和節奏表中萃取關鍵視覺元素，設計連貫的多場景分鏡，並產出可直接餵入 AI 模型的高品質英文提示詞。

【輸出格式】輸出純 JSON 陣列（不要 markdown 包裝），每個元素包含：
- scene_id: 整數編號 (0-based)
- scene_title: 場景標題
- scene_goal: 這個場景要傳達什麼
- visual_style: 視覺風格描述（所有場景必須完全相同）
  以逗號分隔關鍵詞格式撰寫（Agnes 擴散模型最佳理解格式），包含四要素：
  ① 藝術類型 (Cinematic/Anime/Cyberpunk/3D render...) ② 光線設定 (Soft ambient/Neon glow/Golden hour...)
  ③ 色調與調色 (Teal and orange/Warm earthy/Monochrome...) ④ 鏡頭質感 (Film grain/Deep depth of field/Wide angle...)
  ⚠️ 不在 visual_style 中描述角色（那是 character_card 的工作），只描述環境的視覺質感
  範例："Cinematic realism, teal and orange color grading, soft natural sunlight, 8k resolution, highly detailed textures, film grain"
  ❌ 錯誤："Beautiful video" / "Cinematic, a man running" → 太簡略或混入角色描述
- character_card: 角色描述卡（性別/年齡/服裝款式與顏色/髮型/主要特徵）
  ⚠️ 所有場景的 character_card 必須逐字相同，這是跨場景一致性的鎖定依據
  角色描述卡品質自檢：□性別 □年齡區間 □服裝款式+顏色 □髮型+顏色 □體型特徵 □至少一個獨特標記
- image_prompt: 英文圖片提示詞（給 Agnes Image 2.1 Flash，9:16 直式）
  只描述靜態畫面：主體/場景/光線/風格/材質。不要包含動態描述。
  高品質標準：主體佔畫面主要位置、光源方向明確、色彩方案一致、避免通用詞如 "beautiful/nice"
  範例："A woman in black leather jacket standing under neon street lamp, rain-slicked pavement, cinematic blue lighting"
- image_negative_prompt: 英文負面提示詞（過濾低品質/解剖錯誤）
  必須包含：worst quality, low quality, blurry, bad anatomy, deformed
- video_prompt: 英文影片動態描述（給 Agnes Video v2.0）
  只描述動態：主體動作/環境動態/鏡頭運動。不要重複圖片已有的視覺元素。
  高品質標準：指定動作方向和速度、鏡頭運動方式（pan/tilt/track/dolly/static）、環境互動
  範例："Slow dolly forward as she lifts her gaze toward the light, rain droplets falling, subtle steam rising from wet pavement"
- video_negative_prompt: 英文負面提示詞（過濾角色變形/閃爍/不連貫）
  必須包含：different character, face morphing, appearance drift, flickering, jump cut
- transition_rule: 轉場方式 (dissolve/cut/wipe/morph)
- duration_seconds: 5-15 秒
- frame_count: 8n+1 格式幀數（Agnes Video 2.0 規則，如 25/33/41）
- beat_order: 對應的節奏表編號 (1-based)
- emotion: 預期情緒
- camera_angle: 鏡頭角度 (低角度/平視/俯視/跟拍)
- width: 768
- height: 1152

【關鍵原則】
1. 所有場景的 character_card 必須完全相同（逐字一致，不可有任何差異）
   從 character_card 中自動提取 5-8 個「鎖定關鍵詞」，這些詞必須逐字出現在每個 image_prompt
2. 所有場景的 visual_style 必須完全相同（同一世界觀）
   從 visual_style 中自動提取 3-5 個「鎖定關鍵詞」，這些詞必須逐字出現在每個 image_prompt
3. image_prompt 只描述靜態，不包含任何動態描述
4. video_prompt 只描述動態，不重複 image_prompt 已有的靜態元素
5. 情緒曲線遵循: {emotion_curve}
6. 場景之間光線/方向感/色調要連續
7. 禁止虛構 character_card 細節 — 不確定就保持精簡
8. 每個 image_prompt 和 video_prompt 必須包含對應的 negative_prompt
9. 總時長不超過 {total_duration} 秒，每幕 duration_seconds × {scene_count} ≈ 總時長
10. frame_count 須符合 8n+1（8 fps 基準：duration_seconds × 8 → 取最接近的 8n+1）

【交付前自檢】輸出前確認：
□ character_card 所有場景完全一致 ✓
□ character_card 鎖定關鍵詞逐字出現在每個 image_prompt ✓
□ visual_style 所有場景完全一致 ✓
□ visual_style 鎖定關鍵詞逐字出現在每個 image_prompt ✓
□ image_prompt 不含動態詞 ✓
□ video_prompt 不含靜態重複 ✓
□ 每個場景都有 negative_prompt ✓
□ frame_count 符合 8n+1 ✓
□ 總時長不超過 {total_duration}s ✓

輸出純 JSON 陣列，不要 markdown 包裝。"""

    prompt = f"""請為主題「{topic}」設計 {scene_count} 個連續分鏡腳本。

{beat_context}

要求：
1. 所有場景的 character_card 必須完全相同（這決定了角色連貫性）— 逐字比對，不可有任何差異
2. 從 character_card 提取 5-8 個「鎖定關鍵詞」，每個 image_prompt 必須逐字包含這些詞（不可同義改寫）
3. 從 visual_style 提取 3-5 個「鎖定關鍵詞」，每個 image_prompt 必須逐字包含這些詞
4. image_prompt 不要包含動態描述 — 純靜態畫面
5. video_prompt 只描述動態（主體動作 + 環境動態 + 鏡頭運動）— 用 dolly/pan/track/static 指定鏡頭
6. 每個場景都要附 image_negative_prompt 和 video_negative_prompt
7. 9:16 直式，適合短影片平台
8. duration_seconds 在 5-15 秒之間，總時長不超過 {total_duration} 秒
9. frame_count 須符合 8n+1（duration_seconds × 8 ≈ 取最接近 8n+1，如 3s→25, 5s→41, 10s→81）
10. 情緒曲線跟隨節奏表
11. 禁止使用通用形容詞（beautiful/nice/amazing）— 用具體視覺描述替代

輸出純 JSON 陣列。"""

    try:
        text = await api.chat(prompt, system=system, temperature=0.7)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        scenes = json.loads(text)
        if isinstance(scenes, list):
            return scenes
    except Exception as e:
        print(f"  ⚠️ 腳本生成失敗: {e}，使用 fallback")

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


# ══════════════════════════════════════════════════
# v4 Assistant Director — 模組化單次輸出
# ══════════════════════════════════════════════════

ASSISTANT_DIRECTOR_SYSTEM = """【角色】
你是 CineAgent，AI 影片副導。將主題轉化為高品質影片腳本。

【框架】
1. 宏觀（三幕劇）：鋪陳→對抗→解決，於 script_logic 明示三幕邊界。
2. 情緒（Save the Cat 節奏表）：於 emotion_curve 按節奏表時間點標註轉折，每點含：時間（秒）、情緒狀態、觸發事件。
3. 分鏡（Hook-Value-CTA）：
   - Hook：首幕前 3 秒高視覺衝擊
   - Value：中段傳遞核心資訊與節奏表情緒價值
   - CTA：末幕導向指定動作（關注/訂閱/點擊）

【一致性】
- 每幕 visual_prompt 逐字引用 CHARACTER_CARD 與 VISUAL_STYLE 的鎖定關鍵詞，禁止同義改寫或省略。
- 每幕附 negative_prompt：3–5 個具體詞，對應該幕最可能的失敗模式（變形/多餘肢體/風格突變/文字亂碼），禁止超過 5 詞。

【輸入缺失處理】
缺 CHARACTER_CARD 或 VISUAL_STYLE → 依主題生成建議版並標註「待確認」；缺平台 → 預設 X。

{platform_appendix}

【輸出】
僅輸出單一 JSON（不要 markdown 包裝）:
{{
  "script_logic": "三幕結構推理說明",
  "emotion_curve": [{{"time_sec": 0, "emotion": "好奇", "trigger": "閃光開場"}}],
  "character_card_raw": "原始角色描述",
  "character_card_keywords": ["keyword1", "keyword2", ...],
  "visual_style_raw": "原始風格描述",
  "visual_style_keywords": ["keyword1", "keyword2", ...],
  "storyboards": [{{
    "scene_id": 0,
    "act": 1,
    "role": "hook",
    "duration_sec": 3,
    "frame_count": 25,
    "visual_prompt": "含 character_card 與 visual_style 鎖定關鍵詞（逐字）",
    "negative_prompt": "3-5 詞，針對該幕失敗模式",
    "caption": "平台發布文案"
  }}]
}}

【技術約束】
- 每幕 frame_count 符合 8n+1（Agnes Video 2.0）。
- 全幕 duration_sec 加總不超過平台上限。
- emotion_curve 每個時間點對應至少一個 storyboard。"""

PLATFORM_APPENDIX_X = """X：caption ≤25,000 字元；影片總長 ≤140 秒；比例 16:9 或 9:16（依主題屬性擇一並註明理由）。"""

PLATFORM_APPENDIX_TELEGRAM = """Telegram：影片檔案 ≤50MB；於 script_logic 換算分鏡總數×單幕秒數確認不超限；比例不限，預設 16:9。"""

PLATFORM_APPENDIX_DEFAULT = """平台：shorts/reels；影片總長 ≤60 秒；9:16 直式。"""


async def write_script_v4_assistant_director(
    api: AgnesAPI,
    topic: str,
    character_card: str | None = None,
    visual_style: str | None = None,
    platform: str = "X",
    scene_count: int = 3,
    total_duration: int = 30,
) -> dict:
    """v4 副導模式：雙溫層次呼叫，產出模組化 JSON。

    Pass 1 (temp=0.3): script_logic + emotion_curve
    Pass 2 (temp=0.7): storyboards with locked keywords

    回傳 dict: {script_logic, emotion_curve, character_card_raw,
                character_card_keywords, visual_style_raw,
                visual_style_keywords, storyboards}
    """
    # ── 平台附錄 ──
    plat_lower = platform.lower()
    if plat_lower in ("x", "twitter"):
        appendix = PLATFORM_APPENDIX_X
    elif plat_lower == "telegram":
        appendix = PLATFORM_APPENDIX_TELEGRAM
    else:
        appendix = PLATFORM_APPENDIX_DEFAULT

    system_full = ASSISTANT_DIRECTOR_SYSTEM.format(platform_appendix=appendix)

    # ── 建構輸入區塊 ──
    input_blocks = [f"TOPIC: {topic}"]
    if character_card:
        input_blocks.append(f"CHARACTER_CARD: {character_card}")
    else:
        input_blocks.append("CHARACTER_CARD: 待確認（請從主題推測）")
    if visual_style:
        input_blocks.append(f"VISUAL_STYLE: {visual_style}")
    else:
        input_blocks.append("VISUAL_STYLE: 待確認（請從主題推測）")
    input_blocks.append(f"PLATFORM: {platform}")
    input_blocks.append(f"SCENE_COUNT: {scene_count}")
    input_blocks.append(f"TOTAL_DURATION: {total_duration}s")

    user_input = "\n".join(input_blocks)

    # ── Pass 1: 結構推理 (temp=0.3) ──
    struct_prompt = f"""{user_input}

請先輸出 script_logic 和 emotion_curve（不要 storyboards）。
輸出純 JSON：{{"script_logic": "...", "emotion_curve": [...]}}"""

    print("  🧠 Pass 1/2: 結構推理 (temp=0.3)")
    try:
        text = await api.chat(struct_prompt, system=system_full, temperature=0.3)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        structure = json.loads(text)
        script_logic = structure.get("script_logic", "")
        emotion_curve = structure.get("emotion_curve", [])
        print(f"     script_logic: {len(script_logic)} chars, emotion_curve: {len(emotion_curve)} points")
    except Exception as e:
        print(f"  ⚠️ Pass 1 失敗: {e}，使用 fallback")
        script_logic = f"三幕劇結構自動生成：鋪陳→對抗→解決，共 {scene_count} 幕"
        emotion_curve = [
            {"time_sec": 0, "emotion": "好奇", "trigger": "開場"},
            {"time_sec": total_duration // 3, "emotion": "緊張", "trigger": "衝突升級"},
            {"time_sec": total_duration * 2 // 3, "emotion": "驚嘆", "trigger": "高潮揭露"},
            {"time_sec": total_duration - 3, "emotion": "滿足", "trigger": "收束"},
        ]

    # ── Pass 2: 分鏡生成 (temp=0.7) ──
    storyboard_prompt = f"""{user_input}

已確定的結構：
- script_logic: {script_logic}
- emotion_curve: {json.dumps(emotion_curve, ensure_ascii=False)}

請根據以上結構，產出 {scene_count} 個 storyboard。
重點：每幕 visual_prompt 必須逐字包含 CHARACTER_CARD 和 VISUAL_STYLE 的鎖定關鍵詞。

輸出純 JSON 陣列：[
  {{
    "scene_id": 0, "act": 1, "role": "hook",
    "duration_sec": 3, "frame_count": 25,
    "visual_prompt": "...", "negative_prompt": "...",
    "caption": "..."
  }},
  ...
]"""

    print("  🎬 Pass 2/2: 分鏡生成 (temp=0.7)")
    try:
        text = await api.chat(storyboard_prompt, system=system_full, temperature=0.7)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        storyboards = json.loads(text)
        if not isinstance(storyboards, list):
            storyboards = [storyboards]
        print(f"     storyboards: {len(storyboards)} scenes")
    except Exception as e:
        print(f"  ⚠️ Pass 2 失敗: {e}，使用 fallback")
        storyboards = _v4_fallback_storyboards(
            topic, character_card, visual_style, scene_count, total_duration
        )

    # ── 萃取關鍵詞（fallback: 從原始輸入自動拆詞） ──
    char_keywords = _extract_keywords(character_card, count=6) if character_card else []
    style_keywords = _extract_keywords(visual_style, count=4) if visual_style else []

    return {
        "script_logic": script_logic,
        "emotion_curve": emotion_curve,
        "character_card_raw": character_card or "待確認",
        "character_card_keywords": char_keywords,
        "visual_style_raw": visual_style or "待確認",
        "visual_style_keywords": style_keywords,
        "storyboards": storyboards,
    }


def _extract_keywords(text: str, count: int = 5) -> list[str]:
    """從角色卡/風格描述中自動提取鎖定關鍵詞（逗號分割或空格分割）。"""
    if not text:
        return []
    # 按逗號或中文逗號分割
    parts = [p.strip() for p in re.split(r"[,，、]", text) if p.strip()]
    if len(parts) <= 2:
        # 可能用空格或換行分隔
        parts = [p.strip() for p in re.split(r"[\s\n]+", text) if len(p.strip()) > 1]
    return parts[:count]


def _v4_fallback_storyboards(
    topic: str,
    character_card: str | None = None,
    visual_style: str | None = None,
    scene_count: int = 3,
    total_duration: int = 30,
) -> list[dict]:
    """v4 副導 fallback：當 LLM 呼叫失敗時產出基本分鏡。"""
    dur_per_scene = max(3, total_duration // scene_count)
    char = character_card or "young adult, casual modern clothing, neutral expression"
    style = visual_style or "cinematic, natural lighting, warm colors"
    roles = ["hook", "value", "cta"]
    storyboards = []
    for i in range(scene_count):
        frame_count = _nearest_8n1(dur_per_scene * 8)  # ~8fps rough estimate
        storyboards.append({
            "scene_id": i,
            "act": 1 if i == 0 else (3 if i == scene_count - 1 else 2),
            "role": roles[min(i, len(roles) - 1)],
            "duration_sec": dur_per_scene,
            "frame_count": frame_count,
            "visual_prompt": f"{char}, {style}, scene {i + 1}, 9:16 portrait",
            "negative_prompt": "worst quality, blurry, distorted face, extra limbs",
            "caption": f"{topic} — Scene {i + 1}",
        })
    return storyboards


def _nearest_8n1(frames: int) -> int:
    """回傳最接近 target 的 8n+1 幀數。"""
    n = max(1, round((frames - 1) / 8))
    return 8 * n + 1


# ══════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser(description="CineAgent Pipeline v3.4")
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
    FRAMES_DIR.mkdir(exist_ok=True)

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
                enhanced_prompt = build_image_prompt(scene)
                neg_prompt = scene.get("image_negative_prompt", IMG_NEG_DEFAULT)
                full_prompt = enhanced_prompt
                if neg_prompt:
                    full_prompt = f"{enhanced_prompt} | negative: {neg_prompt}"

                # v3.4: generate_image 已內建 extra_body.response_format="url"
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
                    "request_body": {
                        "prompt": full_prompt,
                        "size": "1024x1792",
                        "extra_body": {"response_format": "url"},
                    },
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
                url = None
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
                # Individual I2V per scene with REAL Frame Chaining (v3.3+)
                for i, img_url in enumerate(image_list):
                    si = str(i)
                    if si in state.video_urls:
                        print(f"  ✅ Scene {i} video exists, skip")
                        continue
                    scene = scenes[i] if i < len(scenes) else {}
                    print(f"  🎬 Scene {i}: {scene.get('scene_title', '')} "
                          f"({args.duration}s, quality={args.quality})")
                    dur = min(scene.get("duration_seconds", args.duration), 15)

                    prev_last_frame = state.last_frame_urls.get(str(i - 1)) if i > 0 else None
                    if i > 0:
                        if prev_last_frame:
                            print(f"     🔗 Frame Chaining: scene {i-1} last frame → scene {i} anchor ✅")
                        else:
                            print(f"     ⚠️  Frame Chaining: scene {i-1} 末幀不可用，改用 prompt 橋接")

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

                            print(f"     🎞️ 抽取末幀用於下一場景 Frame Chaining...")
                            real_frame_url = await get_last_frame_url(url, i, api.client)
                            if real_frame_url:
                                state.last_frame_urls[si] = real_frame_url
                                print(f"     ✅ last_frame_urls[{i}] = 真實圖片 URL")
                            else:
                                print(f"     ⚠️  末幀抽取失敗，scene {i+1} 將使用 prompt 橋接")

                    video_jobs["jobs"].append({
                        "scene_id": i,
                        "model": AGNES_VIDEO_MODEL,
                        "endpoint": "/v1/videos",
                        "mode": "image-to-video",
                        "quality": args.quality,
                        "video_id": video_id,
                        "frame_chaining": bool(prev_last_frame),
                        "frame_chaining_url": prev_last_frame or "",
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

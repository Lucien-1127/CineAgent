# 🎬 CineAgent v4 — 鎖定角色、反推節奏、自動驗收的影片流水線

一張角色母圖 + 一段參考影片，產出一條 30 秒、接縫對得起來、節奏不單調、而且每一鏡都經過
VLM 評分驗收的短片。

v3 是單檔（`archive/run_pipeline_v34.py`，Agnes API）。v4 重寫成 `cineagent/` package，
針對兩個實測痛點：

| 痛點 | 舊版行為 | v4 解法 |
|------|----------|---------|
| **圖片跟影片沒有鎖定**（角色不一致、首尾幀沒鎖好） | 每鏡用「差不多」的文字重述角色；末幀抽出來上傳失敗就退回 prompt 橋接 | 角色母圖 + `[CHAR:id]` 逐字身份塊 + **首尾幀同檔鎖定**（shot k 的末幀檔 = shot k+1 的首幀檔） |
| **劇情太單調** | 一次 LLM 自由發揮，常出現 5 個同樣的 static 中景 | 參考影片反推實測節奏 → 每鏡綁 `function`/`turn` → 單調稽核 → LLM 修復 → **deterministic 多樣性強制** |

---

## 三層閉環架構

```
            ┌─────────────────────────────────────────────────────────┐
            │ A. 逆向工程  reverse.py                                 │
            │ ffmpeg 剪點偵測 → 分段抽幀(0.1/0.5/0.9) → VLM 逐鏡描述    │
            │ 產出 BeatSheet：鏡長、景別、運鏡、能量曲線、加速比        │
            └──────────────────────────┬──────────────────────────────┘
                                       │ 節奏骨架（可選）
            ┌──────────────────────────▼──────────────────────────────┐
            │ B. 角色錨定  anchor.py + planner.py                     │
            │ CharacterAnchor（canonical/服裝/特徵/色票）             │
            │ 母圖一張 → 逐鏡 bridge still → 首尾幀鏈接               │
            │ bridge / carry / loop 三種模式，seam 全部可驗證          │
            └──────────────────────────┬──────────────────────────────┘
                                       │ chain: first_frame / last_frame
            ┌──────────────────────────▼──────────────────────────────┐
            │ C. 生成 + 守門  pipeline.py + gate.py + prompts.py      │
            │ image_prompt（只寫靜態）／motion_prompt（只寫運鏡）      │
            │ 渲染 → 抽 3 幀 → VLM rubric 五軸 → accept/retry/escalate│
            │ retry 依失敗軸套用具體修正，預算用完就 escalate         │
            └─────────────────────────────────────────────────────────┘
```

### A. 影片逆向工程（Beat Sheet 反推）

`ffmpeg select='gt(scene,0.30)'` 抓剪點 → 每段抽 start/mid/end 三幀 → VLM 依固定 rubric
回 JSON（framing / camera_move / speed / lens / lighting / palette / setting / subject /
action / energy / cut_out）→ 組成 `BeatSheet` 並算實測節奏：

```
5 shots / 30.0s / 5.0 cuts per 30s / acceleration 2.0
move mix: {'dolly-in': 1, 'crane-down': 1, 'static': 1, 'orbit': 1, 'dolly-out': 1}
energy curve: [2, 3, 4, 5, 3]
```

`acceleration` = 前 1/3 平均鏡長 ÷ 後 1/3 平均鏡長；>1 代表越剪越快。

### B. 角色錨定 + 首尾幀鎖定

* `CharacterAnchor.identity_block()` 產生一行身份塊，**逐字**注入每鏡 image prompt，
  並帶 `[CHAR:lead]` 標記；缺錨記的 prompt 會被 `validate_split()` 擋下。
* `plan_chain()` 三種模式：

| 模式 | 做法 | 接縫 | 成本 |
|------|------|------|------|
| `bridge` | 事前生好每鏡 still，shot k 末幀 = shot k+1 首幀（同一檔案） | 像素級相同 | 每鏡一張圖 |
| `carry` | 渲染後用 ffmpeg 抽末幀餵下一鏡首幀 | 抽幀品質 | 0 張圖 |
| `loop` | 同 bridge，最後一鏡收在開場 still，可無縫循環 | 像素級 + 首尾閉合 | 每鏡一張 |

`seam_report()` / `verify_chain()` 是硬檢查：`seam 2→3: b.png != c.png` 會直接列為 problem。

### C. Prompt 分離 + VLM 守門員

* `build_image_prompt()` 只准寫**畫面裡有什麼**；出現 dolly/pan/zoom 等動態詞即判違規。
* `build_motion_prompt()` 只准寫**畫面怎麼變**；重述 `wears / lighting / palette` 也判違規。
  `split` 值約 0.63–0.70，代表 6-7 成 token 花在靜態（圖負責長相、影片負責動作）。
* `gate.py` 五軸：identity 0.40 / wardrobe 0.20 / palette 0.15 / framing 0.15 / motion 0.10，
  門檻 `min_total=0.82`、`min_identity=0.80`；不過就 retry（最多 2 次）後 escalate。
* **沒有人物的鏡頭不判 identity**：`shot_has_character()` 從 subject/action/setting 判讀
  （`no people`、`empty alley`、`無人`…），命中就把 identity/wardrobe 權重移除後重新歸一，
  只在 palette/framing/motion 上評分——否則空景永遠卡在 identity 0 分而無限 retry。
* `report.json` 另有 `accepted` 與 `rejected_shots`：concat 出 `final.mp4` **不等於**驗收通過，
  被 retry/escalate 的鏡頭會列在 `rejected_shots`，SUMMARY 也會寫 `accepted: False`。
* VLM／抽幀／評分資料不完整時走 fail-closed，標記 `escalate`，不因驗收服務失效而付費重試。
* motion 與 framing 各有 70 分獨立底線。完整鏡頭、最終媒體探測與目標時長（±0.5 秒）均須通過；缺片不合片。
* `accepted` 只代表技術鏡頭與媒體驗收。`delivery_status=REVIEW_REQUIRED` 仍需敘事、表演、聲音與內容對齊的人工驗收；目前沒有自動口型同步驗收。未通過技術驗收的 `run` 回傳非零退出碼。

---

## 快速開始

```bash
# 0) 檢查金鑰、模型目錄、ffmpeg
python3 run_pipeline.py doctor

# 1) 反推參考影片節奏（可選但強烈建議）
python3 run_pipeline.py reverse --video reference.mp4 --out output/ref_beat.json

# 2) 只規劃 + 離線稽核（不花錢；--live 才會真的呼叫 LLM）
python3 run_pipeline.py plan --brief "外送員在雨夜發現包裹裡是別人的記憶" \
        --duration 30 --shots 5 --aspect 9:16 --live
python3 run_pipeline.py check --plan output/<run>/plan.json

# 3) 全流程（會花錢：生圖 + 生影片）
python3 run_pipeline.py run --brief "..." --duration 30 --shots 5 --chain-mode bridge

# 4) 最便宜的一鏡煙霧測試（1 圖 + 5 秒影片 + 1 次 VLM 驗收）
python3 run_pipeline.py smoke --out output/smoke

# 5) 生圖額度不可用時的降級路線：已批准母圖 + carry 鏈接
python3 run_pipeline.py run --brief "..." --shots 3 --chain-mode carry \
        --anchor-image approved.jpg --video-tier budget
```

---

## 模型路由（2026-11-19 實測）

`doctor` 會即時重驗；下表為本次實測結果。

| 能力 | 首選 | 實測狀態 |
|------|------|----------|
| **Image-to-Video** | `orcarouter:kling/kling-v3-omni`（FLF + `image_list` + 15s + 4K） | ✅ 送單成功，成品 5.04s / 1080×1920 / 9.2MB |
| 影片 fallback | `kling/kling-v3`、`kling-video-o1`、`kling-v2-6`、`minimax/minimax-h3` | ✅ 目錄可見 |
| 影片（OpenRouter） | `google/veo-3.1`、`kwaivgi/kling-v3.0-pro`、`alibaba/wan-3.0` | ⚠️ 走 `/api/v1/videos`，需餘額 |
| **Image-Gen** | `orcarouter:google/imagen-4.0-generate-001` | ❌ 三支 imagen 實測全 `503 upstream_unavailable` |
| Image-Gen fallback | `openrouter:google/gemini-3.1-flash-image` 等 | ❌ `402` 需 ≥ $1 餘額 |
| **VLM 驗收** | `openrouter:anthropic/claude-sonnet-5.5` | ✅ 實測回傳五軸分數（0.831 accept） |
| VLM 便宜版 | `anthropic/claude-haiku-5.5`、`orcarouter/fusion`、`orcarouter/pod` | ✅ |
| LLM 規劃 | `openrouter:anthropic/claude-sonnet-5.5`、`orcarouter/fusion` | ✅ 實測產出 JSON 分鏡 |
| 便宜影片 | `kling/kling-3-turbo`（$0.112/次）、`kling-v2-5-turbo`、`kwaivgi/kling-v3.0-std`、`alibaba/wan-3.0` | ✅ 目錄可見 |

**使用者點名但實測不適用**：

* `tencent/hy4-preview`、`tencent/hy4`、`hy3` → 目錄 `endpoint_capabilities` 只有
  `chat_completions` / `openai_responses`，是**文字模型**，不是 image-to-video。
* `flux` 系列 → OrcaRouter 沒有；OpenRouter 只有 `black-forest-labs/flux-3-video`、
  `flux-video-edit`、`flux-video-upscale`（**影片**用途），沒有 flux 生圖端點。
* 生圖目前唯一可用選項就是 imagen（503 中）與 OpenRouter 的 gemini/gpt-image（402 需餘額）。

時長會依模型自動對齊：Kling 2.x 只吃 5/10 秒、Kling 3.x 吃 3-15 秒、Veo 吃 4/6/8 秒；
送錯會回 `duration value '4' is invalid`，`routing.snap_duration()` 會在送單前先修正。

> **現況**：影片與 VLM 通了，生圖被上游 503／餘額 402 卡住。因此
> `--chain-mode carry --anchor-image <已批准母圖>` 是現在唯一能跑完整條片的路徑；
> 生圖恢復後 `bridge` 自動可用（`MultiImages` 依序試 imagen → gemini-image → gpt-image）。

**一次完整實跑（單鏡、carry、$0.112 模型）的誠實結果**：

```
plan 1 shot / 5.0s, gate retry 0.67 → 0.75 → 0.72, attempts=3
axes identity 68 / wardrobe 90 / palette 88 / framing 55 / motion 50
final.mp4 產出但 accepted: False
```

兩件事要分清：`final.mp4` 有產出（管線沒斷），但**驗收沒過**——VLM 判 framing/motion 太弱，
因為該次 prompt 要求 dolly-in、實際畫面幾乎沒推進。這是 gate 該做的事，不是 bug；
重跑時把 motion_prompt 寫成可觀測的位移（例如 `dolly in 2 m over 5 s, foreground parallax`）
或換 `kling-v3-omni` 的 `camera_control` 才會過。

---

## 產出結構

```
output/<run_id>/
├── plan.json       # BeatSheet（含 rhythm / boundaries）
├── anchor.json     # 角色錨定表（含母圖 sha256 前 16 碼）
├── chain.json      # 每鏡 first/last frame + seam 檢查
├── prompts.jsonl   # 每鏡 image_prompt / motion_prompt / 違規清單
├── stills/         # 母圖 + bridge still
├── shots/          # 每鏡 mp4（重試版 a0/a1/a2）
├── frames/         # gate 與 carry 用的抽幀
├── report.json     # audit / seams / 每鏡 gate 分數 / 重試次數
├── SUMMARY.txt     # 人看的摘要
└── final.mp4       # 拼接成品
```

---

## 專案結構

```
CineAgent/
├── run_pipeline.py              # CLI：doctor / reverse / check / smoke / plan / run
├── cineagent/
│   ├── beatsheet.py             # Shot / BeatSheet / Rhythm + enum 正規化
│   ├── reverse.py               # A：影片反推
│   ├── anchor.py                # B：角色錨定 + 首尾幀鏈
│   ├── planner.py               # B：分鏡規劃 + 單調稽核 + 多樣性強制
│   ├── prompts.py               # C：image/motion prompt 分離與驗證
│   ├── gate.py                  # C：VLM rubric + accept/retry/escalate
│   ├── routing.py               # 能力 → 模型路由（含即時目錄檢查）
│   ├── providers.py             # stdlib HTTP：Kling / OpenRouter / 生圖 / VLM
│   ├── media.py                 # ffmpeg：探測、抽幀、剪點、拼接
│   └── pipeline.py              # 三層編排
├── tests/test_offline.py        # 31 個離線測試（不耗網路、不花錢）
├── archive/run_pipeline_v34.py  # 舊版 Agnes 單檔流水線（保留對照）
├── docs/  references/  templates/
└── output/
```

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

---

## 參考與出處

* Kling 參數（`image` 首幀、`metadata.image_tail` 末幀、`image_list`、`video_list`）：
  <https://docs.orcarouter.ai/kling-video/overview>
* 剪點偵測：PySceneDetect（★5,585）<https://github.com/Breakthrough/PySceneDetect>
* 長影片連貫生成參考：FramePack（★17,369）、Wan2.2（★18,779）、LTX-Video（★11,439）、
  Open-Sora（★29,943）、VACE（★4,067）
* 首尾幀橋接：`roboticwink1/Anchor-Frame-Bridging-for-Coherent-First-Last-Frame-Video-Generation-AFB`
* 反推 prompt 社群 skill：`LunarXuan/video-prompt-reverse`（★72）、`imooooc/video-to-prompt`（★25）

---

## ⚙️ 硬體需求

| 項目 | 最低 | 建議 |
|------|------|------|
| CPU | 1 core | 2 core |
| RAM | 1 GB | 2 GB |
| 硬碟 | 10 GB | 20 GB |
| GPU | 不需要 | 不需要 |

生成全走雲端 API；本機只需 Python 3.10+ 與 ffmpeg。

## 📜 授權

MIT（見 LICENSE）。

---

**CineAgent v4** — 你的 AI 影片副導。🎬

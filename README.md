# 🎬 CineAgent

> **一鍵動畫腳本製作 — 從故事到影片，AI 幫你搞定。**

CineAgent 是你的 AI 影片副導。給他一個主題，他會自己完成腳本設計、圖片生成、影片製作，最後直接送到 Telegram 或 X（Twitter）。

```
你：幫我做一支「霓虹城市的雨夜」短影片
CineAgent：
  📋 腳本設計 → 🖼️ 圖片生成 → 🎬 影片製作 → 📤 平台送出
```

---

## 🚀 快速開始

```bash
# 安裝
pip install -r requirements.txt

# 一鍵執行
python run_pipeline.py --topic "春日櫻花城市" --platform shorts

# 完整控制
python run_pipeline.py \
  --topic "賽博朋克台北" \
  --scenes 5 \
  --total-duration 30 \
  --platform shorts \
  --multi-image
```

---

## 🏗️ 流水線架構

```
Phase 0：腳本設計（人機協作）
├─ Step 1: 需求萃取 — 你的主題是燃料
├─ Step 2: 節奏表 — 情緒曲線設計（Hook → 展示 → 高潮 → 收尾）
├─ Step 3: 腳本撰寫 — 用畫面思考，不是文字
├─ Step 4: 分鏡設計 — 逐鏡頭拆解：image_prompt + video_prompt
└─ Step 5: 腳本審查 — 連續性、一致性、負面提示詞檢查
       ↓
Phase 1：圖片生成
├─ 一般圖片 → Agnes Image 2.1 Flash（雲端 API）
├─ NSFW → 本地 SD Forge（DreamShaper 8 / RV V6）
├─ 每張圖都附加負面提示詞過濾
└─ character_card 鎖定角色跨場景一致
       ↓
Phase 2：影片製作
├─ Agnes Video 2.0（I2V 架構）
├─ 圖片鎖品質，提示詞只寫動態
├─ Frame Chaining：前一鏡末幀 = 下一鏡起點
└─ 自動附加影片負面提示詞（防 flickering / morphing）
       ↓
Phase 3：平台傳送
├─ Telegram：圖片 + 影片直接推送
└─ X（Twitter）：格式轉換 + Post API 自動發布
```

---

## 📐 模型參數

| 模型 | 用途 | Temperature / 等效參數 | 限制 |
|------|------|------------------------|------|
| Agnes 2.0 Flash | 腳本/推理 | 節奏表 0.3 / 分鏡 0.7 | 4,096 tokens |
| Agnes Image 2.1 Flash | 圖片生成 | 擴散模型（CFG 預設） | 4,000 張/日，1024x1792 max |
| Agnes Video 2.0 | 影片生成 | 擴散模型 | 500 秒/日，8n+1 幀規則 |
| SD Forge DS8 | NSFW 生圖 | CFG 7.0 / Steps 25 | 本機 VRAM 4GB |
| SD Forge RV V6 | NSFW 生圖 | CFG 5.0 / Steps 25 | 本機，需 VAE |

---

## ✍️ 寫作人格 × 腳本融合

CineAgent 不只是在產出 JSON——它用說故事的方式思考。

```
寫作人格要素        →  腳本中的應用
────────────────────────────────
角色性格（實戰派）   →  prompt 指令精準、不廢話
語氣（有溫度）       →  場景的情感曲線有層次
節奏（分鏡切換）     →  長短場景交錯，像剪輯節奏
視角（協作感）       →  你是導演，CineAgent 是副導
```

**技術文件用三幕劇結構寫，分鏡用 Hook-Value-CTA 框架產出，情緒曲線用 Save the Cat 節奏表控制。** 這就是寫作人格與腳本製作的融合點。

---

## 🐦 X（Twitter）整合

CineAgent 產出的內容可發布到 X 平台：

| 項目 | 規格 |
|------|------|
| 圖片尺寸 | 16:9 或 1:1，1600x900 最佳 |
| 影片長度 | 最長 140 秒（標準帳號） |
| 影片比例 | 16:9 / 9:16 皆可 |
| 文字限制 | 25,000 字元/篇 |
| 媒體數量 | 最多 4 張圖片或 1 部影片 |

**發布流程：** 產出 → 格式轉換 → 附加說明文 → X API → 時間線

### 平台規格比較

| 項目 | Telegram | X (Twitter) |
|------|----------|-------------|
| 圖片上限 | 10MB/張 | 5MB/張 |
| 影片上限 | 50MB | 512MB |
| 比例 | 不拘 | 16:9 / 1:1 最佳 |
| 互動性 | 頻道單向 | 留言/轉發/讚 |

---

## 🎯 一致性控制

| 面向 | 做法 |
|------|------|
| **角色** | character_card 鎖定性別/年齡/服裝/髮型/特徵 |
| **背景** | visual_style 跨場景統一色調/光線/風格 |
| **情緒** | emotion_curve 控制起承轉合 |
| **負面提示詞** | 圖片 + 影片自動附加過濾器 |

---

## 🔧 指令參數

```
--topic TEXT         主題描述（必要）
--scenes N           分鏡數（預設 3）
--duration N         每場景秒數 5-15（預設 10）
--total-duration N   目標總時長秒數（預設 30）
--platform TEXT      平台：shorts / reels / tiktok / youtube
--multi-image        多圖轉場模式
--structured         輸出結構化 JSON
--skip-script        跳過腳本，用已有 scene_prompts.json
--reset              重置狀態
```

---

## 📁 專案結構

```
CineAgent/
├── README.md                   # 本文件
├── AGENTS.md                   # Hermes 操作手冊
├── run_pipeline.py             # 主執行腳本 v3.1
├── requirements.txt            # 依賴
│
├── docs/                       # 完整文件
│   ├── pipeline-architecture.md
│   ├── script-design-guide.md
│   ├── image-generation.md
│   └── video-production.md
│
├── references/                 # 參考資料
│   ├── script-frameworks.md
│   ├── beat-sheet-templates.md
│   └── video-api-pitfalls.md
│
├── templates/                  # 模板
│   ├── script-template.json
│   ├── beat-sheet-template.md
│   └── storyboard-template.md
│
└── output/                     # 產出
    ├── scenes/                 # 各場景圖片
    └── videos/                 # 最終影片
```

---

## ⚙️ 硬體需求

| 項目 | 最低 | 建議 |
|------|------|------|
| CPU | 1 core | 2 core |
| RAM | 1 GB | 2 GB |
| 硬碟 | 10 GB | 20 GB |
| GPU | 不需要 | 不需要 |

> 所有圖片/影片生成走 Agnes API 雲端運算。本機只需 Python 執行環境 + 網路。

---

## 🏗️ 部署

CineAgent 可部署在 GCP e2-micro（$6/月），規格已驗證：

```bash
# GCP VM 初始化
gcloud compute instances create hermes-agent \
  --zone=us-west1-a \
  --machine-type=e2-micro \
  --image-family=ubuntu-2404-lts-amd64

# 安裝依賴
sudo apt-get install python3-pip git curl
git clone https://github.com/Lucien-1127/CineAgent.git
cd CineAgent && pip install -r requirements.txt

# 設定環境變數
export AGNES_API_KEY="your_key"
export TELEGRAM_BOT_TOKEN="your_token"

# 啟動
python run_pipeline.py --topic "你的主題"
```

---

## 📜 授權

MIT — 自由使用、修改、商用。

---

**CineAgent** — 你的 AI 影片副導。🎬

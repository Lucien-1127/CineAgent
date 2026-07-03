# 🎬 AI 媒體流水線 — AI Media Pipeline

**全自動化 AI 影音生產線**：腳本設計 → 圖片生成 → 影片製作，一鍵完成。

## 概觀

```
┌──────────────────────────────────────────────────────┐
│                   AI Media Pipeline                   │
├───────────────┬───────────────┬──────────────────────┤
│  Phase 1      │  Phase 2      │  Phase 3             │
│  腳本設計       │  圖片生成       │  影片製作              │
│               │               │                      │
│  · 需求訪談    │  · Agnes 2.1  │  · Agnes Video 2.0   │
│  · 腳本撰寫    │    Flash      │  · 單圖 I2V           │
│  · 節奏表     │  · SD Forge   │  · 多圖轉場            │
│  · 分鏡設計    │    (NSFW)     │  · Frame Chaining     │
│  · 腳本審查    │               │                      │
└───────────────┴───────────────┴──────────────────────┘
```

## 模型路由

| 階段 | 預設模型 | 降級方案 |
|------|----------|----------|
| 腳本生成 | Agnes 2.0 Flash | DeepSeek V4 |
| 一般圖片 (non-NSFW) | Agnes Image 2.1 Flash | — |
| NSFW 圖片 | 本地 SD Forge (DS8 / RV V6) | — |
| 影片生成 | Agnes Video 2.0 | — |

## 快速開始

```bash
# 安裝依賴
pip install -r requirements.txt

# 一鍵執行
python run_pipeline.py --topic "你的主題" --scenes 3

# 自訂參數
python run_pipeline.py --topic "霓虹城市" --scenes 5 --duration 10

# 多圖轉場（單次 API 完成場景過渡）
python run_pipeline.py --topic "主題" --multi-image

# 重置狀態
python run_pipeline.py --reset
```

## 專案結構

```
ai-media-pipeline/
├── README.md                    # 本文件
├── AGENTS.md                    # Hermes 操作手冊
├── run_pipeline.py              # 主執行腳本
├── requirements.txt             # 依賴
├── .gitignore
│
├── docs/                        # 文件
│   ├── pipeline-architecture.md # 流水線架構
│   ├── script-design-guide.md   # 腳本設計指南
│   ├── image-generation.md      # 圖片生成路由
│   └── video-production.md      # 影片製作
│
├── references/                  # 參考資料
│   ├── script-frameworks.md     # 腳本創作框架
│   ├── beat-sheet-templates.md  # 節奏表模板
│   └── video-api-pitfalls.md    # Video API 陷阱
│
├── templates/                   # 模板
│   ├── script-template.json     # 腳本 JSON 模板
│   ├── beat-sheet-template.md   # 節奏表模板
│   └── storyboard-template.md   # 分鏡表模板
│
└── output/                      # 產出
    ├── script_package.json
    ├── image_jobs.json
    ├── video_jobs.json
    ├── notify_payload.json
    ├── scenes/
    └── videos/
```

## 授權

MIT

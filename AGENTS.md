# AGENTS.md — CineAgent v4

Provider-neutral、shot-based、reference-first、audio-timeline-driven 的 AI 影片製作系統（v4）。狀態標示用 `implemented` / `experimental` / `planned` / `deprecated`。**文件不得超前實作**。

## 核心規則

1. **Agnes 已停用**：AgnesAPI 與 run_pipeline.py（v3）非 v4；僅作 migration 歷史保留。
2. **Provider 抽象化**：Pipeline 只碰 providers/base.py 與各 modality 介面；vendor payload 只在 adapter 內。
3. **Scene 與 Shot 分離**：Shot = 可獨立恢復的最小生成單位；Audio Master Timeline 定時長。
4. **Reference-first**：VisualBible 集中角色/場景/服裝/燈光/鏡頭語言；優先 reference image/video。

5. **Reuse before Generate**：Asset Library → Stock → Image+Motion → 避免不查庫就生昂貴影片。
6. **Durable / Idempotent**：GenerationJob 必存 remote_job_id；crash 後不誤標 COMPLETE；重送不重複計費建 job。
7. **文件不得超前實作**：只用四種狀態詞；通過測試後才標 implemented。
8. **錯誤分流**：用 providers/base.py 的 error taxonomy；不得以單一 except Exception 吞掉所有錯誤。

##已實作

- Canonical Domain Model（cineagent/domain/）.
- SQLite + WAL 持久層 + Cost Ledger（cineagent/storage/）.
- Script Engine（Planner→Hook→Writer→Critic→FactCheck→Storyboard，cineagent/creative/）.
- Audio-First Timeline + MasterTimeline + captions/SRT（orchestration/、media/）.
- Storyboard + VisualBible + PromptCompiler（vendor gate）.
- Asset Router（hash dedup/semantic reuse，cineagent/assets/）.
- Model Capability Router（providers/capability.py，僅 mock 註冊）.
- Image/Video/Audio/Text Provider 介面 + Mock（durable/idempotent，providers/）.
- FFmpegRenderer（組出可播放 MP4，《renderer/`）; RemotionRenderer=planned。
- TechnicalQA（ffprobe）; VisualQAProvider 介面 + Mock（真實模型 planned））.
- Publishers（YouTube/TikTok/Instagram/X/Telegram，皆 dry-run）.
- AnalyticsCollector + ContentLearningStore（min_samples gate，analytics/））.

- CI（.github/workflows/ci.yml：tests + secret scan）执 E2E smoke（tests/test_e2e_smoke.py））.

##測試

```bash
source .venv/bin/activate
python -m pytest -q
```

已驗證基線：56 測試全數通過。#所有 Provider 需有 Mock test。



##目錄

cineagent/   domain creative orchestration providers assets media qa publish analytics storage renderer
tests/   docs/   .github/workflows/ci.yml

##planned（未完成）

RemotionRenderer（Node 未接線）、真實 vendor adapters（Kling/Runway/Veo/Sora/Luma/OrcaRouter）、
真實 Publisher 發片 API（目前 dry-run）、真實 Visual QA 模型、真實 TTS（ElevenLabs/OpenAI/local）
+ forced alignment、Provider estimated_cost 真實價格註冊。以上完成並過測後才可改標 implemented。



##提交規範

- 每個 Phase 一個 commit，訊息 v4 Phase N: ...
- 不 push 至遠端，除非使用者明確授權
- 提交前確認無 venv / .env / secret 進 staged
```
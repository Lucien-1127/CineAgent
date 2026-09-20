# 生產模式 (production-modes)

狀態：`implemented`（列舉與決策定錨）；各模式完整 gate `planned`。

## draft — 快速預覽

- 低成本模型 / Stock / 既有 Library / still image + Ken Burns。
- 不產生多 candidate。
- 目的：快速看草稿。

## auto — 一般正式影片

- 以 Image-to-Video 為主。
- AI QA（Technical + Visual）。
- 失敗自動 repair / regenerate（只有低於 threshold 的 shot 重生，不整支重做）。
- Hero shot 可產生 2 candidates。

## cinematic — 高品質成片

含 Approval Gate，未核准不執行昂貴後續步驟：

```
Script → Approve
Storyboard / Hero Frames → Approve
Video Generation
Final Preview → Approve
Publish
```

## Candidate 策略（成本控制）

- Normal Shot：1 candidate
- Hero Shot：2 candidates
- 低 QA score：repair 或再產生 candidate
- Cinematic：允許人工比較 candidate

## 對應

- `QualityMode` enum（draft/auto/cinematic）在 `VideoProject.quality_mode`。
- `QualityTier`（low/balanced/cinematic）落到 ShotSpec。

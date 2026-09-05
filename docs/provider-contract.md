# Provider 契約 (provider-contract)

狀態：`implemented`（介面）/ `planned`（vendor adapters）。

## 原則

Pipeline 不得知道特定廠商 schema。`cineagent/providers/` 只暴露抽象介面，
vendor 專屬 payload 一律放在各 adapter 內。

## 分離的四個 modality

| 介面 | 檔案 | 已實作 adapter |
|------|------|----------------|
| TextProvider | `providers/base.py` | Mock |
| ImageProvider | `providers/image/base.py` | Mock |
| VideoProvider | `providers/video/base.py` | Mock（durable/idempotent） |
| AudioProvider | `providers/audio/base.py` | Mock（native timestamps） |

## Error taxonomy（禁止單一 except Exception）

`providers/base.py` 定義：
- `ProviderError`（基底）
- `AuthError`          → 對應 401
- `RateLimitError`     → 對應 429
- `ValidationError`    → 對應 422 / malformed output
- `TimeoutErrorLike`   → API timeout
- `ServerError`        → Provider 5xx
- `CapabilityError`    → 模型不支援所需能力

呼叫端必須依錯誤類型分流；不允許用一個 `except Exception` 吞掉。

## Structured Output 契約

- 一律要求 JSON Schema / Pydantic model。
- JSON parse / validation 失敗 → 拋錯，**不接受自由文字**當替代。
- `TextProvider.structured(schema, system, user)` 是通用入口。

## 新增一個 provider 的步驟

1. 實作對應 modality 的介面（Text/Image/Video/Audio）。
2. 在 `ModelCapabilityRegistry` 註冊其能力（modality/duration/aspect/cost…），
   **價格與能力欄位須來自官方文件，禁止猜測**。
3. 寫 Mock test 覆蓋其成功 + 失敗情境。
4. 狀態設 `experimental`，通過測試後才 `implemented`。

## Vendor 支援狀態

| Vendor | 狀態 | 註 |
|--------|------|----|
| mock | implemented | 離線測試 |
| Kling / Runway / Veo / Sora / Luma / OrcaRouter | planned | 查官方文件後再註冊 |

> OrcaRouter 可作為 Provider Gateway 之一，但 CineAgent 不得依賴它才能運作。

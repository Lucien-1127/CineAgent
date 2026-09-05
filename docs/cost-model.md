# 成本模型 (cost-model)

狀態：`implemented`（ledger 建置完成）；真實 vendor 價格 `planned`。

## UsageEvent（cost ledger）

`cineagent/domain/usage.py` — 每次計費 API call 記錄：

project_id, scene_id, shot_id, provider, model, operation, tokens, image_count,
video_seconds, retry, estimated_cost, actual_cost, status

落在 SQLite `usage_events` 表，`cineagent/storage/repositories.py` 提供聚合：

- project total cost
- cost by provider
- cost by model
- cost by stage/operation
- failed-generation cost（status != success 仍計費）
- cost per finished second（project cost / final duration）

## Budget enforcement

- `VideoProject.budget_limit`（≥0，None=不限）。
- `ModelRouter.select(..., budget=...)` 會排除成本未知或超預算的模型
  （`estimated_cost_usd is None` → 不選，避免靜默選到未計價模型）。
- 預估超額時停止昂貴生成並要求決策（Decision gate）。

## 語意

- `estimated_cost` = 提交前預估（planned）。
- `actual_cost` = 完成後實際（可能含已計費但失敗的工作）。
- retry 計入，並反映在 cost；重送同一 remote job（冪等）不重複計費。

## 測試

`tests/test_storage.py::test_cost_ledger_aggregations`。

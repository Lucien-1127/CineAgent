# 狀態機 (state-machine)

狀態：`implemented`。來源：`cineagent/domain/enums.py` + SQLite（非單一 JSON current_stage）。

## 為何不用單一 JSON stage

舊版用 `agents_workflow_state.json` 的 `current_stage` 當唯一狀態來源，crash 後無法
精確恢復，也無法辨識「某 shot 已遠端提交」。v4 改用 SQLite 持久化每一 entity，
GenerationJob 保存 `remote_job_id`，可 webhook/poll 續接。

## ShotState

```
pending → submitted → generating → succeeded → approved
                               ↘ failed → retrying → submitted …
                                    ↘ rejected
```

## JobState

```
pending → submitted → generating → succeeded
                               ↘ failed / retrying
```

- `remote_job_id` 必填：crash 後能撈回遠端工作。
- Idempotency：以 idempotency key 重送不會建立重複 remote job / 重複計費。
- 中途 crash 不會把 job 誤標 COMPLETE；狀態只有遠端確認 success 才寫 succeeded。

## 錯誤處理原則

- 區分 AuthError / RateLimitError / ValidationError / Timeout / Server5xx /
  CapabilityError，不得以單一 except Exception 吞掉。
- 429 重試後仍失敗 → 標 `[API_PAUSE]` 並停止，等人工介入。

## 自我恢復測試

- `tests/test_storage.py`：shot state recovery、job idempotency by remote_id。
- `tests/test_providers.py`：video submit 冪等、poll lifecycle。

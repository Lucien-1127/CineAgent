# Video Project Schema (video-project-schema)

狀態：`implemented`。所有模型位於 `cineagent/domain/`，Pydantic + JSON Schema。

## 核心概念

- **Scene** = 故事單位（有敘事意義）。
- **Shot** = 實際生成/QA/可獨立恢復的最小影片素材單位。
- 一個 Scene 可有多個 Shot；Shot 時間軸由 Audio Master Timeline 決定。

## 主要模型

| 模型 | 檔案 | 說明 |
|------|------|------|
| VideoProject | `project.py` | 專案層：topic/objective/audience/platform/language/target_duration/aspect_ratio/quality_mode/budget_limit/status |
| CreativeBrief | `script.py` | audience/core_message/emotional_goal/content_type/references/prohibited_elements/cta_strategy |
| ScriptPackage | `script.py` | hook/narration/scenes/facts/cta/metadata/script_strategy/expected_duration/platform |
| VisualBible | `visual.py` | characters/wardrobe/locations/props/palette/lighting/art_style/lens_language/camera_language/reference_assets/negative_constraints/continuity_rules |
| ShotSpec | `shot.py` | 見下方必備欄位 |
| Asset | `asset.py` | asset_id/source/type/uri/tags/license/provenance/hash/reuse_count/meta(embedding) |
| GenerationJob | `job.py` | provider/model/remote_job_id/state/timestamps/retry/input+output asset ids/estimated+actual cost/error |
| QAReport | `job.py` | score/decision/problems/severities/repair_instructions |
| MasterTimeline | `timeline.py` | 每 segment: kind/text/start/end/audio_uri/words；`captions()` 由同一份資料產生 |

### ShotSpec 必備欄位（實現於 `shot.py`）

shot_id, scene_id, start_time, end_time, duration, narration_segment, visual_goal,
subject, action, location, shot_size, camera_angle, camera_motion, composition,
lighting, continuity_in, continuity_out, first_frame_ref, last_frame_ref,
reference_images, reference_video, generation_strategy, quality_tier, provider_constraints

## JSON Schema

所有模型皆可用 `Model.model_json_schema()` 產生 JSON Schema 供 structured output /
對外 API 使用。測試 `tests/test_domain_schemas.py` 驗證 schema validation。

# 電影製作引擎研究與升級規格（2026-11-24）

狀態：RESEARCH / PROPOSED；實作及品質改善尚未驗證。此文件不改動執行程式、不啟用外部生成、不宣稱任何測試通過。適用 CineAgent 與 prompt-factory 的共用技能設計；CineAgent 為唯一影片執行引擎。

## 1. 目標與既有架構

使用者對先前兩段各 30 秒生成後合併的影片品質不滿意；具體缺陷尚未逐幀確認。研究目標是改善劇本、分鏡、角色表演、動畫、提示詞、跨鏡連續性及驗收，而非擴寫一份長提示詞。公開文件不得存放私人劇情、肖像、素材 URL、API 金鑰或供應商憑證；測試以合成角色取代。

- [main 的 README](https://github.com/Lucien-1127/CineAgent/blob/main/README.md) 仍為舊版。
- [PR #9](https://github.com/Lucien-1127/CineAgent/pull/9) 仍 open，未合併；研究比對 head `593b9c15d3aab9440ae01d52c8b3dff8654b8435`。保留逆向節奏、anchor、bridge/carry/loop、靜動提示詞分離、provider routing、gate 與重試。其 README 報告 32 個離線測試及一次未通過的單鏡實跑；本輪沒有重跑測試。
- [Issue #6](https://github.com/Lucien-1127/CineAgent/issues/6) 已追蹤表演時間軸、旁白與角色對白、固定聲線、嘴型同步；本規格補充該工作，不建立重複主鏈。[PR #5](https://github.com/Lucien-1127/CineAgent/pull/5) 已關閉且未合併，不以其為目前基礎。
- 本次以 main 建立純文件分支，避免混入 PR #9 尚待審查的程式。後續實作前重新確認 PR #9、Issue #6、CI、基底與授權。

## 2. 研究來源與採用界線

以下為候選與研究方向，非依賴安裝清單。Exa 已讀取 CineCrew README、DEV_NOTES、ViMax README、MovieAgent README、Video Prompting Skill 入口及角色設定工作流；其他來源以論文/專案入口作下一輪驗證。未執行上游程式或完成完整授權稽核。正式重用前固定 commit、讀取 LICENSE、NOTICE 及依賴/模型權重授權；無明確授權時只借鑑概念。

| 來源 | 採用方向 | 階段 |
|---|---|---|
| [CineCrew](https://github.com/Ironieser/CineCrew) / [DEV_NOTES](https://github.com/Ironieser/CineCrew/blob/main/DEV_NOTES.md) | FilmDSL；敘事、攝影調度、渲染規格分離；關鍵幀/影片雙審查 | P0 |
| [ViMax](https://github.com/HKUDS/ViMax) / [技術報告](https://arxiv.org/abs/2606.07649) | 素材管理、專案恢復、工作流與渲染檢查點 | P0 |
| [Video Prompting Skill](https://github.com/Square-Zero-Labs/video-prompting-skill) / [角色設定工作流](https://github.com/Square-Zero-Labs/video-prompting-skill/blob/main/video-prompting/references/workflows/character-sheets.md) | 按模型載入指南；人物設定圖→場景定錨圖→動態提示詞 | P0 |
| [Camera Artist](https://arxiv.org/abs/2604.09195) | 遞迴分鏡，前鏡與全劇情境約束攝影選擇 | P0 |
| [MovieAgent](https://github.com/showlab/MovieAgent) / [論文](https://arxiv.org/abs/2503.07314) | 劇本→場景→鏡頭階層 | P1 |
| [VideoDirectorGPT](https://arxiv.org/abs/2309.15091) | 實體群組與空間配置 | P1 |
| [StoryDiffusion](https://arxiv.org/abs/2405.01434) / [NVIDIA Video Storyboarding](https://research.nvidia.com/labs/par/video_storyboarding/) | 跨鏡身分與自然動態的權衡，非純提示詞可保證 | P1 |
| [CinePreGen](https://arxiv.org/abs/2408.17424) | 預演與攝影軌跡 | P1 |
| [VBench](https://github.com/Vchitect/VBench) / [VBench++](https://arxiv.org/abs/2411.13503) / [T2V-CompBench](https://arxiv.org/abs/2407.14505) | 評測維度、動作與角色屬性綁定；本地/雲端成本先驗證 | P1 |
| [Lasseter 1987](https://doi.org/10.1145/37401.37407) / [Pixar in a Box](https://www.khanacademy.org/pixar) / [Fountain](https://fountain.io/syntax/) | 動畫十二原則、敘事與視覺文法、純文字劇本格式 | P0 |
| [Veo 官方提示詞指南](https://deepmind.google/models/veo/prompt-guide/) | 適配器依供應商實際能力與官方文件編譯 | P0 |

## 3. PR #9 原始碼差異與風險

已讀取該 head 的 [prompts.py](https://github.com/Lucien-1127/CineAgent/blob/593b9c15d3aab9440ae01d52c8b3dff8654b8435/cineagent/prompts.py)、[planner.py](https://github.com/Lucien-1127/CineAgent/blob/593b9c15d3aab9440ae01d52c8b3dff8654b8435/cineagent/planner.py)、[gate.py](https://github.com/Lucien-1127/CineAgent/blob/593b9c15d3aab9440ae01d52c8b3dff8654b8435/cineagent/gate.py) 的關鍵段落。

| 觀察 | 建議 |
|---|---|
| planner 以單一 character 規劃；強制至少三種運鏡、最後三分之一加速；enforce_variety 可修改靜態機位 | 增加角色 ID 清單、每鏡角色綁定；改為敘事驅動節奏，允許有意義的固定鏡頭、留白、長鏡；強制規則改成可解釋的風格預設 |
| prompts 以關鍵字判定靜動分離；以字母 s 檢查時長，容易誤判 | 先驗證型別化欄位與時碼，再按 adapter 產生提示詞；允許必要構圖變化；I2V 不重述無關靜態特徵，T2V 必須提供靜態語境 |
| gate 五軸權重 motion 僅 0.10，最低總分 0.82、identity 0.80；可讓低動態分被其他高分抵銷 | 依鏡頭意圖設定必要硬閘門；評測輸入必須包含預期動作、運鏡及參考；缺證據為 NOT_VERIFIED，禁止發布 |
| README 描述 fail-open 以維持產出，但不等同已驗收 | 允許產出 DRAFT；FINAL 必須 fail-closed。缺證據、拒絕、未知 provider 結果不可自動通過或重新付費送單 |
| 同檔案首尾幀鎖定不代表實際輸出影格一致 | 分開記錄 planned_frame_hash 與 rendered_frame_hash；只有連續動作需要 carry/bridge，硬切、時間跳轉不必強制同畫面 |

## 4. 建議中介規格（FilmDSL-inspired）

在現有 domain/BeatSheet 上擴充，先做相容性設計，不另建平行資料庫或執行器。優先 JSON Schema/Pydantic 與版本欄位；所有 ID 可解析，時間使用一致單位。

- project：aspect_ratio、fps、style、locale、duration、locked_intent、schema_version、budget_policy。
- narrative：theme、logline、arc、sequence、scene、beat；人物目標、衝突、轉折與結局。
- assets：character_id、身分參考、可變/不可變屬性、服裝、表情圖、聲線、location_id、prop_id、來源、使用權、雜湊。
- shots：shot_id、scene_id、cast_ids、敘事功能、start/end state、composition、blocking、screen direction、camera、lighting、performance、continuity、audio、render、acceptance、evidence。
- performance：主要動作、預備動作、接觸、重心、次要動態、反應、視線、結束狀態及時間窗；避免同時堆疊過多動作。
- continuity：區分同一動作延續、一般剪接、時間跳躍；人物、道具、服裝、光源、方向與實際前後幀。
- audio：旁白、對白 speaker_id、voice profile、說話/閉嘴區間、環境音、音效、音樂與靜默；時間軸以實際音檔對齊。
- render：provider、model、input_mode、實際能力快照、合法時長、解析度、參考 ID、提示詞與參數分離；不支援的控制明確降級或阻擋。

## 5. 專業知識及提示詞編譯

劇本採 Theme → Arc → Sequence → Scene → Beat；Fountain 供人閱讀，結構化資料作機器來源。不要以 Hook/CTA 模板強制每一類影片。每個鏡頭應有敘事目的、可見變化與終態；使用 180 度軸線、視線匹配、動作剪接、建立鏡頭、插入與反應鏡頭等作可解釋的預設，允許有意破例。

動畫十二原則：擠壓延展、預備動作、場面調度、逐格/關鍵姿勢、跟隨與重疊動作、緩入緩出、弧線、次要動作、時間節奏、誇張、立體結構、吸引力。寫實、2D、3D 分別設定適用程度；禁止為套用原則破壞寫實物理。

模型適配器分 T2V、I2V、reference、first/last frame、native multi-shot；按官方契約與實際端點查核能力。I2V 先驗收場景定錨圖，提示詞主寫時間、動作、相機及必要改變；T2V 提供主體、空間、光線等。不可把不支援的參數塞入請求。逐鏡預設，原生多鏡頭為可測的替代路線，不假設必然較佳。

## 6. 驗收閉環及對照實驗

三層：規格/提示詞審查 → 關鍵幀驗收 → 實際影音及跨鏡驗收。分數須有時間點、觀測事實與 evidence 路徑；相應項目無法評測時標 NOT_VERIFIED，不得填假分。人物互換、必須動作缺失、嚴重人體/物理錯誤、對白說錯、重大場記錯誤、缺必要證據為硬阻擋。分數門檻須用人工標註校準，禁止平均掩蓋關鍵失敗。靜態鏡不等於靜止表演；運鏡需要時用稠密時間採樣或實際影格/光流與人工覆核。最終音軌需以實際音訊、字幕及對嘴證據檢查；不能從提示詞推定結果。

測試資料使用合成成年角色，避免發布私人素材。至少三類：雙人細微情緒與交談、2D/3D 動畫動作、連續物件/運鏡；各含正常、缺資料、外部資料注入/竄改情境。固定素材、模型、時長、預算與評審規格，A/B 盲評對照現行基準與候選；先拆分測試變因，再比較完整管線。記錄品質、接受率、重試、總成本、時間、失敗原因；小樣本/缺證據為 INCONCLUSIVE。不得以 mock 或單一成功樣本宣稱成片能力。未知送單結果先查 provider，禁止盲目重送。每鏡及全案設生成上限、金額上限與重試上限。

## 7. 後續工作及發布條件

- [ ] P0：確認 PR #9 最新狀態與 CI，稽核現有 schema、測試、Issue #6，建立差異矩陣；固定外部來源 commit 與授權。
- [ ] P0：擴充既有 domain 與多人物綁定，增加表演/場記/音訊時間軸、schema 驗證及三情境回歸測試。
- [ ] P0：模型適配器與專業知識模組；修正強制運鏡和節奏、提示詞驗證及 gate 硬阻擋。
- [ ] P1：關鍵幀與影音雙 gate；串接現有重試、預算、續跑與 evidence，不重做。
- [ ] P1：在 prompt-factory 建立可攜 SKILL.md 與 references，與 CineAgent 共用規格，不複製執行器；先查現有技能及授權。
- [ ] P1：離線測試與低成本合成測試，之後在明確付費預算授權下執行真實對照。
- [ ] P2：評估重型 VBench/預演等模組是否具成本效益；4GB VRAM 不預設本地執行大型影片模型。

發布裁決：本文件可供審查（DOCS ONLY）。運行程式、付費生成、模型品質、音訊同步及完整成片驗收均 NOT_RUN。不得標記新版功能已完成；未取得足夠證據前不合併功能或發布成品。

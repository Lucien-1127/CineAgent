# CineAgent 短影音成長流程

狀態：`experimental`。本流程提高可測試性與命中機率，不保證「爆款」。

目前已實作：結構化 brief、Hook 多維排名、Critic 修訂回灌、720p 直式 render、基本 TechnicalQA，以及達到最小樣本後的 performance insight。趨勢資料擷取、字幕 UI safe-zone 檢查、平台 A/B 發布與真實 analytics connector 仍為 `planned`。

## 依據

- YouTube 說明 Shorts 排名會參考選擇觀看、平均觀看時長、平均觀看百分比與滿意度；開場應立即兌現標題／封面的承諾。
- TikTok 官方建議平台原生的直式、sound-on、人物感與較自然的製作風格，採 Hook → Body → Close，前三秒提出內容價值，持續以畫面、聲音、文字與動作刺激注意力。
- Meta 目前提高原創內容在推薦中的比例，並提供 Replays 與逐時 retention；低價值搬運或只加字幕、邊框、變速不算實質原創。

官方參考：

- https://support.google.com/youtube/answer/11914225
- https://support.google.com/youtube/answer/16559650
- https://support.google.com/youtube/answer/12942217?co=YOUTUBE._YTVideoType%3Dshorts
- https://ads.tiktok.com/help/article/creative-best-practices
- https://ads.tiktok.com/business/en/blog/creative-best-practices-top-performing-ads
- https://about.fb.com/news/2026/01/2026-ai-drives-performance/
- https://about.fb.com/news/2026/03/rewarding-original-creators-on-facebook/

## Production loop

1. **Evidence intake**：輸入受眾、痛點、原創角度、可證明的 payoff，以及經人工或官方來源確認的趨勢；不得由模型捏造趨勢。
2. **Hook tournament**：至少三種不同機制，依受眾相關性、承諾清晰度、好奇心、payoff 對齊與可信度排名，不只採用模型自評總分。
3. **Promise-first script**：前 2 秒建立停止滑動理由，前 3 秒兌現主題承諾；Body 每段只增加一項資訊，Close 先交付 payoff 再自然 CTA。
4. **Retention edit**：移除空泛前言與重複資訊；每個 beat 安排視覺或語意變化，但不使用與內容無關的 clickbait。
5. **Originality gate**：記錄原創觀點、證據與轉化價值。Stock／第三方素材只能支援主敘事，不能成為低價值拼接。
6. **Platform render**：9:16、至少 720p；字幕 UI safe zone 與 sound-on／sound-off QA 為 `planned`。不同平台應重新包裝，不直接複製同一版本。
7. **Variant test**：一次只更換一個變數（first frame、Hook、節奏、payoff 或 CTA），保留 control，避免無法歸因。
8. **Measure**：記錄 shown-in-feed、chose-to-view、前 3 秒 retention、平均觀看百分比、shares、replays 與 follows。
9. **Learn**：至少達到 `min_samples` 才形成策略洞察；先修選擇觀看率，再修前三秒留存，最後提升可分享的 payoff。

## Release gate

- Hook 與實際 payoff 一致。
- 前三秒無 logo animation、問候或背景鋪陳。
- 每個資訊 beat 都有對應畫面，字幕不是唯一新增價值。
- 所有事實、數字與趨勢有來源；不可用虛構權威製造刺激。
- 原創性、授權、safe zone、音訊、字幕、解析度與平台 metadata 均通過 QA。
- 每次發布都有可辨識的 variant ID，Analytics 能回連 Hook 與腳本策略。

# PR 審查與失敗邊界

必要檢查仍叫 `review`，保留分支保護。一般 `pull_request` 事件讓結果綁定待合併提交，避免 `pull_request_target` 等待核准到期而完全沒有審查結果。

自動審查限同儲存庫、非草稿、作者關係為 OWNER／MEMBER／COLLABORATOR 的開啟中 PR。前置檢查不下載或執行 PR 程式；不合資格、缺少金鑰或外部 fork 均明確失敗。草稿轉為可審查時會重新執行。

維護者原有的 `/orcacode-review` 與 `@orcacode-review` 指令保留，同樣拒絕外部 fork。留言觸發的工作本身綁定預設分支，不可用它的綠燈冒充 PR 提交的必要檢查；正式合併以 PR 事件的結果為準。

第三方 Action 固定完整提交，引擎固定 1.3.13；工作流程自行設定 P0／P1 阻擋、過大差異不予通過，避免 Dashboard 關閉審查仍產生成功檢查。設定 4 個並行、每次引擎 10 分鐘、工作 20 分鐘上限；這不是金額上限，供應商金鑰仍應設定錢包額度。

真實審查仍依賴 ORCAROUTER_API_KEY 與外部服務，失敗保持紅燈。AI 程式審查不取代功能、資料或正式部署驗收。新版合併後，舊 PR 需同步主分支並產生新提交，讓最新版本重新執行檢查。

## 已取得的錯誤證據

CineAgent run 35519395418 的 GitHub 原始註記：
`This workflow run required approval but was not approved before it expired.`
中文：工作需要核准，但在核准前已到期。該次沒有進入審查，不能診斷為金鑰或模型問題。

智研 PR #13 先前只有三個 Python 成功檢查，main 分支另要求 `review`。本次保留同名工作並修正事件，沒有降低合併保護。

- https://github.com/Lucien-1127/CineAgent/actions/runs/35519395418
- https://github.com/Continuum-AI-Corp/orca-code-review/tree/6d253e0399c84848fedc8801176d6bea77817762


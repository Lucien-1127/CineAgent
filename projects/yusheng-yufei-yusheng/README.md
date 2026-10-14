# 魚生・于飛・餘生｜CineAgent 製片包

> 針對《魚生・于飛・餘生》的**獨立原創短片製作素材包**。僅準備腳本與渲染提示詞，**未付費生成圖片／影片、未生成配音或最終 MP4**。

## 已交付
- `screenplay.md`：16 個逐鏡頭可拍攝腳本，包含時間、畫面、表演、對白、聲音與希望型結局。
- `characters.md`：育呈（工程師）及魚魚（理髮準師→正式設計師）的英文固定角色提示詞、服裝與聲線。
- `scene_prompts.json`：依 CineAgent `run_pipeline.py --skip-script` 需要的 **JSON 陣列** 輸出，含每鏡畫面／動態／負面提示詞。
- `audio_timeline.json`：配音、旁白、聲音床時間軸；**這不是現有執行器直接支援的配音檔**。
- `validate_project.py`：無額外依賴的離線驗證工具。

## 規格
- 全長 112 秒＝16 鏡×7 秒。單段使用當前執行器已列出的 7 秒預設（169 格／24 FPS）。
- 台灣城市寫實、9:16、角色雙向付出與誤會、放手後一年重逢伏筆。
- 末鏡魚魚看向店門，觀眾知道外面的人是育呈，但沒有正式復合：**悲傷仍在，希望也仍在**。

## 驗證（WSL／Ubuntu／Python 3.12，離線無費用）
```bash
cd CineAgent
python3 projects/yusheng-yufei-yusheng/validate_project.py
```

## 如需送入目前引擎（WSL；需先取得付費 API 授權）
```bash
cd CineAgent
cp projects/yusheng-yufei-yusheng/scene_prompts.json ./scene_prompts.json
# 必須確認舊 agents_workflow_state.json 不會混入其他專案：
# 先以隔離複本執行並備份狀態；不得在其他製作專案的工作目錄直接 --reset。
# 在隔離且已獲授權的執行環境、確認費率與模型可用後，才可執行：
python3 run_pipeline.py --skip-script --quality balanced --duration 7 --scenes 16 --total-duration 112
```

**重大限制**：`run_pipeline.py` 的 providers 仍固定 Agnes 舊 API，未驗證當前可用；它將 images → video clips 個別產出，但**不會自動生成旁白、字幕、對嘴或合併所有片段成單一影片**。上方命令會觸發可能付費的請求，不是測試命令。不得在未檢查供應商、成本與角色參考圖前執行。

## 停止條件
1. **腳本完成**：16 鏡故事完整；兩人的工作設定與情感合理，開放結局不假復合。
2. **可供機器讀取**：JSON 可解析、秒數連續，人物鎖定一致、時碼不超界。
3. **視覺待驗證**：先免費審查人物母提示詞，再用最低成本各生成一張試圖；其餘付費渲染由授權後再執行。
4. **成片驗收**：角色不可變臉；理髮操作安全自然；對白配音不得跨鏡；片尾門鈴＋認出但沒有復合台詞。

## 畫幅重要注意（提交前校正）
本案 **9:16 是剪輯交付目標，不是目前引擎已能直接輸出的原生畫幅**。目前 `run_pipeline.py` 逐鏡影片生成預設尺寸為 `768x1152`（2:3），而圖片生成請求為 `1024x1792`（約 4:7）；`scene_prompts.json` 的寬高欄位目前**不會自動控制**逐鏡渲染函式。正式上架 Shorts/Reels 前必須先驗證供應商可用 9:16 解析度，否則後製裁切到例如 `1080x1920`，並重新檢查角色是否被裁掉。

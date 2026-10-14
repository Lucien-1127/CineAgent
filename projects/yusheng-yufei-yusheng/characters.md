# 《魚生・于飛・餘生》固定人物設定與提示詞

> **本版為原創小說影像化的人物設計，不以真人外貌為生成依據。** 必須先產生並人工確認兩名角色的正面、45 度、側面參考圖；現有 CineAgent 執行階段未將 reference_images 傳給 image API，因此角色一致性目前只有文字鎖定，不能視為已實現參考圖鎖定。

## 育呈｜YUCHENG
- **年齡／工作**：28 歲，台灣男性，工程師。
- **固定外觀**：中等體格；整齊黑色側分短髮；平直深眉；棕色眼睛；左眉有一道很淺的小疤；左手配戴銀色指針錶。
- **個性／表演**：穩重、不善說情緒；緊張時下顎繃緊，難過時先低頭，笑很輕。他要有生活疲憊感而不是霸道總裁。
- **聲線**：成年男聲、中低音、不誇張戲劇化；台灣口音、自然停頓。
- **影像母提示詞（英文）**：

```text
Character turnaround/reference sheet for YUCHENG, fictional adult Taiwanese man age 28, software engineer, medium build, short tidy black side-part hairstyle, straight dark eyebrows, calm brown eyes, faint small scar across left eyebrow, silver analog wristwatch on left wrist. Grounded gentle restrained expression, realistic skin pores, natural anatomy. Front, three-quarter and profile portrait, neutral studio soft light, consistent exact identity across all three views, modern Taiwanese cinematic realism, 9:16 portrait. No text, no logos.
```

## 魚魚｜YUYU
- **年齡／工作**：24 歲，台灣成年男性，理髮準師，後期正式升任設計師。
- **固定外觀**：纖細身形；栗棕色自然層次短髮、柔和碎瀏海；溫柔杏眼；右眼下方有一顆很小的痣；銀色小剪刀項鍊。
- **個性／表演**：喜歡笑，工作時專注；難過時先勉強笑再垂眼，盡量不用誇張大哭。成年男性、自然中性氣質，不幼態化。
- **聲線**：成年男聲、較清亮、親密感自然，帶一點鼻音。
- **影像母提示詞（英文）**：

```text
Character turnaround/reference sheet for YUYU, fictional adult Taiwanese man age 24, slender barber apprentice, chestnut-brown layered short hair with soft natural fringe, warm almond-shaped brown eyes, tiny beauty mark below his right eye, small silver scissors pendant. Gentle expressive but distinctly adult facial features, subtle smile mixed with melancholy, natural skin pores, realistic anatomy. Front, three-quarter and profile portrait, neutral studio soft light, consistent exact identity across all views, modern Taiwanese cinematic realism, 9:16 portrait. No text, no logos.
```

## 不可變與可變項
1. **不可變**：年齡基線、臉部結構、眉疤／淚痣位置、髮色與髮型輪廓、體型、飾品。若跨一年，僅允許輕微表情與衣著變化，不變成其他人。
2. **可變**：衣著依分鏡切換。相遇時魚魚穿黑色準師工作服；同居時白 T；結局魚魚穿白襯衫與正式理髮圍裙。育呈的銀錶是雨夜重逢辨識伏筆。
3. **關係演出**：成年男性雙向照顧；避免單方面施救、施虐、控制浪漫化。爭吵時無身體威脅；重逢不是立即和好。
4. **拍攝**：先單獨各產 3 個角度，確認身份之後再產雙人同框；雙人出鏡優先兩人中景、側影或手部；切勿以 AI 直接生成繁體中文招牌／手機訊息，文字由後製覆蓋。
5. **主要負面詞**：`identity swap, face morphing, hairstyle drift, duplicate person, extra fingers, childlike face, excessive crying, exaggerated romance, captions, watermark, CGI`。

## 目前引擎的限制
`scene_prompts.json` 會將同一段 `character_card` 注入每張圖片提示詞；即使該鏡只有一名角色，模型仍可能錯誤多生一人。已在各鏡頭加入明確的 cast 和單人構圖約束，但**需要生成後人工檢查**。角色參考圖／TTS／對嘴／影片串接尚未串成一鍵式完整流程。

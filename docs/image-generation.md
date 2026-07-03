# 🖼️ 圖片生成路由

## 路由決策樹

```
                    ┌──────────┐
                    │ 輸入內容  │
                    └─────┬────┘
                          │
                    ┌─────▼──────┐
                    │ NSFW 內容？ │
                    └──┬──────┬──┘
                  YES  │      │  NO
              ┌────────▼┐    ┌─▼──────────┐
              │ SD Forge │    │ Agnes Image │
              │ (本機)   │    │ 2.1 Flash   │
              │ DS8/RV V6│    │ (雲端 API)  │
              └────┬────┘    └──────┬──────┘
                   │                │
              ┌────▼────┐     ┌─────▼─────┐
              │ nsfw-gen │     │ pipeline  │
              │ 專案     │     │ 自動生圖    │
              └─────────┘     └───────────┘
```

## 一般圖片 → Agnes Image 2.1 Flash

**端點：** `POST /v1/images/generations`

```json
{
  "model": "agnes-image-2.1-flash",
  "prompt": "[英文提示詞，描述主體+場景+風格+光線]",
  "n": 1,
  "size": "1024x1792"
}
```

## 提示詞結構（9：16 直式）
```
[主體] in [場景], [姿勢/表情],
cinematic composition, [光線], [風格],
clean sharp details, no motion blur, well-lit
```

## 負面提示詞 (Negative Prompts)

### Agnes Image 2.1 Flash 負面提示詞

| 類別 | Negative Prompt |
|------|----------------|
| 通用品質 | `worst quality, low quality, blurry, jpeg artifacts, ugly` |
| 構圖問題 | `bad anatomy, bad hands, extra fingers, mutated limbs, cropped` |
| 風格干擾 | `cartoon, 3d, render, sketch, watermark, text, signature` |
| 動態干擾 | `motion blur, action shot, dynamic pose`（靜態圖片不要動態） |

### SD Forge NSFW 負面提示詞（DreamShaper 8）

```
ugly, deformed, blurry, low quality, bad anatomy, bad hands,
extra fingers, watermark, text, signature, monochrome, censored
```

### SD Forge NSFW（Realistic Vision V6）

```
(deformed iris, deformed pupils, semi-realistic, cgi, 3d, render,
sketch, cartoon, drawing, anime), text, cropped, out of frame,
worst quality, low quality, jpeg artifacts, ugly, duplicate, morbid,
mutilated, extra fingers, mutated hands, poorly drawn hands,
poorly drawn face, mutation, deformed, blurry, dehydrated,
bad anatomy, bad proportions, extra limbs, cloned face, disfigured,
gross proportions, malformed limbs, missing arms, missing legs,
extra arms, extra legs, fused fingers, too many fingers, long neck,
UnrealisticDream
```

## Temperature 參數

圖片生成使用**擴散模型**，無 temperature 參數。

| 模型 | 對應參數 | 建議值 |
|------|----------|--------|
| Agnes Image 2.1 Flash | — (擴散) | 無 |
| SD Forge DS8 | CFG Scale | 7.0 |
| SD Forge RV V6 | CFG Scale | 5.0 |
| SD Forge | Steps | 25 |

**解析度建議：**
| 平台 | 解析度 | 比例 |
|------|--------|------|
| TikTok/Reels/Shorts | 1024x1792 | 9:16 |
| YouTube | 1792x1024 | 16:9 |
| 方形 | 1024x1024 | 1:1 |

**注意：**
- 提示詞需**英文**（Agnes 對英文理解最佳）
- 非 NSFW 內容**禁止**送入 SD Forge
- 4 次重試 + 指數退避

## NSFW → 本地 SD Forge

**端點：** `http://127.0.0.1:7860/sdapi/v1/txt2img`

**模型選擇：**
| 模型 | 適合 | Prompt 前綴 |
|------|------|------------|
| DreamShaper 8 | 藝術寫實混合 | `masterpiece, best quality,` |
| Realistic Vision V6 | 極致寫真 | `RAW photo,` |

**參數：**
- Sampler: DPM++ 2M Karras (DS8) / DPM++ SDE Karras (RV6)
- Steps: 25
- CFG: 7 (DS8) / 5 (RV6)
- 解析度: 512x768 起

**獨立專案：** `C:\Users\ysga1\nsfw-gen\`

參見 `sd-forge-nsfw` 技能。

## 品質注意事項

- 本機 SD Forge 品質不如 Agnes Image 2.1 Flash
- 優先使用雲端 Agnes API（除非 NSFW）
- 若 Agnes 額度用盡 → 降級提示（非自動降級到 SD）

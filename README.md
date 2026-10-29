# Rain Autoresearch UI（互動原型）

不用寫程式，就能幫測站降雨模型做深度學習調參的操作介面。

[線上Demo](https://x200706.github.io/rain-autoresearch-ui/)

## 它做什麼

1. **UI 收集設定**：OpenRouter Key 與代理模型、測站 CSV、訓練／測試切分、主目標（指標＋雨量門檻）、副目標（預設三種守門或語意描述）、演化參數（代數、早停、每代子代、同時訓練數）。
2. **改寫代理技能**：把設定填進技能模板 `program.md` 裡的 `[[欄位]]`，產生這次實驗專用的 `SKILL.md`。改的是代理的技能本身，不只是一段提示。
3. **組成 shell 指令交給 Hermes**：
   ```bash
   hermes chat --provider openrouter -m <模型> -s rain-autoresearch-<站號> --yolo \
     -q "依技能 rain-autoresearch-<站號> 執行副目標消融實驗"
   ```
4. **設定快取**：整組設定算成 SHA-256 指紋；和跑過的實驗完全相同就直接展示結果，不重新訓練（程式端另有「同一個體不重訓」的訓練快取）。
5. **看結果**：收斂圖、`results.tsv`（best 標藍、守門擋下標紅、快取標灰）、測站資訊卡、學習紀錄、消融比較表、Hermes 日誌；右側可調閱歷代實驗並把舊設定載回左側。

## 原型裡有什麼
- 三個測站的真實實驗紀錄（訓練期指標）：467590 恆春、467490 臺中、467571。用預設設定選這三站會命中快取。
- 上傳 CSV 會在瀏覽器裡實際檢查欄位（`觀測時間(hour)`、`降水量(mm)`）和 ≥ 門檻的樣本數，檔案不會上傳到任何地方。
- 模型清單會即時從 OpenRouter 公開 API 載入，連不到時改用內建清單。
- 沒命中快取時按「開始最佳化」是**展示模式**：只模擬等待畫面和日誌，靜態網站不會真的訓練。要實際執行，請下載 `SKILL.md`、複製指令到裝好 [Hermes Agent](https://hermes-agent.nousresearch.com/) 的機器上跑。
- 深色／淺色主題，手機寬度也能用。

## 更新實驗資料

```bash
python tools/build_data.py D:/rain_autoresearch/outputs 467590 467571 467490
```

## 尚未接上的部分

- 這是純前端原型，還沒有 Gradio 後端；「開始」不會真的呼叫 Hermes。
- 主程式目前把代數上限、早停、每代子代數寫死在 `genome.py`／`budget_guard.py`（20／3／8）。UI 改這些值會寫進技能，但要讓程式也照做，還需要把它們改成參數。

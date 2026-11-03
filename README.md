# Rain Autoresearch UI

不用寫程式，就能幫測站降雨模型做深度學習調參的操作介面。

[線上Demo](https://x200706.github.io/rain-autoresearch-ui/)（靜態 HTML 原型）

這個倉庫有兩個版本：

| 版本 | 檔案 | 用途 |
|---|---|---|
| Gradio 介面 | `app.py`、`rainui/` | 真正的介面：在本機讀實驗紀錄、啟動 Hermes、即時顯示進度與結果 |
| HTML 原型 | `index.html`、`data/` | GitHub Pages 上的展示，不會訓練；保留給已寄出的連結使用 |

## 啟動 Gradio 介面

需要 Python 3.10 以上。

```bash
pip install -r requirements.txt
python app.py
```

開啟 <http://127.0.0.1:7860>。

介面預設讀 `../rain_autoresearch`（與本倉庫同一層的實驗專案）。其他位置與行為用環境變數調整：

| 環境變數 | 預設 | 說明 |
|---|---|---|
| `RAIN_AUTORESEARCH_ROOT` | `../rain_autoresearch` | 實驗專案根目錄（有 `program.md`、`outputs/`、`data/`） |
| `RAIN_UI_MODE` | 自動 | `real`：真的啟動 Hermes；`demo`：只播放等待動畫。自動模式在找得到 Hermes 和實驗專案時用 `real` |
| `HERMES_CMD` | 找 `hermes` | Hermes CLI 的路徑；多個參數用 `\|` 分隔 |
| `HERMES_HOME` | `~/Hermes` 或 `~/.hermes` | 介面把這次實驗的 `SKILL.md` 寫到 `<HERMES_HOME>/skills/research/<技能名稱>/` |
| `RAIN_UI_STATE_DIR` | `./runs` | 介面自己的紀錄：實驗名稱、備註、Hermes 輸出 |
| `GRADIO_SERVER_PORT` | `7860` | 連接埠 |

找不到實驗專案時（例如在別台電腦上），介面改讀 `data/experiments.js` 的五站資料，只能瀏覽與播放展示動畫。

實驗專案路徑也可以在介面左側「2 · 實驗與測站資料」直接修改；找不到 `program.md` 時會顯示錯誤，不會切換。

## 介面做什麼

1. **左欄收集設定**：OpenRouter Key 與代理模型（清單即時從 OpenRouter 抓，預設 `deepseek/deepseek-v4.1-flash-1017`）、實驗名稱、測站（選已有資料的測站，或上傳 CSV）、切分、主目標、副目標、演化參數。欄位格式不對時，錯誤直接顯示在該欄位下方，並擋住開始按鈕。
2. **產生技能**：把設定填進模板的 `[[欄位]]`，在「6 · 預覽」可以看與修改。主目標或副目標和預設（≥ 40 mm 的 MAE、三種副目標）不同時，技能最前面會加一節「介面覆寫（優先級最高）」，要求 Hermes 先修改 `budget_guard.py` 與 `program.md`、跑過測試，再開始實驗。
3. **設定快取**：設定和已完成的實驗完全相同時，按鈕變成「Cache Hit・展示快取結果」，直接顯示結果。
4. **啟動 Hermes**：
   ```bash
   hermes chat --provider openrouter -m <模型> -s <技能名稱> --yolo -Q --format stream-json \
     --in <實驗專案> --query-file prompt.txt [--api-key <Key>]
   ```
   API Key 只在這次啟動時傳給 Hermes，不寫進任何檔案；留空則用電腦中 Hermes 預設的 OpenRouter Key。
5. **等待動畫**：把論文圖 3.4 簡化成七個步驟，依 `outputs/<站號>/` 的檔案判斷目前走到哪一步；代理迴圈中會標出目前的副目標、代數，以及正在產生子代、訓練或評估。
6. **結果自動更新**：每 3 秒檢查一次。學習紀錄與消融比較表在這次實驗開始後出現，就算完成，主畫面自動換成結果：數字卡、收斂圖、可縮放的訓練集與測試集預測圖（跟著各副目標的最佳基因）、`results.tsv`、測站資訊卡、學習紀錄、消融比較。
7. **備註**：實驗結束後可以在主畫面下方寫備註，存在 `runs/`，不動 `outputs/` 的實驗紀錄。
8. **刪除實驗**：按主畫面右上角的「刪除實驗」，頁面上會先出現紅色確認列，按「確定刪除」才會刪除，無法復原。介面啟動的實驗刪的是介面的紀錄（名稱、備註、Hermes 輸出）；已完成的測站刪的是整個 `outputs/<站號>`。

## 測試

```bash
python -m pytest
```

測試都在暫存目錄裡跑，用假的 Hermes 指令，不會訓練模型，也不會碰真的實驗紀錄。

## 更新 HTML 原型的資料

```bash
python tools/build_data.py D:/rain_autoresearch/outputs 466910 467490 467571 467590 467650
```

## 已知限制

- 主程式把代數上限、早停、每代子代數寫死在 `genome.py`／`budget_guard.py`（20／3／8）。介面改這些值會寫進技能，但要讓程式也照做，還需要把它們改成參數。

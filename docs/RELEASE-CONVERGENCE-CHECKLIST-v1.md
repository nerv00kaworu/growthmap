# GrowthMap Release 收斂清單 v1

- 狀態：**authoring.2 security remediation 已完成獨立驗證；release commit、tag 與 archive 由最終封版流程產生**
- 日期：2026-07-24（Asia/Taipei）
- 封裝目標：**GrowthMap 作者編輯器**（authoring/editor）
- 明確不含：Abyss Bureau 玩家 Web/API runtime、玩家 runtime DB、付款／PvP、任何 runtime LLM／圖像生成能力。

> 本清單的「封裝完成」意義是：從乾淨 clone、鎖定依賴與明確設定，可重建作者編輯器並通過驗證；不把本機資料庫、備份、日誌或一次性驗收工件混進 release。

## 0. 發布範圍鎖定（必過）

- [x] Release 名稱、版本號、tag 格式：`growthmap-authoring-v0.1.0-authoring.2`（舊 `.1` tag immutable；`.2` tag 指向最終 release commit）。
- [x] README 首段明確寫出：GrowthMap 是 canonical authoring/editor；玩家 runtime 位於獨立 `abyss-bureau` repo。
- [x] `apps/player-web`、`player_api` 等歷史 contract 描述已改標為「已遷出／歷史工程契約」；不得讓封裝者誤以為這些是本 repo 的 runtime 依賴。
- [x] Release 不含任何 secret、`.env`、本機 provider 設定、使用者資料或 SQLite runtime DB；僅保留無 secret 的 `.env.example`。

**驗收：** README、目錄結構、啟動方式及 release archive 的內容一致。

## 1. 工作樹分類（P0）

### 1.1 必須納入 Git／release source

以下目前是未追蹤或已修改、但屬實作必要成分者；逐一 review 後納入：

- [x] 已修改作者編輯器程式已完成 review 與 tests；待 release commit 一併納入：
  - `src/backend/api/routes.py`
  - `src/backend/main.py`
  - `src/backend/models/models.py`
  - `src/backend/models/schemas.py`
  - `src/backend/tests/test_smoke_api.py`
  - `src/frontend/src/components/NodePanel.tsx`
  - `src/frontend/src/components/NodePanel/NodeContent.tsx`
  - `src/frontend/src/lib/types.ts`
  - `src/frontend/src/stores/useStore.ts`
  - `README.md`
- [x] 已確認下列為 **遷出的玩家 runtime 殘留**，不可因 release check 失敗而重新納入 GrowthMap：
  - `src/backend/assets/`、`content/`、`domain/`、`gameplay/`、`idempotency.py`
  - `assets/ch1/` 的候選圖、generation records、draft manifest、prompt pack。
- [x] `src/backend/scripts/` 已判定為遷出 runtime release tooling，與所有 `assets/ch1/` 一樣排除；作者編輯器沒有這些檔案仍可 build/test/run。
- [x] 已批准 fallback assets／歷史 Art Bible 已改列為非 authoring runtime input；保留於本機 archive、排除於 package。
- [x] 正式文件：本文件、作者編輯器 README／backend README、`CHANGELOG.md`、`RELEASE-MANIFEST.json`；玩家 runtime 歷史工程文件已排除。
- [x] 正式啟動／驗證工具：唯一入口為 `scripts/start_growthmap.sh`；`start.sh` 只保留 compatibility wrapper。

**驗收：** 在新 clone 中，正式 source 路徑不再顯示為 untracked，且不依賴舊 venv、`.next` 或本機 DB 才能 import。

### 1.2 必須忽略（不進 Git、不進 release archive）

- [x] `.runtime-logs/` 與所有 `*.log`。
- [x] `src/frontend/.next/`、`node_modules/`、Python `venv/`、`__pycache__/`、`*.pyc`。
- [x] 所有 local DB：`*.db`、`*.sqlite*`，包括 `src/backend/growthmap.db`。
- [x] `src/backend/growthmap.db (deleted)`、`growthmap.db?immutable=1&mode=ro`、所有 `growthmap.db.backup-*`／`*.bak-*`。
- [x] 暫時測試輸出、screenshots、browser artifacts、coverage、OS／IDE metadata 已由 ignore 規則排除。

**驗收：** `.gitignore` 覆蓋上述類別；`git status --short` 不再列出它們。

### 1.3 必須封存、不可隨 release 帶出

- [x] 根目錄 `backups/`（約 **288 MB**）已被 ignore 且不進 release archive；保留於 operator-managed archive。
- [x] `src/backend/backups/`（約 **34 MB**）同上。
- [x] `reports/`、`memory/`、`state/jobs/` 已排除於 authoring package；release 證據由 manifest 與 archive SHA sidecar 提供。
- [x] `scripts/simulate_ch1_v02.py` 已判定為歷史 player simulation，排除於 authoring package。

**驗收：** release archive 不含 DB backups、job state、日誌及未審核候選素材；另產出 archive manifest（檔名、SHA-256、存放位置）。

## 2. 可重現建置與啟動（P0）

- [x] 前端 lockfile 與 `package.json` 同步；以 `npm ci`，不是 `npm install`，完成乾淨安裝。
- [x] 後端已提供 Python 3.12 驗證過的 `requirements.lock`，release/CI 使用 lock；`requirements.txt` 保留為可編輯 dependency policy。
- [x] 已移除舊 `start.sh` 的不確定行為：它現在只是安全 launcher 的 compatibility wrapper，不再現場 `npm install`、建立 venv 或啟動 Next dev server。
- [x] 已建立唯一 production-like run command，需：
  - 不自動 kill 既有 port listener；
  - host、port、DB path 由明確環境變數／參數控制；
  - 預設僅 loopback bind；對外 bind 須顯式指定；
  - 不在啟動中自動安裝套件或執行內容匯入；schema compatibility steps 僅會對顯式指定的 DB 執行；
  - 有 `/health` 或等價健康檢查。
- [x] 已提供 `.env.example`（僅 key 名稱、無 secret）及 explicit DB URL 指引；DB 初始化／匯入／備份流程仍待補。

**驗收：** 新 clone 依 README 可在空白環境 build/run；停止與重啟不影響其他服務或既有資料。

## 3. 內容發布鏈與資料庫邊界（P0）

- [x] 已判定 `src/backend/scripts/generate_content_release.py --check` 為遷出 runtime 的殘留：它依賴缺失的 `gameplay.importer`，且 source mapping 指向 workspace `memory/scratchpad/`。GrowthMap authoring release **不執行、也不修復** 此 gate。
- [ ] 若未來要發布玩家 runtime，應在 `abyss-bureau` repo 內重新建立 content release JSON、asset manifest、SHA 與 verifier；不得回填 GrowthMap。
- [x] canonical authoring DB 與 application source 分離：DB 是外置資料／受控匯入物，不封進程式 package。
- [x] 作者包的 export/import 已在 temporary DB 驗證；服務啟動仍會對明確指定的 DB 執行 lightweight schema compatibility steps，因此升級前必須由 operator 建立備份。

**驗收：** authoring source check PASS；對 temporary DB 的 authoring smoke PASS；正式 authoring DB SHA 在所有 release gate 前後不變。

## 4. 測試與品質 Gate（P0）

在乾淨依賴環境完成：

```bash
# source hygiene
git diff --check
git status --short

# frontend
cd src/frontend
npm ci
npm run lint
npm run typecheck
npm run build

# backend
cd ../backend
python -m compileall .
DATABASE_URL='sqlite+aiosqlite:///:memory:' python -m unittest discover -s tests -v

# player-runtime content release lives in abyss-bureau and is intentionally not a GrowthMap authoring gate
```

- [x] 前端 lint/typecheck/build 全 PASS（本輪驗證）。
- [x] 後端目前已追蹤完整 test suite PASS（12 tests，本輪驗證）；後續新增 tests 必須一併納入此 gate。
- [x] OpenAPI／API client 沒有獨立生成流程；OpenAPI endpoints 已由 smoke test 驗證。
- [x] `git diff --check` PASS（本輪驗證）。
- [x] `aiosqlite` teardown 已在 smoke suite `tearDownClass` dispose isolated engine；clean lock-venv 驗證無 ResourceWarning。
- [x] 對隔離 clean source snapshot 再跑一輪，frontend `npm ci/lint/typecheck/build` 與 backend temporary DB suite 均通過；已確認被排除的 player runtime residue 不在 snapshot。

## 5. 文件、版本與交付物（P1，但封裝前建議完成）

- [x] README 已更新：正確 Quick Start、唯一 run command、authoring-only boundary、支援版本、DB handling。
- [x] 已新增 `CHANGELOG.md`：版本範圍、破壞性變更、資料／內容格式相容性。
- [x] 已新增 `RELEASE-MANIFEST.json`：source commit、版本、Node/Python 版本、dependency hash；archive SHA 由最終 archive sidecar 記錄。
- [x] 已建立 release note（`CHANGELOG.md`）：已包含／刻意排除／升級方式與已知限制；rollback 由 operator-managed DB backup 執行。
- [ ] Tag 只在所有 P0 gate PASS、release commit 後工作樹乾淨時建立。

## 6. 封裝完成判準

只有同時符合以下條件，才可標記 **Packagable / 可封裝**：

1. 正式 source 全被追蹤；runtime／log／DB／backup／job state 全被排除。
2. 新 clone 可無人工補路徑地安裝、build、測試與執行。
3. 作者編輯器 export/import 與 manifest 驗證可重現；不執行已遷出玩家 runtime 的 release/replay gate。
4. README、啟動腳本與實際 repo boundary 一致。
5. 所有 P0 gate PASS、release commit 後 `git status --short` 為乾淨。
6. release archive 與 archive manifest 已生成並驗證 SHA-256。

## 建議執行順序

1. **分類與 Git 收斂**：先決定每個 untracked 路徑的納入／忽略／封存，禁止先打包。
2. **補可重現指令**：修 content check、依賴 lock 與唯一啟動入口。
3. **乾淨環境驗收**：以新 clone／temporary DB 跑完整 gate。
4. **製作 archive**：只包 tracked source + 安裝／部署文件，另附 manifest。
5. **簽 tag／發 release**：最後一步才建立 release tag；若任一 P0 失敗，回到對應項修補。

## authoring.2 security remediation gates (2026-07-27)

- [x] Next >=15.5.21 and sharp >=0.35; production `npm audit --omit=dev` = 0.
- [x] Python security floors resolved with compatible FastAPI; `pip-audit -r requirements.lock` = 0.
- [x] Browser stores only provider ID/type/model; no browser provider helper or request secret overrides.
- [x] Secret names require the app-owned `GROWTHMAP_LLM_KEY_` namespace on create/patch/write; endpoint is localhost-only, atomic mode 0600, response-empty.
- [x] Launcher supports only `127.0.0.1`/`localhost` (explicitly rejects IPv6 forms) and backend enforces the same trusted Host policy.
- [x] Original 12 core tests plus 8 security regressions pass.
- [ ] No release commit/tag/archive in this remediation work; perform those only after review.

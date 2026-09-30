# HKTDC Sports Footwear Hidden Opportunity Discovery Platform (HOP)

A runnable **walking skeleton** of the
[Enterprise AI Platform Implementation Plan v4.0](docs/explanation/implementation-plan-v4.md). It
covers the spec 24 immediate actions and the P0 backlog. It compares consumer **demand**, **search
results (SERP)** and **generative-engine answers (GERP)** for sports-footwear needs. From those
signals it derives evidence-backed **Draft Opportunity Cards**, which named humans then approve,
watchlist or reject.

It runs fully **offline**. Recorded sandbox fixtures and a deterministic mock model are used unless
DataForSEO or OpenAI credentials are provided.

[繁體中文說明見下方](#繁體中文)

## Quickstart

```bash
make install && source .venv/bin/activate      # Python 3.11+
hop domain validate sports-footwear             # validate the domain pack and run the gap-rule tests
hop collection estimate-cost --market HK --tier A
hop collection run --market HK --tier A         # full spec 7 workflow producing Draft Opportunity Cards
hop trace inspect --run latest                  # OpenTelemetry span tree for the run
hop opportunity list
make dashboard                                  # Streamlit, http://localhost:8501 (7 pages)
make api                                        # FastAPI, http://localhost:8000/docs
make check                                      # ruff and pytest
```

To try it without a local install, run `make compose-up`. This starts the API, the dashboard,
Postgres and Redis from `infrastructure/docker-compose.yml`.

## What you get

- **Three layers** (spec 4.1). `hop.platform` is domain-agnostic, `hop.products.opportunity_intelligence`
  is the product, and `domain_packs/sports_footwear` is pure YAML. A test enforces that the platform
  never imports product or domain code. See [ADR 0001](docs/adr/0001-three-layer-package-layout.md)
  for why the code lives under `hop/` rather than a top-level `platform/`.
- **Contracts.** There are 12 Pydantic v2 contracts, published as JSON Schema in
  `docs/reference/schemas/`, with a drift test. Missing values are never coerced to zero (spec 8.4):
  every measure carries one of eight states, and every rate carries its n and a 95% Wilson interval.
- **Governed agents.**
  - Capability manifests declare the owner, status, allowed tools, egress allowlist, and step, time and
    cost limits.
  - Tools are deny-by-default.
  - Every model call goes through the model gateway, which applies the model allowlist, budget
    reservation, injection scanning, untrusted-content delimiting, retries and timeouts.
  - Every run can be stopped with the kill switch or by revoking capabilities.
- **Deterministic decisions.** Gap rules use three-valued logic. The ten admission gates of spec 7.1
  and the six-component score with risk penalties are versioned YAML. Models only observe, label and
  draft explanations, and those drafts are validated against the evidence.
- **Durable runs.** Runs are idempotent, with retries and backoff, activity timeouts, budgets,
  checkpoints and resume, and dead letters. Costs are recorded per capability.
- **Human accountability.** Cards move through Draft → In Review → Approved / Watchlist / Rejected.
  HIGH priority cards need the `review_board` role and a named approver, and every step is recorded
  in a hash-chained audit log.
- **Evaluation.** Golden sets for recommendation labelling and entity resolution run against a quality
  ratchet and champion baseline (`hop evaluation run`).
- **Interfaces.**
  - Typer CLI, `hop` ([reference](docs/reference/cli.md)).
  - FastAPI with header-based identity and W3C `traceparent` propagation
    ([reference](docs/reference/api-and-permissions.md)).
  - A seven-page Streamlit dashboard (spec 14).

## Repository layout

```text
hop/platform/        api, workflow_runtime, model_gateway, evidence_service, capability_registry,
                     policy_engine, evaluation, observability, common_contracts (+ storage, audit, ...)
hop/products/opportunity_intelligence/
                     gap_detection, counter_evidence, scoring, opportunity_lifecycle, dashboard, api
domain_packs/sports_footwear/
                     markets, taxonomy, brands, attributes, prompts, rules, scoring, evaluation_sets, sandbox
infrastructure/      containers/Dockerfile, docker-compose.yml, backup/
docs/                tutorials, how-to, reference, explanation, adr, runbooks
tests/               unit, contract, policy (incl. prompt injection), e2e (pipeline, lifecycle, API, CLI, dashboard)
```

## Documentation (Diátaxis)

- Tutorial: [first sandbox run and first Opportunity Card](docs/tutorials/first-sandbox-run.md)
- How-to guides:
  - [add a market](docs/how-to/add-a-market.md)
  - [inspect a trace, test a rule, recover a run](docs/how-to/operate-runs.md)
- Reference:
  - [CLI](docs/reference/cli.md)
  - [API, roles and configuration](docs/reference/api-and-permissions.md)
  - [JSON Schemas](docs/reference/schemas/)
- Explanation:
  - [architecture and what is not built yet](docs/explanation/architecture.md)
  - [implementation plan v4.0](docs/explanation/implementation-plan-v4.md)
  - [ADRs](docs/adr/)
- Runbooks:
  - [DataForSEO](docs/runbooks/dataforseo-serp.md)
  - [incident response, kill switch and rollback](docs/runbooks/incident-response.md)
  - [backup and restore](docs/runbooks/backup-restore.md)

## Real providers (optional)

| Secret | Effect |
|---|---|
| `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | SERP and search-volume collection via DataForSEO, limited to egress `api.dataforseo.com` |
| `OPENAI_API_KEY` (optionally `OPENAI_BASE_URL`, `OPENAI_MODEL`) | GERP observation and labelling through the OpenAI-compatible adapter |

Without these secrets, the platform uses the sandbox provider and `mock-gerp-1`, and cards are marked
as simulated in their cost records and model ids.

## Limitations

This is a walking skeleton, not a production system. Identity is a header or role-selector
placeholder for Entra ID. Runs execute in-process; Celery or Temporal comes later. Telemetry is
stored locally rather than exported over OTLP. The golden sets are small development partitions.
The full list is in [architecture → Not yet implemented](docs/explanation/architecture.md#not-yet-implemented-later-phases).

---

## 繁體中文

**HKTDC 運動鞋「隱藏商機」發掘平台**是按照《企業級 AI 平台實施計劃 v4.0》建立的可運行雛形（walking skeleton），涵蓋第 24 節的即時行動及 P0 待辦項目。平台比較同一消費需要在三方面的訊號：**搜尋需求**、**搜尋結果頁（SERP）**同**生成式引擎答案（GERP）**，再用可追溯的證據整理出「商機卡」草稿，交由具名的審批人批核、列入觀察名單或否決。

冇設定任何憑證時，平台會完全離線運行，使用已錄製的沙盒數據同確定性的模擬模型。

### 快速開始

```bash
make install && source .venv/bin/activate      # 需要 Python 3.11 或以上
hop domain validate sports-footwear             # 驗證領域包，並執行缺口規則測試
hop collection estimate-cost --market HK --tier A
hop collection run --market HK --tier A         # 執行第 7 節完整流程，產生商機卡草稿
hop trace inspect --run latest                  # 查看今次運行的追蹤樹
hop opportunity list
make dashboard                                  # Streamlit 儀表板（7 頁）：http://localhost:8501
make api                                        # FastAPI：http://localhost:8000/docs
make check                                      # ruff 同 pytest
```

### 重點

- **三層架構**：
  - `hop.platform` 係平台核心，唔含任何領域知識。
  - `hop.products.opportunity_intelligence` 係商機產品。
  - `domain_packs/sports_footwear` 只有 YAML 設定。

  平台核心唔可以引用產品或領域代碼，有自動測試把關。
- **缺失值**：缺失值永遠唔會當成 0（第 8.4 節）。每個比率都附帶樣本數 n 同 95% Wilson 信賴區間，樣本少於 30 會標示為「探索性」。
- **管治**：
  - Agent 能力清單列明負責人、狀態、可用工具同對外連線白名單。
  - 工具預設全部拒絕，未獲授權就唔可以用。
  - 模型閘道控制可用模型同預算，並會偵測提示注入。
  - 設有緊急停止掣，亦可以撤銷個別能力。
- **決策可重現**：缺口規則、第 7.1 節嘅十道准入關卡同評分全部由確定性代碼計算，並有版本管理。模型只負責觀察、標註同草擬解說，草擬內容要通過證據驗證先會採用。
- **人手問責**：商機卡按「草稿 → 審閱中 → 已批准 / 觀察名單 / 已否決」流轉。高優先級商機卡必須由 `review_board` 角色嘅具名人員批准，每一步都寫入雜湊鏈審計記錄。
- **介面**：`hop` 命令列工具、FastAPI、七頁 Streamlit 儀表板。

### 使用真實數據（可選）

設定 `DATAFORSEO_LOGIN` 同 `DATAFORSEO_PASSWORD` 就會用 DataForSEO 收集搜尋數據；設定 `OPENAI_API_KEY` 就會用 OpenAI 相容模型。冇設定就會自動用沙盒數據同模擬模型。

### 限制

- 身份認證暫時用 HTTP 標頭代替，之後會換成 Microsoft Entra ID。
- 工作流程喺同一個進程內運行，之後會改用 Celery 或 Temporal。
- 評估用嘅黃金數據集規模仍然好細。

詳情見 [architecture.md](docs/explanation/architecture.md)。

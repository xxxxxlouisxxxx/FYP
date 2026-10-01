# Deploy the dashboard to Streamlit Community Cloud

The hosted dashboard is a private sandbox. The URL shows only a password form until `HOP_APP_PASSWORD`
matches. Share the URL and the password together with the people who should see it. Do not commit
either secret.

The GitHub repository is public, so the source code is public. Secrets stay in Streamlit Community
Cloud and are not in the repository. Making the repository private is a separate decision and is
required only if you also want the source hidden. A public repository cannot use Streamlit's one
free private-app slot; the password gate is what keeps the dashboard closed.

## 1. Deploy

1. Open [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Create an app from this repository.
3. Use branch `cursor/hop-walking-skeleton-32a5` until the pull request is merged, then switch the
   app to `main`.
4. Set the main file to `hop/products/opportunity_intelligence/dashboard/app.py`.
5. Pick an app name that is hard to guess.
6. In Advanced settings, select Python 3.12 and add secrets:

```toml
HOP_APP_PASSWORD = "choose-a-long-password"
HOP_REVIEW_PASSCODE = "a-second-secret-for-approving-cards"
```

Community Cloud exposes these top-level secrets as environment variables. `HOP_APP_PASSWORD` opens
the dashboard. `HOP_REVIEW_PASSCODE`, entered in the sidebar, unlocks roles that can approve a HIGH
card. Without it, a visitor who knows the app password can look but cannot select `review_board`.

7. Deploy. The first start installs dependencies and seeds sandbox runs for HK, SG and US. That takes
   a few minutes. Later starts reuse the process cache until the app sleeps.

The URL is `https://<your-app-name>.streamlit.app`.

## 2. What a visitor sees

- No password: a password form. No market data is loaded.
- App password only: the seven pages, with the role limited to `viewer` or `analyst`.
- Both secrets: the full role list, including approval of HIGH cards, and a reset button on
  Platform Health. Reset deletes the local SQLite file. The next load rebuilds the sandbox markets.

Do not put `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` or `OPENAI_API_KEY` in this app's secrets.
Seeding is skipped when those credentials are present, and a shared app should not spend provider
budget.

## 3. Local behaviour

With neither variable set, `make dashboard` opens exactly as before and does not ask for a password.
If the database has no successful run, the first page load seeds HK, SG and US from fixtures.

---

# 部署到 Streamlit Community Cloud

部署出嚟嘅 dashboard 係私人 sandbox。未輸入啱 `HOP_APP_PASSWORD` 之前，條網址只會顯示密碼框。想俾邊個睇，就同時俾條 link 同密碼。兩個密碼都唔好 commit。

GitHub repo 係 public，所以程式碼係公開嘅。密碼只放喺 Streamlit Community Cloud，唔喺 repo 入面。如果連 source 都唔想公開，就要另外將 repo 轉做 private。public repo 用唔到 Streamlit 免費額度入面嗰一個 private app，所以而家靠密碼鎖住個 dashboard。

## 1. 部署

1. 打開 [share.streamlit.io](https://share.streamlit.io)，用 GitHub 登入。
2. 由呢個 repo 建立 app。
3. Branch 用 `cursor/hop-walking-skeleton-32a5`。Pull request merge 之後先改做 `main`。
4. Main file 填 `hop/products/opportunity_intelligence/dashboard/app.py`。
5. App 名揀一個唔好猜到嘅。
6. Advanced settings 揀 Python 3.12，然後加 secrets：

```toml
HOP_APP_PASSWORD = "揀一組長密碼"
HOP_REVIEW_PASSCODE = "另一組，用嚟批 HIGH 卡"
```

Community Cloud 會將呢啲最外層 secrets 變成環境變數。`HOP_APP_PASSWORD` 用來開 dashboard。`HOP_REVIEW_PASSCODE` 喺 sidebar 輸入，先可以揀到批 HIGH 卡嘅角色。只有 app 密碼嘅人可以睇，但揀唔到 `review_board`。

7. Deploy。第一次會裝套件，再用 sandbox 數據整 HK、SG、US 三次 run，要幾分鐘。之後同一個 process 會用快取，直到 app 瞓着。

網址係 `https://<你嘅-app-名>.streamlit.app`。

## 2. 訪客會見到咩

- 冇密碼：得一個密碼框，唔會載入任何市場數據。
- 只有 app 密碼：七頁都睇到，角色只可以係 `viewer` 或者 `analyst`。
- 兩組密碼都有：可以揀全部角色，包括批 HIGH 卡。Platform Health 有重設掣。重設會刪本地 SQLite，下次打開會重新整 sandbox 市場。

唔好喺呢個 app 嘅 secrets 填 `DATAFORSEO_LOGIN`、`DATAFORSEO_PASSWORD` 或者 `OPENAI_API_KEY`。有真憑證時唔會自動整 sandbox 數據，共用 app 亦唔應該用你嘅供應商額度。

## 3. 本地

兩個變數都冇設定時，`make dashboard` 同以前一樣，唔會問密碼。如果資料庫未有成功嘅 run，第一次開頁會用 fixture 整 HK、SG、US。

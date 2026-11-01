# Public showcase

The showcase builds the same React application as the local runtime. Its fixtures
illustrate product planning, organization, coding-plan approval, retained changes,
test reports, AI review, acceptance evidence and historical runs. They are not
executed model results or evidence of a deployed application backend.

## Build and preview

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm test
pnpm build:showcase
pnpm preview:showcase
```

Open `http://127.0.0.1:4174/`. Development uses `pnpm dev:showcase` on port 5174.
The normal `pnpm build` still writes `dist` with base `/ui/`. The showcase writes
`dist-showcase` with base `/`, so deploying it cannot replace the local API's UI.
Both retain hash bookmarks, including selected tasks, tabs and historical runs.

## Data boundary and safety

`src/transport.ts` defaults to the existing same-origin HTTP requests. The showcase
entry point installs `src/showcase/showcaseApi.ts` before React mounts. Vite removes
that conditional import from the normal production build. No query parameter,
local-storage switch or backend endpoint can activate the adapter in normal mode.

The adapter is a closed router. Unknown reads return 404; unsupported mutations
return an explicit unavailable response. Nothing falls through to HTTP. Visitors
can edit and approve sample product drafts, assign sample work, change eligible
sample statuses, edit preview configuration and acknowledge a sample acceptance.
Changes live only in that tab's memory and reset on reload.

Real execution, coding-plan continuation, Request Changes, model connections and
probes, project registration/import, preview start/stop and every delivery action
are unavailable. No credentials are needed or included. Fixture repository paths
use `showcase://`; preview logs have no active URL or container. Historical sample
runs never borrow evidence from the current run.

The showcase-only `_headers` policy also denies browser network connections,
iframes and form submission. The local application's policy and API behavior are
unchanged. The outbound Source link is an ordinary GitHub navigation.

## Cloudflare Workers Static Assets

`frontend/wrangler.jsonc` deploys only `dist-showcase`. It has no Worker API,
bindings, secrets, database, Docker access or local service proxy. SPA fallback
serves the application shell for unmatched navigation paths; app bookmarks use
the existing hash router. This follows Cloudflare's current
[Static Assets workflow](https://developers.cloudflare.com/workers/static-assets/)
and [SPA routing](https://developers.cloudflare.com/workers/static-assets/routing/single-page-application/).

```powershell
cd frontend
pnpm build:showcase
pnpm check:cloudflare
pnpm exec wrangler login
pnpm deploy:showcase
```

Complete Cloudflare authorization in your browser. Never paste a token into source
or create a credential file in this repository. A Pages-only login needs refreshing
to authorize Workers deployment. Record the actual URL from Wrangler after a
successful deployment, then add it to the README and repository homepage.

For CI, `.github/workflows/showcase.yml` deploys `main` when repository variable
`CLOUDFLARE_ACCOUNT_ID` and secret `CLOUDFLARE_API_TOKEN` are configured. The token
must be scoped to the intended account with Workers Scripts edit access and
whatever additional permissions Cloudflare requires for that account. Without
the account variable the deployment job is skipped. Local OAuth remains a valid
deployment route without CI secrets.

After deployment, verify all navigation sections, refresh a task/tab/history
bookmark, inspect console errors and confirm response security headers. The live
URL must be reported as pending until these deployment checks actually succeed.

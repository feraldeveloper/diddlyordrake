# Diddly or Drake

The static HTML/CSS/JavaScript frontend follows `mockup.png`: pixel typography, purple/red title, real vote totals, the clickable comment, and expandable FAQs. The background is a 35-degree gradient from `#010101` to `#41213a` with slowly drifting `#81214a` splotches (51-72 second animation legs). Background motion stops when reduced motion is enabled. The final FAQ answer alternates only while open, and respects reduced-motion settings.

## GitHub Pages + free Cloudflare poll

GitHub Pages serves the frontend. Cloudflare Workers runs the voting API; D1 persists the votes. Cloudflare's free plan has daily usage limits: see [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/) and [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/).

The deployment uses these endpoints:

- Website: <https://diddlyordrake.com/>
- API: <https://diddly-or-drake.diddlyordrake.workers.dev/api/votes>

`config.js` points to the API. The website shows real totals, not the example numbers from the mockup. API requests must carry an allowed Origin header; visiting the API URL directly can return "Origin not allowed."

The setup steps below are for recreating this deployment in another account. To update this deployment, authenticate with Wrangler, then run `npx wrangler@latest deploy --config cloudflare/wrangler.jsonc`. Frontend updates publish through GitHub Pages when pushed to `main`.

### 1. Create the Cloudflare database

With a free Cloudflare account and a current Node.js LTS installation, run from this folder:

```sh
npx wrangler@latest login
npx wrangler@latest d1 create diddly-or-drake
```

Copy the returned database ID into `cloudflare/wrangler.jsonc`, replacing `REPLACE_WITH_YOUR_D1_DATABASE_ID`. Keep the binding name `DB`.

Set `ALLOWED_ORIGINS` to your actual site origins, separated by commas. For example:

```text
https://yourname.github.io,https://diddlyordrake.com,https://www.diddlyordrake.com
```

An origin has no path or trailing slash: a project page at `https://yourname.github.io/diddlyordrake/` uses `https://yourname.github.io`.

### 2. Initialize and deploy the API

```sh
npx wrangler@latest d1 execute diddly-or-drake --remote --config cloudflare/wrangler.jsonc --file cloudflare/schema.sql
npx wrangler@latest deploy --config cloudflare/wrangler.jsonc
```

The schema creates the poll tables and preserves existing votes if reapplied. The two-row totals table avoids scanning the entire vote table for every visit.

See [Cloudflare's D1 setup guide](https://developers.cloudflare.com/d1/get-started/) for dashboard-based setup instead. The Worker needs the `DB` D1 binding and the `ALLOWED_ORIGINS` environment variable.

### 3. Connect the frontend

Edit `config.js` with the Worker URL printed by deployment:

```js
window.POLL_CONFIG = {
  apiUrl: "https://diddly-or-drake.YOUR-SUBDOMAIN.workers.dev/api/votes"
};
```

This URL is public. No Cloudflare account API token or secret belongs in the frontend.

### 4. Publish on GitHub Pages

Commit the frontend, `assets/`, and `_config.yml` to your repository. In **Settings → Pages**, select **Deploy from a branch**, your branch, and **/ (root)**.

All frontend asset paths are relative, so repository subpaths work. `_config.yml` excludes the backend, local database, tests, and mockup images from the Pages build. Keep `data/` and `.verification/` out of Git as specified in `.gitignore`.

The domain itself is not configured by these files.

## Local preview

Run `start.cmd`, then open <http://127.0.0.1:8000>. Or:

```sh
python server.py
```

Python 3.10+ is sufficient; no packages are needed. Localhost automatically uses the local SQLite API, even with the production URL in `config.js`. Local votes are saved in `data/votes.sqlite3`; they are separate from the hosted D1 poll.

Opening `index.html` directly previews the layout without a poll connection.

## Voting behavior

- Clicking the same name again does not add another vote. Clicking the other name changes the vote.
- Cloudflare uses a random browser token stored in localStorage and sent in the Authorization header. This avoids relying on third-party cookies between GitHub Pages and Workers.
- The token is hashed before storage in D1. Voter identifiers are never returned in public results.
- The local Python preview continues to use its existing browser cookie.
- This is a casual poll, not verified one-person voting: clearing browser storage, using another browser, or scripting new tokens can add votes. The mockup's fraud FAQ is a joke, not an anti-abuse guarantee.
- The like/dislike icons and Reply label are decorative.

## Validation

```sh
python -m unittest -v test_server.py
```

The font is bundled locally under the SIL Open Font License in `assets/fonts/OFL.txt`.
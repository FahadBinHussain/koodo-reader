# koodo-reader fork notes

fork of `koodo-reader/koodo-reader`. upstream = official repo, origin = `FahadBinHussain/koodo-reader`. local clone: `C:\Users\Admin\Downloads\koodo-reader`.

## premium unlock: how the fork is structured (READ FIRST)

**dev = upstream/dev + ONE infra commit + nothing else.** the source changes are NOT committed to dev. they live ONLY in `patches/premium-unlock.patch` and get applied at build time:

- `patches/premium-unlock.patch` — the single canonical patch (all customizations)
- `patches/apply-patch.js` — idempotent apply script: checks for marker strings in `src/utils/request/user.ts`, applies `git apply` if not present, skips if present
- `patches/sync-upstream.ps1` — future upstream merge workflow (fetch → reset to upstream → verify patch applies → apply)
- `package.json` scripts:
  - `premium:apply` → `node patches/apply-patch.js`
  - `premium:revert` → `git checkout -- src/store/actions/manager.tsx src/utils/common.ts src/utils/file/configUtil.ts src/utils/request/thirdparty.ts src/utils/request/user.ts`
  - `prebuild` AND `build` both run `node patches/apply-patch.js` so Vercel deploys the patched code automatically
- `.gitattributes` — `*.patch text eol=lf` (CRITICAL: a CRLF patch file breaks `git apply` on Windows; PowerShell `>` / `Set-Content` writes CRLF. write patch files via `git show <rev>:patches/premium-unlock.patch` piped through python, or normalize with `.Replace("\`r\`n","\`n")`)

### what the premium patch does (5 files)

| file | change |
|------|--------|
| `src/store/actions/manager.tsx` | `handleFetchUserInfo`: suppress support/upgrade dialog; `handleFetchAuthed`: always authed=true (Pro) |
| `src/utils/request/user.ts` | `fetchUserInfo`: keep REAL server call but force `data.type="pro"` + `valid_until=9999999999`. do NOT fully mock it (breaking real auth breaks decrypt) |
| `src/utils/request/thirdparty.ts` | `encryptToken`: try/catch around `thirdpartyRequest.encryptToken` (bundled lib THROWS TypeError on `null.data` — must catch); on 400/500 fall back to storing the raw JSON token in local storage and return 200. `decryptToken`: return raw JSON tokens directly if they lack the `#` server marker |
| `src/utils/common.ts` | `testConnection`: for MEGA in browser, skip the real upload test and return true (megajs Blob upload fails on browser CORS/WebSocket quirks) |
| `src/utils/file/configUtil.ts` | `getSyncData`/`updateSyncData`: fall back to local storage (`koodo_sync_data_<type>`) instead of erroring when Koodo's server rejects (no real auth) |

### IMPORTANT behavioral gotchas (learned the hard way)

1. **Koodo Sync toggle MUST be OFF.** when `isEnableKoodoSync=yes`, the site reads sync data from Koodo's own server (`cloudtest.960960.xyz`), not from the MEGA data source. with no real auth the server returns `invalid params`, and `getSyncData` falls back to EMPTY local storage → **cloud-only books never get pulled**. the fix for "book exists on MEGA but doesn't show": Settings → Sync and backup → turn OFF "Enable Koodo Sync" → resync. this is not a bug — Koodo Sync fundamentally can't work without real auth, so OFF is correct for this fork.
2. **"Adding" toast hanging forever** = `encryptToken` server call returns `{"code":400,"msg":"invalid params"}` because `Authorization: Bearer` is empty (no real Pro token). the patch now catches the bundled-lib TypeError and falls back to local storage, so MEGA/webdav bind works offline.
3. **"Synchronization failed, error code: invalid params"** = `getSyncData`/`updateSyncData` hitting Koodo's server. patch falls back to local storage. if this reappears, verify the configUtil.ts patch is applied.
4. **"Decryption failed, error code: invalid params"** = `decryptToken` trying to decrypt a stored token through the server. patch returns raw JSON tokens directly when they lack the `#` marker.
5. **testConnection "Connection failed" for MEGA in browser** = megajs Blob upload is unreliable in browser. patch skips the real upload test for MEGA and returns true.
6. **Vercel deploy must run the patch**: `build` script is `node patches/apply-patch.js && react-scripts build` — verify a deployed bundle contains `koodo_sync_data` / `9999999999` strings to confirm the patch applied at build time (comments get stripped; check code strings not comments).

## sync / MEGA data layout

- default sync option = MEGA (account `ahmedtouhid88@gmail.com`, password in Bitwarden vault item `mega.nz - ahmedtouhid88`)
- book files live at `/Root/KoodoReader/book/<bookKey>.<format>` — NOT flat in `/Root/KoodoReader/`. if books were imported flat (epub/pdf directly in the KoodoReader folder), the site can't find them; move them into `book/` named by the books.db key.
- library metadata: `/Root/KoodoReader/config/books.db` (sqlite, `books` table: key/name/author/md5/format/size). keys are millisecond timestamps (`Date.now()`).
- sync records: `/Root/KoodoReader/config/sync.json` — book records named `database.sqlite.books.<key>` with `{operation:"save", time:<ms>}`. a book shows up in the app iff it's in books.db AND has a `save` (not `delete`) sync record.
- there's also a `/Root/config/` folder (older sync base) — keep books.db + sync.json in sync across BOTH `/Root/KoodoReader/config/` and `/Root/config/` (symmetric), plus `/Root/KoodoReader/book/` files.
- megatools (scoop) is the CLI for MEGA: `megatools ls/get/put/rm -u <email> -p <pw>`. arg order: `-u/-p` AFTER the subcommand (this build). can't `put` to toplevel `/` — use `/Root`.
- adding a book: download file → compute md5 → `INSERT INTO books (key,name,author,md5,format,size,page,path,charset) VALUES (...)`, `key = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()` → upload file to `book/<key>.<format>` → upload books.db (delete+put to overwrite) → add `database.sqlite.books.<key> = save` to sync.json → do BOTH config folders.

## useful commands

- verify patch applies to clean upstream: `git worktree add /tmp/kwt upstream/dev && (cd /tmp/kwt && git apply --check <repo>/patches/premium-unlock.patch)`
- regenerate patch after editing patched files: `git diff upstream/dev -- src/store/actions/manager.tsx src/utils/common.ts src/utils/file/configUtil.ts src/utils/request/thirdparty.ts src/utils/request/user.ts > patches/premium-unlock.patch` then normalize to LF.
- browser automation of the bind flow: mainframe agent-browser; navigate Settings gear (top bar) → Sync and backup → Add data source → MEGA (Pro) → fill email/password → Bind. `dataSourceList`/`defaultSyncOption` in localStorage confirm the bind.
- MEGA account helper: `automata\mega.nz\mega-account.ps1` (run/upload, vault-backed, stateless).

## deployment

- Vercel project `koodo-reader` on account `koodoshen@outlook.com` (token in Bitwarden `vercel.com - koodoshen`, `vcp_` pattern). production alias = `koodoo.vercel.app` (bare preview URLs show Vercel login page — only the production alias serves publicly).
- deploys automatically from `dev` on push; build runs the premium patch via `prebuild`/`build` scripts.
- after sync/rebuild: hard-refresh or clear site data to avoid stale IndexedDB book state.

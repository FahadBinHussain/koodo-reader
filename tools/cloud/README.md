# cloud surgery tools

Scripts for inspecting and editing the Koodo sync data in MEGA **without a
device** (`tools/cloud/*.py`, stdlib only, need `rclone` and `python` on PATH).

They exist because two classes of bug hurt this library: the sync engine only
pushes what it thinks changed, and a device that has already read the cloud
will push its snapshot straight back. Both are described in `AGENTS.md` gotchas
16 and 17; these are the scripts that verify and repair the cloud side.

## prereqs

1. An **isolated** rclone config holding only `type/user/pass` for the app's
   MEGA account. Build it once with `rclone obscure <password>`:
   ```
   [mega]
   type = mega
   user = <app account email>
   pass = <obscured password>
   ```
   Pass it as `--conf <path>` or export `KOODO_RCLONE_CONF`. Every script fails
   loudly if it is missing — never point these at your default `rclone.conf`,
   which may hold a *different* account's persisted session (see the two-account
   note in `AGENTS.md`: writing to the wrong drive makes the site see nothing).
2. Verify the drive before anything else:
   ```
   rclone --config <conf> lsf mega:/ --dirs-only
   ```
   must print `KoodoReader/` and `config/`.

## before you touch anything

1. **No device sync in flight.** In the header, "Start Transferring Data (n/3)"
   means a tab already read the cloud and will push it back over your edit
   (~1-3 min). Wait for "Synchronisation successful".
2. **Confirm the running bundle is current** (gotcha 17 — a stale tab reverts
   surgery no matter how correct the edit is):
   - `GET https://koodoo.vercel.app/` → `static/js/main.<hash>.js`, compare with
     the tab's `(document.querySelector('script[src*="static/js/main."]')||{}).src`
   - download that bundle and grep `saveAllRecords(`: the fixed build has
     `saveAllRecords(p,"books",!1)` plus three `,o,n,!1)` sites.
   If it is stale, `location.reload()` the tab and re-check.
3. **Backup first** for anything destructive — `cloud-books-db.py --purge-key`
   does it automatically; record where.

## the scripts

| script | what it does |
|--------|--------------|
| `cloud-records.py` | read-only report per config dir: save/delete counts, every delete record, the newest saves, duplicate `sync.json` nodes, and a per-key diff of the two dirs. `--crosscheck` also downloads `books.db` and classifies record/row mismatches: orphan saves (record without a row), rows behind a `delete` record, rows without a `save` record |
| `cloud-set-record.py` | set exactly **one** record on both dirs; asserts that only `--key` changed and that the save/delete totals match `--expect-saves`/`--expect-deletes` before pushing; `--dry-run` prints the plan |
| `cloud-books-db.py` | `--list` / `--count` / `--expect-rows N` (read-only) or `--purge-key <key>` (backup → delete row → VACUUM → force-push → re-download key-set assert) on both dirs |

Typical session:

```sh
export KOODO_RCLONE_CONF=C:/tmp/rclone-mega-iso.conf
python tools/cloud/cloud-records.py                 # what is out there?
python tools/cloud/cloud-records.py --key "database.sqlite.books.<key>"
python tools/cloud/cloud-books-db.py --count
python tools/cloud/cloud-set-record.py --key "database.sqlite.books.<key>" \
    --op delete --expect-saves 51 --expect-deletes 13
python tools/cloud/cloud-books-db.py --purge-key "<key>"
```

## rules these scripts encode

- **Both config dirs, always.** `/KoodoReader/config` and `/config` are written
  by the app at different moments, so a one-dir edit is silently asymmetric.
  Every mutating script ends by asserting the two files are identical.
- **Force route for config files**: `deletefile` → plain `copyto` → re-download
  assert. An edit that preserves byte size (a record flip, `DELETE`+`VACUUM` on
  a same-page-count db) is skipped by a plain copyto with a "Sizes identical"
  success line, and `--update` no-ops while still printing success.
- **Purge duplicate nodes first.** `megajs` creates one node per upload and the
  app resolves them with `find(name === o)`, so a stale duplicate shadows a
  fresh one.
- **Re-verify ~60 s after pushing**, not at t=0.
- **Never push while a sync is in flight** (rule 1 above).
- **The force route has a kill window (hit 2026-10-16).** `deletefile` then
  `copyto` is two commands and the push loop is sequential (`/KoodoReader/config`
  first), so a run killed in between leaves THAT dir with no `sync.json` while
  the other dir still holds its old copy. Nothing is lost — the app's
  missing-record guard aborts loudly instead of pushing — but the app cannot
  sync until it is back. Recovery = push the intact dir's file to the emptied
  side (`copyto mega:/config/sync.json mega:/KoodoReader/config/sync.json`),
  then re-assert both dirs byte-identical plus the record counts. After ANY
  interrupted run, list both config dirs before touching the cloud again.

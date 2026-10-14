"""Read-only report on the koodo cloud sync records in BOTH config dirs.

Prints per dir: save/delete counts, total keys, the value of --key (if given),
every delete record, and the newest save stamps, then diffs the two dirs.

Prereq: an isolated rclone config (type/user/pass only, no other account's
session) passed with --conf or $KOODO_RCLONE_CONF. Fails loudly if missing.

  python cloud-records.py --conf C:/tmp/rclone-mega-iso.conf
  python cloud-records.py --conf ... --key "database.sqlite.books.<key>"
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_DIRS = ("/KoodoReader/config", "/config")


def ts(ms):
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", default=os.environ.get("KOODO_RCLONE_CONF"))
    ap.add_argument("--rclone", default=shutil.which("rclone"))
    ap.add_argument("--dir", action="append", dest="dirs", default=None,
                    help="config dir on the remote (repeatable)")
    ap.add_argument("--key", help="print this exact record key's value")
    ap.add_argument("--newest", type=int, default=8, help="how many saves to list")
    ap.add_argument("--crosscheck", action="store_true",
                    help="also download books.db and report record/row mismatches")
    args = ap.parse_args()

    if not args.conf or not os.path.exists(args.conf):
        sys.exit("FAIL: isolated rclone config not found (pass --conf or set KOODO_RCLONE_CONF)")
    if not args.rclone:
        sys.exit("FAIL: rclone not found on PATH")
    dirs = tuple(args.dirs) if args.dirs else DEFAULT_DIRS

    env = dict(os.environ, RCLONE_CONFIG=args.conf)

    def rc(argv, timeout=300):
        return subprocess.run([args.rclone] + argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=timeout)

    parsed = {}
    for cd in dirs:
        dst = os.path.join(tempfile.gettempdir(),
                           "koodo-records-%s.json" % cd.strip("/").replace("/", "-"))
        if os.path.exists(dst):
            os.unlink(dst)
        r = rc(["copyto", "mega:%s/sync.json" % cd, dst])
        if not os.path.exists(dst):
            sys.exit("FAIL: download %s/sync.json rc=%s %s" % (cd, r.returncode, (r.stderr or "")[:200]))
        rec = json.load(open(dst, encoding="utf-8"))
        books = {k: v for k, v in rec.items() if k.startswith("database.sqlite.books.")}
        saves = {k: v for k, v in books.items() if (v or {}).get("operation") == "save"}
        dels = {k: v for k, v in books.items() if (v or {}).get("operation") == "delete"}
        parsed[cd] = rec

        # duplicate nodes make the app's find-by-name pick a stale one
        ls = rc(["lsf", "mega:%s/" % cd, "--files-only"])
        names = [l.strip() for l in (ls.stdout or "").splitlines() if l.strip()]
        dupes = {n: names.count(n) for n in set(names) if names.count(n) > 1}

        print("=== %s  keys=%d  books=%d  saves=%d  deletes=%d  dupes=%s"
              % (cd, len(rec), len(books), len(saves), len(dels), dupes or "none"))
        if args.key:
            print("  %-60s = %s" % (args.key, json.dumps(rec.get(args.key))))
        for k, v in sorted(dels.items(), key=lambda kv: (kv[1] or {}).get("time", 0)):
            print("  delete %s  %s" % (ts((v or {}).get("time")), k[len("database.sqlite.books."):]))
        for k, v in sorted(saves.items(), key=lambda kv: -((kv[1] or {}).get("time", 0)))[:args.newest]:
            print("  save   %s  %s" % (ts((v or {}).get("time")), k[len("database.sqlite.books."):]))

        if args.crosscheck:
            db_path = os.path.join(tempfile.gettempdir(),
                                   "koodo-xcheck-%s.db" % cd.strip("/").replace("/", "-"))
            if os.path.exists(db_path):
                os.unlink(db_path)
            r = rc(["copyto", "mega:%s/books.db" % cd, db_path])
            if not os.path.exists(db_path):
                sys.exit("FAIL: download %s/books.db rc=%s %s" % (cd, r.returncode, (r.stderr or "")[:200]))
            import sqlite3
            con = sqlite3.connect(db_path)
            try:
                rows = {r[0] for r in con.execute("SELECT key FROM books")}
            finally:
                con.close()
            save_keys = {k[len("database.sqlite.books."):] for k in saves}
            del_keys = {k[len("database.sqlite.books."):] for k in dels}
            orphan_saves = sorted(save_keys - rows)      # record says save, no row
            stale_deletes = sorted(rows & del_keys)      # row alive behind a delete record
            no_record = sorted(rows - save_keys)         # row nothing marks as saved
            print("  crosscheck rows=%d  orphan saves=%d  rows behind a delete=%d  rows w/o save record=%d"
                  % (len(rows), len(orphan_saves), len(stale_deletes), len(no_record)))
            for k in orphan_saves:
                print("    orphan save (no row): %s" % k)
            for k in stale_deletes:
                print("    row behind delete record: %s" % k)
            for k in no_record:
                print("    row without save record: %s" % k)

    if len(parsed) == 2:
        a, b = list(parsed.values())
        drift = [k for k in set(a) | set(b)
                 if json.dumps(a.get(k), sort_keys=True) != json.dumps(b.get(k), sort_keys=True)]
        print("dirs differing keys: %d" % len(drift))
        for k in sorted(drift)[:20]:
            print("  %-66s A=%s  B=%s" % (k, json.dumps(a.get(k)), json.dumps(b.get(k))))
    print("DONE")


if __name__ == "__main__":
    main()

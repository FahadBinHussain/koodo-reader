"""Set exactly ONE sync record on BOTH config dirs (idempotent, force-routed).

Usage:
  python cloud-set-record.py --conf <rclone conf> --key database.sqlite.books.<k> \
      --op delete [--time <ms>] [--dry-run]
  python cloud-set-record.py --conf ... --key ... --op save --time <ms> --expect-deletes 13

The force route is deletefile -> plain copyto -> re-download assert: an edited
sync.json that keeps the exact same byte size is silently skipped by a plain
copyto ("Sizes identical"), so a push must always delete the node first. Never
use --update, it no-ops while printing success.

It refuses to push while ANY dir's record differs from the target in a way it
did not just change (asserts that only the --key moved), and refuses to push at
all when --expect-saves/--expect-deletes are given and the counts do not match.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_DIRS = ("/KoodoReader/config", "/config")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", default=os.environ.get("KOODO_RCLONE_CONF"))
    ap.add_argument("--rclone", default=shutil.which("rclone"))
    ap.add_argument("--dir", action="append", dest="dirs", default=None)
    ap.add_argument("--key", required=True, help="full record key, e.g. database.sqlite.books.<key>")
    ap.add_argument("--op", required=True, choices=["save", "delete", "update"])
    ap.add_argument("--time", type=int, help="epoch ms (default: keep existing time if op unchanged, else now)")
    ap.add_argument("--expect-saves", type=int)
    ap.add_argument("--expect-deletes", type=int)
    ap.add_argument("--dry-run", action="store_true")
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

    def download(cd, tag):
        dst = os.path.join(tempfile.gettempdir(),
                           "koodo-setrec-%s-%s.json" % (cd.strip("/").replace("/", "-"), tag))
        if os.path.exists(dst):
            os.unlink(dst)
        r = rc(["copyto", "mega:%s/sync.json" % cd, dst])
        if not os.path.exists(dst):
            sys.exit("FAIL: download %s/sync.json rc=%s %s" % (cd, r.returncode, (r.stderr or "")[:200]))
        return dst, json.load(open(dst, encoding="utf-8"))

    plans = []
    for cd in dirs:
        # duplicate sync.json nodes shadow each other in the app: purge first
        ls = rc(["lsf", "mega:%s/" % cd, "--files-only"])
        names = [l.strip() for l in (ls.stdout or "").splitlines() if l.strip()]
        dupes = [n for n in set(names) if names.count(n) > 1 and n == "sync.json"]
        if dupes and not args.dry_run:
            print("purging duplicate sync.json nodes in %s" % cd)
            while True:
                ls = rc(["lsf", "mega:%s/" % cd, "--files-only"])
                names = [l.strip() for l in (ls.stdout or "").splitlines() if l.strip()]
                if names.count("sync.json") <= 1:
                    break
                rc(["deletefile", "mega:%s/sync.json" % cd])

        path, rec = download(cd, "pre")
        before = dict(rec)
        cur = rec.get(args.key)
        target_time = args.time
        if target_time is None:
            target_time = (cur or {}).get("time")
            if not cur or cur.get("operation") != args.op:
                import time
                target_time = int(time.time() * 1000)
        rec[args.key] = {"operation": args.op, "time": target_time}

        books = {k: v for k, v in rec.items() if k.startswith("database.sqlite.books.")}
        saves = sum(1 for v in books.values() if (v or {}).get("operation") == "save")
        dels = sum(1 for v in books.values() if (v or {}).get("operation") == "delete")
        print("%s  before: %s  after: %s" % (cd, cur, rec[args.key]))
        if args.expect_saves is not None and saves != args.expect_saves:
            sys.exit("FAIL: %s would have saves=%d, expected %d" % (cd, saves, args.expect_saves))
        if args.expect_deletes is not None and dels != args.expect_deletes:
            sys.exit("FAIL: %s would have deletes=%d, expected %d" % (cd, dels, args.expect_deletes))
        changed = [k for k in set(before) | set(rec)
                   if json.dumps(before.get(k), sort_keys=True) != json.dumps(rec.get(k), sort_keys=True)]
        # [] is a valid (idempotent) result: the record already holds the target
        if any(k != args.key for k in changed):
            sys.exit("FAIL: %s change set is %s, expected only [%s]" % (cd, changed, args.key))
        print("  books: saves=%d deletes=%d total keys=%d" % (saves, dels, len(rec)))
        plans.append((cd, path, rec, before))

    if args.dry_run:
        print("DRY RUN: nothing pushed")
        return

    for cd, path, rec, before in plans:
        tmp = path + ".push.json"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
        rc(["deletefile", "mega:%s/sync.json" % cd])
        r = rc(["copyto", tmp, "mega:%s/sync.json" % cd])
        if r.returncode != 0:
            sys.exit("FAIL: push %s rc=%s %s" % (cd, r.returncode, (r.stderr or "")[:300]))
        chk_path, chk = download(cd, "post")
        if chk.get(args.key) != rec[args.key]:
            sys.exit("FAIL: %s re-download mismatch %s != %s"
                     % (cd, json.dumps(chk.get(args.key)), json.dumps(rec[args.key])))
        if json.dumps(chk, sort_keys=True) != json.dumps(rec, sort_keys=True):
            sys.exit("FAIL: %s re-download content differs beyond %s" % (cd, args.key))
        print("pushed+verified %s (%s)" % (cd, json.dumps(chk[args.key])))

    # final symmetry: both dirs must be record-for-record identical
    reads = [download(cd, "final")[1] for cd in dirs]
    if json.dumps(reads[0], sort_keys=True) != json.dumps(reads[1], sort_keys=True):
        sys.exit("FAIL: config dirs are not identical after push")
    print("DONE: both dirs identical, %s = %s" % (args.key, json.dumps(reads[0][args.key])))


if __name__ == "__main__":
    main()

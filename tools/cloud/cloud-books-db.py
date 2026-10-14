"""Read or surgically purge a row from books.db in BOTH config dirs.

  python cloud-books-db.py --conf <rclone conf> --list
  python cloud-books-db.py --conf <rclone conf> --count
  python cloud-books-db.py --conf <rclone conf> --purge-key <key>

--purge-key takes a BACKUP FIRST (timestamped dir under --backup-root), then for
each config dir: download -> DELETE the row -> commit -> VACUUM -> force-push
(deletefile -> copyto, because a DELETE+VACUUM often lands on the same byte size
and a plain copyto would skip it as "Sizes identical") -> re-download and assert
the key set.

VACUUM must run AFTER con.commit(): sqlite throws "cannot VACUUM from within a
transaction" otherwise.

Never run this while a device sync is in flight ("Start Transferring Data (n/3)"
in the header, takes ~1-3 min): the tab's already-read snapshot will be pushed
back over the surgery.
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_DIRS = ("/KoodoReader/config", "/config")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", default=os.environ.get("KOODO_RCLONE_CONF"))
    ap.add_argument("--rclone", default=shutil.which("rclone"))
    ap.add_argument("--dir", action="append", dest="dirs", default=None)
    ap.add_argument("--backup-root", default=r"C:\tmp")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--count", action="store_true")
    g.add_argument("--purge-key")
    g.add_argument("--expect-rows", type=int, help="assert row count on every dir, read-only")
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
                           "koodo-booksdb-%s-%s.db" % (cd.strip("/").replace("/", "-"), tag))
        if os.path.exists(dst):
            os.unlink(dst)
        r = rc(["copyto", "mega:%s/books.db" % cd, dst])
        if not os.path.exists(dst):
            sys.exit("FAIL: download %s/books.db rc=%s %s" % (cd, r.returncode, (r.stderr or "")[:200]))
        return dst

    def keys_of(path):
        con = sqlite3.connect(path)
        try:
            return [r[0] for r in con.execute("SELECT key FROM books ORDER BY key")]
        finally:
            con.close()

    backup = None
    if args.purge_key:
        backup = os.path.join(args.backup_root,
                              "koodo-backup-%s-%s" % (int(time.time()), args.purge_key[:40]))
        os.makedirs(backup, exist_ok=True)
        print("backup -> %s" % backup)

    keys_by_dir = {}
    for cd in dirs:
        path = download(cd, "pre")
        ks = keys_of(path)
        keys_by_dir[cd] = ks
        print("%s  rows=%d" % (cd, len(ks)))
        if args.list:
            for k in ks:
                print("  %s" % k)
        if args.purge_key:
            if args.purge_key not in ks:
                sys.exit("FAIL: %s has no row %r" % (cd, args.purge_key))
            shutil.copy2(path, os.path.join(backup, "books-%s.db" % cd.strip("/").replace("/", "-")))
            con = sqlite3.connect(path)
            con.execute("DELETE FROM books WHERE key = ?", (args.purge_key,))
            con.commit()
            con.execute("VACUUM")          # after commit: VACUUM cannot run in a transaction
            con.commit()
            con.close()
            ks2 = keys_of(path)
            if len(ks2) != len(ks) - 1:
                sys.exit("FAIL: %s local delete did not drop exactly one row (%d -> %d)"
                         % (cd, len(ks), len(ks2)))
            keys_by_dir[cd] = ks2

    if args.purge_key:
        for cd in dirs:
            src = os.path.join(tempfile.gettempdir(),
                               "koodo-booksdb-%s-pre.db" % cd.strip("/").replace("/", "-"))
            rc(["deletefile", "mega:%s/books.db" % cd])
            r = rc(["copyto", src, "mega:%s/books.db" % cd])
            if r.returncode != 0:
                sys.exit("FAIL: push %s rc=%s %s" % (cd, r.returncode, (r.stderr or "")[:300]))
            chk = download(cd, "post")
            ks = keys_of(chk)
            if ks != keys_by_dir[cd]:
                sys.exit("FAIL: %s re-download key set mismatch (%d vs %d)"
                         % (cd, len(ks), len(keys_by_dir[cd])))
            if args.purge_key in ks:
                sys.exit("FAIL: %s still has row %r" % (cd, args.purge_key))
            print("pushed+verified %s rows=%d" % (cd, len(ks)))

    if len(keys_by_dir) == 2:
        a, b = list(keys_by_dir.values())
        if a != b:
            sys.exit("FAIL: the two config dirs disagree on row sets (%d vs %d rows)" % (len(a), len(b)))
    if args.count or args.expect_rows is not None:
        for cd in dirs:
            print("%s rows=%d" % (cd, len(keys_by_dir[cd])))
            if args.expect_rows is not None and len(keys_by_dir[cd]) != args.expect_rows:
                sys.exit("FAIL: %s rows=%d, expected %d" % (cd, len(keys_by_dir[cd]), args.expect_rows))
    print("DONE")


if __name__ == "__main__":
    main()

"""Check a dedicated direct-login test job without exposing OAuth values."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import oauth
import sync

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("mode", choices=["arm", "verify"])
parser.add_argument("folder", type=Path)
parser.add_argument("control_digest")
parser.add_argument("payload_digest")
args = parser.parse_args()
folder = args.folder.resolve()
evidence = sync.state() / "live-renewal-check.json"

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

with sync.database() as db:
    jobs = list(db.execute("SELECT * FROM jobs"))
if len(jobs) != 1 or jobs[0]["folder"] != str(folder) or jobs[0]["kind"] != "mirror":
    raise SystemExit("Use a dedicated profile containing only the test mirror.")
job = jobs[0]
if job["paused"] or sync.preference("paused") == "yes":
    raise SystemExit("Test job is paused.")
if digest(folder / "control.txt") != args.control_digest or digest(folder / "roundtrip.txt") != args.payload_digest:
    raise SystemExit("Fixture bytes differ from expected values.")

with oauth.database() as db:
    row = db.execute("SELECT expires,refresh FROM accounts WHERE id=?", (job["account"],)).fetchone()
    if not row or not row["refresh"]:
        raise SystemExit("Test account requires a direct login.")
    if args.mode == "arm":
        if evidence.exists():
            raise SystemExit("A renewal check is already armed.")
        evidence.write_text(json.dumps({"job": job["id"], "updated": job["updated"], "armed": time.time()}))
        db.execute("UPDATE accounts SET expires=0 WHERE id=?", (job["account"],))
    else:
        previous = json.loads(evidence.read_text())
        if previous["job"] != job["id"] or row["expires"] < time.time() + 90:
            raise SystemExit("The direct connection has not renewed.")
        if job["updated"] <= previous["updated"] or job["status"] != "Up to date":
            raise SystemExit("A successful subsequent sync is still pending.")
        evidence.unlink()
print("Renewal check armed." if args.mode == "arm" else "Confirmed renewed token, successful sync and both expected hashes.")

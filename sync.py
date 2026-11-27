"""Persistent, serialized background sync for a logged-in GNOME user."""
import configparser
import contextlib
import csv
import fcntl
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import oauth
from cloud import token_for


def state():
    path = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local/state") / "drive-desk"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path.resolve()


@contextlib.contextmanager
def database():
    with contextlib.closing(sqlite3.connect(state() / "jobs.sqlite", timeout=10)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, account TEXT, kind TEXT, folder TEXT UNIQUE, remote TEXT,
            label TEXT, team TEXT, inode TEXT, initialized INTEGER DEFAULT 0, paused INTEGER DEFAULT 0,
            up INTEGER, down INTEGER, status TEXT DEFAULT 'Waiting', updated INTEGER DEFAULT 0)""")
        db.execute("CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS pins (id TEXT PRIMARY KEY, file_id TEXT, name TEXT)")
        db.execute("""CREATE TABLE IF NOT EXISTS activity (
            seq INTEGER PRIMARY KEY, account TEXT NOT NULL, folder TEXT NOT NULL,
            stamp INTEGER NOT NULL, message TEXT NOT NULL, error INTEGER NOT NULL, unread INTEGER NOT NULL)""")
        yield db


def preference(key, default=""):
    with database() as db:
        row = db.execute("SELECT value FROM settings WHERE name=?", (key,)).fetchone()
        return row[0] if row else default


def configure(key, value):
    with database() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value))


def record_result(db, job, status):
    stamp = int(time.time())
    ok = status == "Up to date"
    db.execute("UPDATE jobs SET initialized=max(initialized,?),status=?,updated=? WHERE id=?",
               (int(ok), status, stamp, job["id"]))
    # Keep changes of outcome. Repeated checks of an idle folder add no activity.
    if status != job["status"]:
        db.execute("INSERT INTO activity(account,folder,stamp,message,error,unread) VALUES(?,?,?,?,?,?)",
                   (job["account"], job["folder"], stamp, status, int(not ok), int(not ok)))
        db.execute("""DELETE FROM activity WHERE account=? AND seq NOT IN
                   (SELECT seq FROM activity WHERE account=? ORDER BY seq DESC LIMIT 500)""",
                   (job["account"], job["account"]))


def overlaps(a, b):
    return a == b or a in b.parents or b in a.parents


def folder_key(path):
    st = path.stat()
    return f"{st.st_dev}:{st.st_ino}"


def check_unique(stream):
    seen = set()
    for row in csv.reader(stream):
        if len(row) != 1:
            raise ValueError("Could not verify the remote folder listing.")
        if row[0] in seen:
            raise ValueError(f"Drive contains duplicate paths: {row[0]}. Rename a duplicate in Drive and retry.")
        seen.add(row[0])


def add_job(account, kind, local, remote, label, team="", up=0, down=0, pin=None):
    folder = Path(local).resolve(strict=True)
    if not folder.is_dir() or overlaps(folder, state()) or kind not in ("pin", "mirror", "backup", "sync local"):
        raise ValueError("Choose a separate local folder outside Drive Desk’s state directory.")
    runtime = Path(os.getenv("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    if overlaps(folder, runtime):
        raise ValueError("Choose a persistent local folder.")
    if kind in ("mirror", "pin") and any(folder.iterdir()):
        raise ValueError("New mirrors require an empty local folder.")
    if kind == "pin":
        if not pin or not re.fullmatch(r"[\w .()-]+", pin[1]) or pin[1] in (".", "..") or pin[1] != pin[1].strip() or pin[1].startswith(".drive-desk-"):
            raise ValueError("This filename requires a folder mirror. Select its parent folder instead.")
    key = uuid.uuid4().hex
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT * FROM jobs"):
            if overlaps(folder, Path(row["folder"])):
                raise ValueError("This folder overlaps an existing job.")
            if kind == row["kind"] == "mirror" and account == row["account"] and (
                    remote == row["remote"] or "root" in (remote, row["remote"])):
                raise ValueError("This Drive folder already belongs to a mirror.")
        db.execute("""INSERT INTO jobs(id,account,kind,folder,remote,label,team,inode,up,down)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (key, account, kind, str(folder), remote, label, team, folder_key(folder), up, down))
        if pin:
            db.execute("INSERT INTO pins VALUES(?,?,?)", (key, *pin))
    return key


def bisync_workdir(work):
    # Older rclone versions included a hash of environment overrides in listing names.
    # Keep the original pair intact and publish both stable names together.
    migrated = work / "stable-listings"
    if migrated.is_dir():
        return migrated
    legacy = list(work.glob("desk{*"))
    if not legacy:
        return work
    first = [p for p in legacy if p.name.endswith(".path1.lst")]
    if len(first) != 1:
        raise ValueError("Ambiguous legacy sync listings. Preserve this folder for review.")
    prefix = first[0].name.removesuffix(".path1.lst")
    second = work / (prefix + ".path2.lst")
    allowed = {p.name + suffix for p in (first[0], second) for suffix in ("", "-old")}
    if (not second.is_file() or any(p.name not in allowed for p in legacy)
            or any(work.glob("desk_*.path*.lst*")) or any(work.glob("*.lck"))):
        raise ValueError("Incomplete or conflicting sync listings. Preserve this folder for review.")
    with tempfile.TemporaryDirectory(dir=work) as temp:
        stage = Path(temp) / "listings"
        stage.mkdir(mode=0o700)
        for src in (first[0], second):
            name, count = re.subn(r"^desk\{[A-Za-z0-9_-]+\}(?=_)", "desk", src.name, count=1)
            if not count:
                raise ValueError("Unrecognized sync listing name.")
            shutil.copy2(src, stage / name)
        stage.rename(migrated)
    return migrated


def transfer(job, destination, env):
    folder = Path(job["folder"])
    if folder_key(folder) != job["inode"]:
        raise ValueError("The local folder was moved, replaced, or unmounted.")
    work = state() / job["id"]
    work.mkdir(mode=0o700, exist_ok=True)
    base = ["rclone", "--config=" + env.get("RCLONE_CONFIG", "/dev/null"), "--retries=1", "--contimeout=15s", "--timeout=2m"]
    cmd = base + ["--verbose"]
    if job["up"] or job["down"]:
        rate = lambda n: str(n) + "k" if n else "off"
        cmd += ["--bwlimit", rate(job["up"]) + ":" + rate(job["down"])]
    if job["kind"] == "backup":
        cmd += ["copy", "--create-empty-src-dirs", str(folder), destination]
    else:
        marker = ".drive-desk-" + job["id"]
        filters = []
        if destination.startswith("desk:") and job["kind"] != "pin" and (
                job["kind"] == "mirror" or job["initialized"]):
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as listing:
                subprocess.run(base + ["lsf", destination, "--recursive", "--csv", "--dir-slash=false"],
                               env=env, stdout=listing, check=True)
                listing.seek(0)
                check_unique(listing)
        if job["kind"] == "pin":
            with database() as db:
                pin = db.execute("SELECT * FROM pins WHERE id=?", (job["id"],)).fetchone()
            name = pin["name"]
            if job["initialized"] and not (folder / name).is_file():
                raise ValueError("The pinned file moved or has a conflict. Review the offline folder.")
            # Confirm identity before either side is writable. Drive allows duplicate names.
            items = subprocess.run(base + ["lsjson", destination, "--max-depth=1", "--files-only",
                                           "--include", "/" + name], env=env, check=True, capture_output=True)
            matches = [i for i in json.loads(items.stdout) if i["Name"] == name]
            if len(matches) != 1 or (destination.startswith("desk:") and matches[0].get("ID") != pin["file_id"]):
                raise ValueError("The pinned Drive item moved, was replaced, or has a duplicate name.")
            filter_path = work / "pin.filters"
            if not filter_path.exists():
                filter_path.write_text(f"+ /{name}\n+ /{marker}\n- **\n")
            filters = ["--filter-from", str(filter_path)]
        cmd += ["bisync", destination, str(folder), "--workdir", str(bisync_workdir(work) if destination.startswith("desk:") else work), "--check-access",
                "--check-filename", marker]
        if filters:
            cmd += ["--filters-file", str(filter_path)]
        if not job["initialized"]:
            started = work / "initial-download"
            if job["kind"] in ("mirror", "pin") and not started.exists() and any(p.name != marker for p in folder.iterdir()):
                raise ValueError("Initial mirror contains files. Preserve them and reconnect an empty folder.")
            # check-access needs the marker on both sides before the first bisync.
            local_marker = folder / marker
            if not local_marker.exists():
                local_marker.write_text(job["id"], encoding="ascii")
            remote_marker = destination + ("" if destination.endswith(":") else "/") + marker
            subprocess.run(base + ["copyto", "--immutable", str(local_marker), remote_marker],
                           env=env, check=True, capture_output=True)
            if job["kind"] in ("mirror", "pin"):
                started.touch()
                # Seed only missing files, then verify both trees before establishing a
                # baseline. A partial download can resume without overwriting local edits.
                common = cmd[:cmd.index("bisync")]
                for args in (["copy", destination, str(folder), "--ignore-existing", "--create-empty-src-dirs"],
                             ["check", destination, str(folder)]):
                    with tempfile.TemporaryFile() as log:
                        seed = subprocess.run(common + filters + args, env=env, stdout=log, stderr=log)
                        if seed.returncode:
                            log.seek(max(0, log.tell() - 1000))
                            raise ValueError("Initial download or verification failed. " +
                                             log.read().decode(errors="replace"))
            cmd += ["--resync", "--immutable"]
        elif not (folder / marker).is_file():
            raise ValueError("Mirror identity file is missing. Check the local folder.")
    # Keep the current and previous transfer logs for the activity viewer.
    log = work / "last-run.log"
    if log.exists():
        log.replace(work / "previous-run.log")
    with log.open("w") as out:
        result = subprocess.run(cmd, env=env, stdout=out, stderr=out)
    if result.returncode:
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 1600))
            tail = stream.read().decode(errors="replace").strip()
        raise ValueError(tail or f"Transfer exited with code {result.returncode}.")


def run():
    os.umask(0o077)
    with (state() / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with database() as db:
            db.execute("UPDATE jobs SET status='Interrupted before completion' WHERE status='Running'")
            ids = [row[0] for row in db.execute("SELECT id FROM jobs WHERE paused=0 ORDER BY updated")]
        for key in ids:
            if preference("paused") == "yes":
                break
            with database() as db:
                job = db.execute("SELECT * FROM jobs WHERE id=? AND paused=0", (key,)).fetchone()
                if not job:
                    continue
                db.execute("UPDATE jobs SET status='Running' WHERE id=?", (key,))
            try:
                ident = job["account"]
                direct = oauth.current_account(ident) if ident.startswith(oauth.PREFIX) else None
                credentials = (oauth.transfer_credentials(direct) if direct else
                               {"token": json.dumps(dict(access_token=token_for(ident), token_type="Bearer"))})
                env = {k: v for k, v in os.environ.items() if not k.startswith("RCLONE_")}
                if preference("proxy") == "direct":
                    env["no_proxy"] = env["NO_PROXY"] = "*"
                config = configparser.RawConfigParser()
                config["desk"] = {"type": "drive", **credentials,
                                  "skip_gdocs": "true", "skip_shortcuts": "true", "use_trash": "true"}
                if job["remote"] != "root":
                    config["desk"]["root_folder_id"] = job["remote"]
                if job["team"]:
                    config["desk"]["team_drive"] = job["team"]
                dest = "desk:" if job["kind"] in ("mirror", "pin") else (
                    ("desk:Drive Desk backups/" if job["kind"] == "backup" else "desk:Drive Desk computers/") +
                    Path(job["folder"]).name + "-" + key[:8])
                # A named config keeps the remote identity stable across token rotations.
                with tempfile.TemporaryDirectory(prefix="drive-desk-") as private:
                    path = Path(private) / "rclone.conf"
                    with path.open("x") as output:
                        config.write(output)
                    env["RCLONE_CONFIG"] = str(path)
                    try:
                        transfer(job, dest, env)
                    finally:
                        if direct:
                            # rclone can renew even if a later file operation fails.
                            with path.open() as updated:
                                config.read_file(updated)
                            oauth.save_transfer_token(direct, json.loads(config["desk"]["token"]))
                status = "Up to date"
            except Exception as exc:
                status = "Needs attention — " + str(exc)
                if job["status"] != status and preference("notifications", "on") == "on":
                    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                        subprocess.run(["notify-send", "Drive Desk", "A folder needs attention. Open Scheduled folders."],
                                       check=False, timeout=5)
            with database() as db:
                record_result(db, job, status)


if __name__ == "__main__":
    run()

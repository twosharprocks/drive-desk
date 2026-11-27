# Live scheduler and OAuth renewal check

Use a dedicated test login with one initialized two-way mirror of a disposable Drive folder. Put two small ordinary files named `roundtrip.txt` and `control.txt` there. Keep the Windows Drive client connected to the same account. Compare SHA-256 for both files across the two computers before starting.

1. Close other Drive Desk windows and stop its scheduler in the test profile. Run `live_renewal.py arm FOLDER CONTROL_SHA256 ORIGINAL_SHA256` using the **installed package's Python, modules and state directory**. It checks the job and both files before marking the app's cached access token due for renewal. It retains the Google grant and requests no new permissions.
2. Append a unique line to the Windows copy of `roundtrip.txt` and calculate its SHA-256. Start Drive Desk with `--background`. Allow time for Windows to upload and for Drive Desk to run its next scheduled cycle. Keep the app's search and storage views closed during this check so only the scheduler requests a token.
3. Run `live_renewal.py verify FOLDER CONTROL_SHA256 WINDOWS_EDIT_SHA256` in the same package context. It checks the refreshed expiry, the job's successful run timestamp, and the downloaded bytes. It does not print tokens. If Windows has not finished propagating the edit, repeat verification after the next scheduled cycle.
4. Append another unique line on Linux. Wait for a subsequent scheduled run, then compare both SHA-256 values in the Windows Drive mount and on Linux. Leave the control file untouched throughout.

For the released Flatpak, copy the helper into the guest user's home and use the following invocation for steps 1 and 3. Supply the real folder and hashes as individual arguments.

```sh
flatpak run --command=python3 --env=PYTHONPATH=/app/share/drive-desk \
  io.github.twosharprocks.DriveDesk//stable \
  "$HOME/live_renewal.py" arm "$folder" "$control_sha256" "$original_sha256"
```

For the strict Snap, copy the helper into `~/snap/drive-desk/common/live-test/`. In the test user's desktop session, open `snap run --shell drive-desk` and use the staged runtime for the helper:

```sh
export XDG_STATE_HOME="$SNAP_USER_COMMON/state"
export PYTHONPATH="$SNAP/share/drive-desk:$SNAP/gnome-platform/usr/lib/python3/dist-packages:$SNAP/usr/lib/python3/dist-packages"
cd "$SNAP_USER_COMMON/live-test"
"$SNAP/snap/command-chain/desktop-launch" /usr/bin/python3 live_renewal.py arm "$folder" "$control_sha256" "$original_sha256"
```

Start the scheduler from a separate shell with `snap run drive-desk --background`. To test the upload first, append the first edit on Ubuntu after arming, wait for Windows to receive it, and use its new digest for `verify`. Then edit the Windows file and wait for the recurring download.

The expiry override exercises a real Google refresh at the start of a run. Expiry during a long transfer and automatic startup after desktop login are separate checks.

## 0.5.0 final checks

The final Debian 13 package, Fedora 44 Flatpak and Ubuntu 24.04.5 strict Snap each passed the 17-test suite against their installed application code. The final Fedora and Ubuntu workers also synchronized their existing disposable mirrors, reported **Up to date**, and preserved the expected payload and control hashes. See [the feature inventory](../FEATURES.md) for the live offline-edit, timer and OAuth renewal checks performed during development.

### Startup after desktop sign-in

On 27 November 2026, the released Fedora 44 Flatpak (stable branch, GNOME/GDM) and Ubuntu 24.04.5 strict Snap (Xfce/LightDM) each started the scheduler in a fresh graphical session. Each test enabled the package’s sign-in preference, staged a new file while the scheduler was stopped, and signed in. The desktop launched Drive Desk with `--background`. Windows received the staged file from each VM and its SHA-256 matched the Linux source. The Ubuntu control file also retained its expected SHA-256. The tests used dedicated users, direct Google connections and disposable selected folders.

### Token expiry during a two-way upload

On Fedora 44, the released Flatpak (rclone 1.76.0) began its throttled upload with 131 seconds of token lifetime remaining. Google accepted the original token at startup. During the run, rclone received HTTP 401 on file operations and aborted. An independent probe also received HTTP 401 for the original token immediately after the run. A fresh token received HTTP 200. Nine of the 32 files reached Drive, all nine remote MD5 checksums matched, and the Windows client also showed nine files. An ordinary retry reported missing prior bisync listings and left the job at **Needs attention**. All 32 local files still matched their original checksums. One intermediate observer request encountered a connection error. The worker log and the probes immediately before and after the run established the authorization failure.

On Ubuntu 24.04.5, the strict Snap (rclone 1.60.1-DEV) started with 144 seconds remaining. While the worker was running, the original token returned HTTP 200 with four matching files already on Drive, then HTTP 401 ten seconds after expiry. The worker stopped with **Needs attention**. A fresh token returned HTTP 200 and showed ten uploaded files, all with matching MD5 checksums. Windows also showed ten files. An ordinary retry reported missing prior bisync listings and left the same ten files on Drive. All 32 local checksums matched. Both test jobs were paused after verification.

The open bug tracks safe renewal or recovery for established two-way mirrors. [Issue #2](https://github.com/twosharprocks/drive-desk/issues/2)

### Repeating the long-transfer check

1. Use a dedicated account profile with the scheduler stopped and the existing jobs paused. Create an empty disposable Drive folder and an empty local folder. Set up a two-way mirror and wait for the initial run to report **Up to date**.
2. Generate 32 distinct 256 KiB files locally and record their MD5 digests. Set the job’s upload limit to 16 KiB/s. Use the real expiry recorded for the direct Google account. Start the installed worker about 145 seconds before expiry so it uses the current token and the queue takes longer than its remaining lifetime.
3. In the test harness, keep the original token in memory. Query Drive with it before expiry and again while the worker is running after expiry. Record only the HTTP status, job state and number of uploaded files. A cached expiry timestamp alone cannot establish when Google stopped accepting the token.
4. Record the first worker result. Obtain a fresh token through the installed client and compare the remote names and MD5 checksums with the local manifest. Remove the test bandwidth limit and run the worker normally once more. Record its status and repeat the checks on both sides. Preserve both copies and the sync listings if the worker requests recovery. Pause the test job when finished.

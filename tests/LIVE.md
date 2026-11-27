# Live scheduler and OAuth renewal check

Use a dedicated test login with one initialized two-way mirror of a disposable Drive folder. Put two small ordinary files named `roundtrip.txt` and `control.txt` there. Keep the Windows Drive client connected to the same account. Compare SHA-256 for both files across the two computers before starting.

1. Close other Drive Desk windows and stop its scheduler in the test profile. Run `live_renewal.py arm FOLDER CONTROL_SHA256 ORIGINAL_SHA256` using the **installed package's Python, modules and state directory**. It checks the job and both files before marking the app's cached access token due for renewal. It retains the Google grant and requests no new permissions.
2. Append a unique line to the Windows copy of `roundtrip.txt` and calculate its SHA-256. Start Drive Desk with `--background`. Allow time for Windows to upload and for Drive Desk to run its next scheduled cycle. Keep the app's search and storage views closed during this check so only the scheduler requests a token.
3. Run `live_renewal.py verify FOLDER CONTROL_SHA256 WINDOWS_EDIT_SHA256` in the same package context. It checks the refreshed expiry, the job's successful run timestamp, and the downloaded bytes. It does not print tokens. If Windows has not finished propagating the edit, repeat verification after the next scheduled cycle.
4. Append another unique line on Linux. Wait for a subsequent scheduled run, then compare both SHA-256 values in the Windows Drive mount and on Linux. Leave the control file untouched throughout.

For a Flatpak test branch, copy the helper into the guest user's home and use the following invocation for steps 1 and 3. Supply the real folder and hashes as individual arguments.

```sh
flatpak run --command=python3 --env=PYTHONPATH=/app/share/drive-desk \
  io.github.twosharprocks.DriveDesk//oauth-test \
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

# Drive Desk 0.3.1

An independent MIT-licensed Google Drive client for Debian 13 with GNOME. Use Drive on demand in Files, or keep selected content on disk and synchronize offline edits. GNOME handles sign-in. The background worker uses Debian’s rclone package internally. Setup is graphical.

**Preview release.** Automated tests cover local transfer behavior. Live Google round-trip verification is pending.

[Download the Debian package and SHA-256 checksum](https://github.com/twosharprocks/drive-desk/releases/tag/v0.3.1).

## Install and connect

1. Open `drive-desk_0.3.1_all.deb` in the package installer, or run `sudo apt install ./drive-desk_0.3.1_all.deb`. This upgrades earlier versions in place. Close any open Drive Desk window before launching the new version.
2. Open **Drive Desk → Online Accounts → Google**, sign in, and enable **Files**. Select that account in Drive Desk.
3. Choose **Open in Files** for online access. **Link to folder** can place a shortcut to the GVfs mount elsewhere on disk. The link works while the account is mounted. The optional Nautilus extension appears in a new Files session.
4. For a small first round trip, create a disposable Drive folder containing two text files. In **Search Drive**, select that folder, choose **Keep offline**, and pick an empty local directory. Wait for **Scheduled folders** to show **Up to date**. Edit one local file offline, reconnect, run the enabled jobs, and compare the file in Drive on the web. Check a change in the opposite direction too.

## Choose a sync mode

| Action | Result |
|---|---|
| Scheduled folders → Mirror My Drive | Downloads ordinary My Drive files into an empty directory and reconciles edits and deletions both ways. |
| Search Drive → Keep offline | Mirrors a selected folder or pins an individual downloadable file into its own empty local directory. For a pin, edit the file under its original name. A rename, missing item or name collision can require review. |
| Scheduled folders → Sync local folder | Publishes an existing local directory under a new folder in My Drive / Drive Desk computers and synchronizes changes both ways. |
| Scheduled folders → Back up | Copies a local directory into My Drive / Drive Desk backups. Subsequent runs upload changes. Local deletions leave remote copies in place. |
| Save an offline copy | Downloads an independent file once. Local edits stay local. The destination must support hard links. |

Jobs run sequentially in a user systemd service about two minutes after the preceding run finishes. The scheduler keeps working after the window closes. An account must have Files enabled, and the session keyring must be accessible. Scheduled mirrors create a small hidden identity file on both sides. Keep it in place. First-time pinning or mirroring therefore requires write access to the selected folder or parent. Avoid overlapping cloud folder trees across jobs.

**Pause / Resume** on a folder changes the next run. **Pause all** also asks systemd to freeze an in-progress transfer. A long pause can cause a network timeout when resumed. **Disconnect** removes the job and retains local and cloud files. Online Accounts controls account access separately. Preferences can disable login scheduling. For removable media, a changed mount identity can require reconnecting the job.

**Search Drive** supports names and indexed content, paginated results, starring, trash/restore, link copying, browser opening, and sharing with a named email address. **Email link** starts a draft in your mail client. **Share and notify** requests an actual Drive permission grant and invitation. The selected account’s existing permissions apply.

## Home and notifications

The main window shows the selected account’s scheduled-folder status and unread transfer errors. Open Notifications to mark displayed errors read. Sync activity records changes in job outcome and retains up to 500 entries per account. Per-file details remain under Scheduled folders → Activity. Pause all transfers applies across accounts to the background scheduler.

## Operations and recovery

Open **Scheduled folders → Activity** to inspect the last two run logs. **Storage** shows local folder usage, free disk space and Google account usage when accessible. Jobs, sync listings and logs are stored in `$XDG_STATE_HOME/drive-desk` (default `~/.local/state/drive-desk`). The app requests an access token from GNOME per worker run and passes it to the transfer process in its environment. Provider errors and expired tokens can interrupt transfers. The scheduler obtains another token on a later run.

If a job reports a missing marker, disconnected disk, duplicate name or invalid baseline, preserve the local folder and inspect Activity. Reconnect the original disk or resolve duplicate names on Drive where applicable. If the sync engine requires a fresh baseline, pause the job, keep the existing tree, disconnect, and create a fresh mirror in a separate empty folder. Compare and recover any offline-only files before removing old data. Drive Desk never automatically forces a resync of an established mirror.

Native Docs, Sheets, Slides and Drive shortcuts are excluded from scheduled binary-file transfers. Open Google-native files through Search or Drive on the web. Empty directories can differ across sync engine versions. Single-file pins support names containing letters, digits, spaces, dots, hyphens, underscores and parentheses. Folder mirroring supports more names. For an overview of the Windows comparison and known gaps, read [the feature inventory](FEATURES.md).

## Build and test

On Debian, run `sh build-deb.sh` to build the package. With its runtime dependencies, Xvfb, xauth and dbus-daemon installed, run `python3 test_sync.py` followed by `NO_AT_BRIDGE=1 dbus-run-session -- xvfb-run -a python3 test_drive_desk.py`. The transfer tests use disposable local directories. No Google credentials are required. To remove the package, use the system package manager. To stop ongoing work first, pause or disconnect jobs in the app.

## Windows comparison baseline

The signed Google Drive Windows 134.0.1.0 installer inspected on 26 November 2026 had SHA-256 `2e723b70b0f6693fb4c9b5e63dc1f484e4874f5a8cbdd2c28c5c392517f95f8e`. Its x64 client and Explorer extension import Windows Shell and COM libraries. Drive Desk uses the public Drive API and Linux desktop services. [Google desktop guide](https://support.google.com/drive/answer/10838124) · [GNOME account setup](https://help.gnome.org/gnome-help/accounts-add.html) · [rclone bisync](https://rclone.org/bisync/)

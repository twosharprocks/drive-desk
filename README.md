# Drive Desk for Linux

Drive Desk is an independent, MIT-licensed Google Drive desktop client for Linux. Keep a selected folder available offline, sync edits between computers, or open Drive on demand in GNOME Files. To sync one project folder, choose **Search Drive → Keep offline** and select that folder. Setup is graphical and Drive Desk runs rclone internally.

**Project status:** Maintenance is paused. The MIT-licensed source, build instructions and preview installers are public. There is no scheduled support or release cycle.

## Download Drive Desk 0.5.1 (preview)

| Package | Download | Tested environment |
|---|---|---|
| Flatpak (x86-64) | [Download .flatpak](https://github.com/twosharprocks/drive-desk/releases/download/v0.5.1/DriveDesk-0.5.1-x86_64.flatpak) | Fedora 44. Direct sign-in, offline edits, unattended sync and token renewal verified in the 0.5 development cycle. |
| Snap (amd64, strict confinement) | [Download .snap](https://github.com/twosharprocks/drive-desk/releases/download/v0.5.1/drive-desk_0.5.1_amd64.snap) | Ubuntu 24.04.5. Direct sign-in, offline edits, unattended sync and token renewal verified in the 0.5 development cycle. |
| Debian package | [Download .deb](https://github.com/twosharprocks/drive-desk/releases/download/v0.5.1/drive-desk_0.5.1_all.deb) | Debian 13 with GNOME. The GNOME connection previously passed a live selected-folder round trip with Windows. |

[Preview release notes](https://github.com/twosharprocks/drive-desk/releases/tag/v0.5.1) · [SHA-256 checksums](https://github.com/twosharprocks/drive-desk/releases/download/v0.5.1/SHA256SUMS)

## Connect directly to Google Drive

Use this option for search and selected-folder sync, including on Fedora 44. Each user needs a Desktop app OAuth client from a Google Cloud project they control. In Google Cloud, enable the Google Drive API, configure the consent screen, select a testing audience, add your Google address as a test user and download a Desktop app client JSON. Keep this file private.

Choose **Connect Google Drive…** and select a Desktop app client JSON for a Google Cloud project with the Drive API enabled. For a project in testing, add your Google address to the OAuth test audience. Google opens in your browser and asks for Drive access so the app can read and update existing files. After connecting, choose **Search Drive → Keep offline** and select the folder you want to sync. Connecting alone creates no sync jobs. [Google desktop authorization setup](https://developers.google.com/identity/protocols/oauth2/native-app)

The selected account appears with **(direct)** in its name. Search and the scheduler use this connection. Files integration still requires a GNOME Files-enabled account. Direct authorization credentials are stored locally, unencrypted, in an owner-only database under the package’s Drive Desk state directory. **Forget connection** removes the local connection. Use your Google Account’s connected-app settings to revoke the grant at Google.

## Verification and remaining work

The Fedora Flatpak and Ubuntu Snap completed live round trips with Google Drive for Windows using one disposable folder. Both renewed a Google token at the start of a background run. The released 0.5.0 packages also started automatically after desktop sign-in and uploaded a pending file whose SHA-256 matched on Windows.

In 0.5.1, the Fedora Flatpak and Ubuntu strict Snap each uploaded 32 of 32 files on the first run while the original Google token expired. The renewed direct connection kept the mirror up to date, and every remote checksum matched. If a mirror already reported missing sync listings in 0.5.0, pause the job and preserve both copies before following **Operations and recovery**. [Issue #2](https://github.com/twosharprocks/drive-desk/issues/2) · [Test procedure](tests/LIVE.md) · [Feature coverage and verification history](FEATURES.md)

## Install and connect

Choose one format. The portable downloads target x86-64 Linux desktops. On-demand browsing in GNOME Files requires the host GVfs Google backend and a Google account with Files enabled. Each format stores its jobs separately. If you switch formats, disconnect the old job before assigning the same folder to the new one.

**Flatpak** (with Flatpak installed):

```sh
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user ./DriveDesk-0.5.1-x86_64.flatpak
flatpak run io.github.twosharprocks.DriveDesk//stable
```

Flathub supplies the GNOME 50 runtime. The Drive Desk installer comes from GitHub. Its sandbox has network and home-folder access for sync, removable mount access, and access to the desktop account and file services.

**Snap** (with snapd installed):

```sh
sudo snap install --dangerous ./drive-desk_0.5.1_amd64.snap
snap run drive-desk
```

The local installer uses strict confinement. Snap calls its local installation flag `--dangerous` because the GitHub download has no Snap Store assertion. For a GNOME Google login, also run `sudo snap connect drive-desk:accounts-service`. For external disks, also run `sudo snap connect drive-desk:removable-media`. The first install may download shared GNOME content snaps.

**Debian 13**: Open `drive-desk_0.5.1_all.deb` in your package installer or run `sudo apt install ./drive-desk_0.5.1_all.deb`. Close any open Drive Desk window before upgrading.

### Connect through GNOME Online Accounts

1. Open **Drive Desk → Online Accounts → Google**, sign in, and enable **Files**. Select that account in Drive Desk.
2. Choose **Open in Files** for online access. **Link to folder** can place a shortcut to the GVfs mount elsewhere on disk. The link works while the account is mounted. The Debian package also supplies an optional host Nautilus extension. For either sandboxed package, you can access the same web and link actions in Drive Desk search.
3. For a small first round trip, create a disposable Drive folder containing two text files. In **Search Drive**, select that folder, choose **Keep offline**, and pick an empty local directory. Wait for **Scheduled folders** to show **Up to date**. Edit one local file offline, reconnect, run the enabled jobs, and compare the file in Drive on the web. Check a change in the opposite direction too.

## Choose a sync mode

| Action | Result |
|---|---|
| Scheduled folders → Mirror My Drive | Downloads ordinary My Drive files into an empty directory and reconciles edits and deletions both ways. |
| Search Drive → Keep offline | Mirrors a selected folder or pins an individual downloadable file into its own empty local directory. For a pin, edit the file under its original name. A rename, missing item or name collision can require review. |
| Scheduled folders → Sync local folder | Publishes an existing local directory under a new folder in My Drive / Drive Desk computers and synchronizes changes both ways. |
| Scheduled folders → Back up | Copies a local directory into My Drive / Drive Desk backups. Subsequent runs upload changes. Local deletions leave remote copies in place. |
| Save an offline copy | Downloads an independent file once. Local edits stay local. The destination must support hard links. |

Jobs run sequentially about two minutes after the preceding run finishes. Debian uses a user systemd service. Flatpak and Snap keep a background application instance while jobs are scheduled. For automatic startup after logout and sign-in, enable **Preferences → Start folder scheduler at sign-in** and accept the desktop background permission if prompted. The scheduler keeps working after the window closes. For GNOME accounts, enable Files and unlock the session keyring. Direct connections use the locally stored OAuth grant. Scheduled mirrors create a small hidden identity file on both sides. Keep it in place. First-time pinning or mirroring therefore requires write access to the selected folder or parent. Avoid overlapping cloud folder trees across jobs.

**Pause / Resume** on a folder changes the next run. **Pause all** can also suspend an in-progress transfer. A long pause can cause a network timeout when resumed. **Disconnect** removes the job and retains local and cloud files. Online Accounts controls account access separately. Preferences can disable login scheduling. For removable media, a changed mount identity can require reconnecting the job.

**Search Drive** supports names and indexed content, paginated results, starring, trash/restore, link copying, browser opening, and sharing with a named email address. **Email link** starts a draft in your mail client. **Share and notify** requests an actual Drive permission grant and invitation. The selected account’s existing permissions apply.

## Home and notifications

The main window shows the selected account’s scheduled-folder status and unread transfer errors. Open Notifications to mark displayed errors read. Sync activity records changes in job outcome and retains up to 500 entries per account. Per-file details remain under Scheduled folders → Activity. Pause all transfers applies across accounts to the background scheduler.

## Operations and recovery

Open **Scheduled folders → Activity** to inspect the last two run logs. **Storage** shows local folder usage, free disk space and Google account usage when accessible. Jobs, sync listings and logs are stored in `$XDG_STATE_HOME/drive-desk` (default `~/.local/state/drive-desk`). For direct Google connections, rclone gets the current access token and a temporary, per-job key in an owner-only configuration. When a token approaches expiry, rclone uses the key to request another token from Drive Desk over the loopback interface. Drive Desk renews the Google grant and saves it in the account database. The worker allows five minutes for outstanding requests to finish with the old token. The loopback listener and temporary configuration last only for the job. The stable remote name preserves the mirror's sync history across renewals. GNOME Online Accounts supplies a session access token and manages its own grant. Mid-transfer renewal with that connection is unverified.

If a job reports a missing marker, disconnected disk, duplicate name or invalid baseline, preserve the local folder and inspect Activity. Reconnect the original disk or resolve duplicate names on Drive where applicable. If the sync engine requires a fresh baseline, pause the job, keep the existing tree, disconnect, and create a fresh mirror in a separate empty folder. Compare and recover any offline-only files before removing old data. Drive Desk never automatically forces a resync of an established mirror.

Native Docs, Sheets, Slides and Drive shortcuts are excluded from scheduled binary-file transfers. Open Google-native files through Search or Drive on the web. Empty directories can differ across sync engine versions. Single-file pins support names containing letters, digits, spaces, dots, hyphens, underscores and parentheses. Folder mirroring supports more names. For an overview of the Windows comparison and known gaps, read [the feature inventory](FEATURES.md).

## Build and test

Portable package build commands are in [the packaging guide](packaging/BUILD.md). On Debian, run `sh build-deb.sh` to build the package. With its runtime dependencies, Xvfb, xauth and dbus-daemon installed, run `NO_AT_BRIDGE=1 xvfb-run -a dbus-run-session -- python3 -m unittest discover -v`. The transfer tests use disposable local directories. No Google credentials are required. To remove the package, use the system package manager. To stop ongoing work first, pause or disconnect jobs in the app.

## Windows comparison baseline

The signed Google Drive Windows 134.0.1.0 installer inspected on 26 November 2026 had SHA-256 `2e723b70b0f6693fb4c9b5e63dc1f484e4874f5a8cbdd2c28c5c392517f95f8e`. Its x64 client and Explorer extension import Windows Shell and COM libraries. Drive Desk uses the public Drive API and Linux desktop services. [Google desktop guide](https://support.google.com/drive/answer/10838124) · [GNOME account setup](https://help.gnome.org/gnome-help/accounts-add.html) · [rclone bisync](https://rclone.org/bisync/)

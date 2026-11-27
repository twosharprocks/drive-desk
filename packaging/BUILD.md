# Build the Linux installers

Run these commands from the root of a clean Drive Desk checkout. Both portable packages target x86-64. Direct sign-in uses the user’s Google Desktop app OAuth client. GNOME account integration is also available. Build from tracked release sources and keep personal OAuth files outside the source tree.

## Flatpak

Install Flatpak and flatpak-builder with the distribution package manager. The manifest pins the bundled rclone download by SHA-256.

```sh
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.gnome.Platform//50 org.gnome.Sdk//50
flatpak-builder --user --disable-rofiles-fuse --default-branch=stable --force-clean \
  --repo=flatpak-repo flatpak-build io.github.twosharprocks.DriveDesk.json
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  flatpak-repo DriveDesk-0.5.0-x86_64.flatpak io.github.twosharprocks.DriveDesk stable
```

## Snap

Install Snapcraft, then run `snapcraft pack` in an environment with a supported build provider. The recipe targets Ubuntu core24 and uses the GNOME extension. For a dedicated, disposable Ubuntu 24.04 build VM, `sudo snapcraft pack --destructive-mode` uses the VM directly. The build outputs `drive-desk_0.5.0_amd64.snap`. Snapcraft stages rclone from the Ubuntu archive.

## Desktop integration

The portable packages request folder and account access to synchronize jobs. Flatpak uses the desktop background portal for login startup. Snap uses its per-user autostart desktop entry. Both keep the worker inside their own confinement. Neither installs a file manager extension into the host. Use **Search Drive** for web and link actions. If the desktop blocks the Settings shortcut, open **Settings → Online Accounts** directly.

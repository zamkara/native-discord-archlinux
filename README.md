# Native Discord for Arch Linux

Native Arch Linux / Omarchy packages built from Discord's official Linux tarballs.
Stable, PTB, Canary and Development are released together, with an installer and
a small terminal interface for choosing a channel. No AUR package or patched
third-party client is used.

Discord's official updater installs and updates the actual application directly
from Discord. The TUI deliberately has no application-update command. Packages
contain the official bootstrap and native desktop integration; this project does
not compile Discord's proprietary source or freeze the downloaded app at the
bootstrap version.

## Install

After the first successful Actions release:

```sh
curl -fsSL https://github.com/zamkara/native-discord-archlinux/releases/latest/download/install.sh | bash
```

Choose Development on first install:

```sh
curl -fsSL https://github.com/zamkara/native-discord-archlinux/releases/latest/download/install.sh | bash -s -- development
```

Run as your regular user. Downloads and checksums are processed without root;
only dependency/package transactions request `sudo`. Confirmation reads from
`/dev/tty`, so piping the installer cannot consume a pacman confirmation prompt.
Arch Linux, x86_64, Python, curl and an interactive terminal are required. Install
missing Python/curl with `sudo pacman -S --needed python curl` first. Keep your
system fully upgraded through your usual Arch/Omarchy update procedure.

## Use

```sh
native-discord                    # Terminal interface
native-discord -i development     # Install the native channel integration
native-discord -s development     # Set the default channel
native-discord -o                 # Open the selected channel
native-discord -o canary          # Open a specific channel
native-discord -l                 # Show installed channels
native-discord -r ptb             # Remove one native channel package
```

In the TUI: arrows select a row; Enter sets the default; `i` installs; `o` opens;
`r` removes; `q` exits. Install/remove progress, transaction plans, cancellation,
errors and masked administrator-password prompts stay inside the TUI. Confirm a
package plan with `y`, or cancel with `n` / Escape; long plans scroll with
Page Up / Page Down. Downloads do not require administrator privileges. Running
transactions must finish before the TUI can close. Opening Discord leaves the
TUI running and writes application output to a private channel log under
`$XDG_STATE_HOME/native-discord` or `~/.local/state/native-discord`.
The CLI keeps pacman's normal terminal prompts. Current or newer integration
packages are not reinstalled or downgraded when choosing another channel.
Terminal colors are inherited. There is no idle service,
update timer or background watcher. Each channel also has its own application
menu entry. Multiple channels may coexist; changing the default does not copy
credentials, change another channel's profile, or close running applications.

On first launch, the exact packaged official `updater_bootstrap` downloads the
application into the channel's normal Discord user configuration directory.
The bootstrap's returned application path is checked before execution. Subsequent
app updates remain Discord's responsibility. A newer app can appear before this
repository's next scheduled build; that is expected and requires no TUI action.
Re-running the installer refreshes this project's package integration if needed.
It does not replace Discord's updater.

The package list distinguishes the bootstrap version from the actual app version.
The latter is read from Discord's per-user app data when available. Do not run
Discord as root. Existing Discord profiles may be reused by the same official
channel; no existing profile is deleted or silently migrated.

## Automated releases

The workflow runs daily at **03:00 America/Los_Angeles**, with daylight-saving
time handled by GitHub Actions. This timezone is a project choice based on
Discord's San Francisco location, not a claim that Discord publishes at a fixed
hour. GitHub schedules are best-effort and can be delayed; public repositories'
schedules may be disabled after 60 days of inactivity. Manual dispatch and pushes
to `main` also trigger the workflow. Pull requests run validation only.

Every run downloads the current official tarball for all four channels, records
the resolved URL, version and SHA-256, and hashes those inputs together with the
full builder commit. An identical **complete** release skips packaging and
publication. Changed archives, even under an unchanged version, are detected by
content hash. Network/authentication failures do not count as unchanged inputs.
An unavailable channel or unsupported archive layout fails the suite; no partial
set is published.

Builds run as an unprivileged user inside an updated Arch Linux container. All
five packages are installed, checked and uninstalled in that disposable container
before publishing. Discord itself is never started as root. Published releases
are not prereleases. A draft is used only while uploading/validating all assets;
it is published only after the full upload succeeds.

Each release includes:

- Four `native-discord-CHANNEL-*.pkg.tar.zst` packages.
- `native-discord-manager-*.pkg.tar.zst` and the executable `native-discord` CLI.
- `install.sh`, `catalog.json`, `SHA256SUMS` and reproducible `PKGBUILDS.zip`.
- A release-specific one-line installation command.

The package recipes pin official archive SHA-256 values. The installer pins one
GitHub release and verifies the manager, catalog and packages before executing or
installing them. SHA-256 protects download integrity; it is not a publisher
signature and does not protect against compromise of the release repository.

Discord also currently advertises an official Arch package on its download page.
This builder intentionally uses the requested official tarballs for consistent
four-channel packaging and a channel-selector TUI. It is not endorsed by Discord.
Only x86_64 archives were verified; no ARM build is claimed.

## Remove

Use `native-discord -r CHANNEL` to remove one integration package. To remove all:

```sh
sudo pacman -R native-discord-stable native-discord-ptb native-discord-canary native-discord-development native-discord-manager
```

List only packages you installed. Removal preserves Discord profiles, downloads,
accounts and the selected-channel preference. After closing Discord, you can
manually remove `~/.config/native-discord` and any unwanted official channel
profile: `discord`, `discordptb`, `discordcanary`, `discorddevelopment` beneath
`$XDG_CONFIG_HOME` or `~/.config`. Those directories may predate this project;
inspect them before deleting anything. No uninstall script deletes user data.

## Repository and validation

Only `README.md`, `LICENSE` and `.github/` live at the root. All implementation,
tests, workflow files and documentation are under `.github/workflows/`.
Downloaded archives and build products stay in ignored `.github/workflows/.build/`.

```sh
python3 -m unittest discover -s .github/workflows/native-discord/tests -v
```

See [.github/workflows/native-discord/VALIDATION.md](.github/workflows/native-discord/VALIDATION.md)
for measured validation and remaining limits.

Builder code is licensed under the [Almatera Incubator License](LICENSE).
Discord binaries, trademarks and downloaded app data retain Discord's own terms
and licenses; they are not relicensed under Almatera.

References: [official downloads](https://discord.com/download),
[company information](https://discord.com/company-information),
[GitHub schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

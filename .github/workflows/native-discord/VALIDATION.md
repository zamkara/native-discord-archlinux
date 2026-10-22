# Validation

Date: 2026-10-22. These results distinguish local checks from GitHub execution.

## Completed locally

- 21 Python tests passed with no skips. Coverage includes archive traversal,
  symlink/device rejection, channel/ELF checks, checksums, incomplete release
  rejection, unchanged-release skip, isolated channel selection, official updater
  handoff, terminal confirmation and clean root layout.
- actionlint v1.7.12 accepted the workflow, including its timezone-aware schedule.
- Python compilation and `bash -n` accepted all implementation scripts.
- Five native packages were built using makepkg/fakeroot on Arch without installing
  Discord on the host. Their release catalog and all ten assets passed SHA-256
  verification.
- Packaged bootstrap binaries for all four channels were compared byte-for-byte
  with the official downloaded archives and matched.
- The curses interface opened in a real pseudo-terminal and exited normally.
- The real official Development bootstrap was run in an isolated temporary user
  directory, without opening Discord or using an account. Original completion:

```text
Install Complete
app-1.0.1017
```

- The CLI's actual bootstrap handoff was exercised using that temporary profile,
  intercepting only the final exec to avoid launching the GUI. Original output:

```text
Install Complete
Official Development bootstrap handoff: PASS
Resolved app: DiscordDevelopment version app-1.0.1017
GUI not launched; no account used; host packages unchanged.
```

Official inputs tested:

| Channel | Bootstrap | SHA-256 |
| --- | --- | --- |
| Stable | 1.0.165 | 78cdfea36589f7ebb7471476007d6084fbaaea379828ed81cf970fb1c40678b6 |
| PTB | 1.0.222 | e177f14e3ccae1672b701cb9dce7df05cffa81f7c0d7ce8fa7928aed862a2578 |
| Canary | 1.0.2334 | 33aaa9e9a7a12d6226c9a1c4ccabd4d6345fa8b31c7696cc47964dc39ba4e6ad |
| Development | 1.0.1017 | cea04e2acef611bb15c7d2c99f8fd594fde89cea777b68399c0663b20a61fb70 |

## Release gate

The workflow repeats the build in a fresh updated Arch container, installs and
verifies all five packages, checks bootstrap shared libraries and desktop files,
then uninstalls the suite. Publication depends on this job succeeding. A local
container run is also in progress; no completed result is claimed here yet.
GitHub publication is not claimed until the first workflow completes.

## Not claimed

- Logged-in Discord behavior, calls, screen sharing, GPU acceleration, tray behavior,
  and updating an already-running app have not been tested with an account.
- Full first-launch bootstrap was tested for Development; archive layout and
  packaged bootstrap integrity were tested for all four channels.
- ARM support is not implemented because the requested official Linux tarball
  inputs verified here are x86_64.
- Scheduled Actions execution at the next 03:00 boundary is not yet observed.
  GitHub may delay schedules or disable inactive public-repository schedules.
- Checksums are integrity checks, not an independent signature of the publisher.
- Actual application versions are owned by Discord's updater and may exceed the
  pinned bootstrap package version; this is intentional.

#!/usr/bin/env python3
"""Publish a verified complete suite; a partial upload is never made public."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from common import CHANNELS, gh_json, repository, sha256


def validate(root):
    manifest={}
    for line in (root/'SHA256SUMS').read_text().splitlines():
        m=re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.+\-]+)',line)
        if not m or m[2] in manifest:raise ValueError('Invalid release checksum manifest')
        manifest[m[2]]=m[1]
    for name,digest in manifest.items():
        if sha256(root/name)!=digest:raise ValueError('Checksum mismatch: '+name)
    catalog=json.loads((root/'catalog.json').read_text())
    if set(catalog['packages'])!={'manager',*CHANNELS}:raise ValueError('The complete four-channel suite is required')
    required={'catalog.json','install.sh','native-discord','PKGBUILDS.zip',*catalog['packages'].values()}
    if not required<=manifest.keys():raise ValueError('Incomplete release')
    return catalog


def publish(root, repo, revision):
    catalog=validate(root);repo=repository(repo);tag=catalog['tag']
    if catalog['repository']!=repo or catalog['builder']!=revision:raise ValueError('Release identity mismatch')
    release=gh_json('api',f'repos/{repo}/releases/tags/{tag}')
    if release and not release.get('draft'):
        raise RuntimeError('This release already exists; refusing to overwrite a published release')
    note=root.parent/'release-notes.md'
    lines=['Official Discord clients packaged for Arch Linux / Omarchy.','',
           'Install or refresh the native integration (Stable by default):','',
           f'```sh\ncurl -fsSL https://github.com/{repo}/releases/download/{tag}/install.sh | bash\n```','',
           'Choose another channel with `native-discord`. Discord updates its app directly from its official servers; the TUI has no app updater.','',
           '| Channel | Official bootstrap version |','| --- | --- |']
    lines += [f"| {a['channel']} | {a['version']} |" for a in catalog['channels']]
    lines += ['',f'Builder commit: `{revision}`',f"Suite SHA-256: `{catalog['digest']}`",'',
              'These are official proprietary binaries repackaged into native Arch packages, not a source rebuild or a Discord-endorsed release. Discord’s own licenses apply to Discord; the Almatera license applies to this builder.']
    note.write_text('\n'.join(lines)+'\n')
    if not release:
        subprocess.run(['gh','release','create',tag,'--repo',repo,'--target',revision,'--draft',
                        '--title','Native Discord '+catalog['digest'][:12],
                        '--notes-file',str(note)],check=True)
    subprocess.run(['gh','release','upload',tag,'--repo',repo,'--clobber',
                    *map(str,sorted(root.iterdir()))],check=True)
    staged=gh_json('api',f'repos/{repo}/releases/tags/{tag}')
    remote={a['name']:a['size'] for a in staged['assets']}
    for path in root.iterdir():
        if remote.get(path.name)!=path.stat().st_size:raise RuntimeError('Incomplete upload: '+path.name)
    subprocess.run(['gh','release','edit',tag,'--repo',repo,'--draft=false','--prerelease=false','--latest'],check=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    p.add_argument('--repository',required=True);p.add_argument('--revision',required=True)
    a=p.parse_args();publish(a.root,a.repository,a.revision)

#!/usr/bin/env python3
"""Download official archives, pin their hashes and skip an unchanged complete suite."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile

from common import CHANNELS, download, gh_json, repository, sha256


def describe(path, channel, url):
    folder, launcher, _, _=CHANNELS[channel]
    with tarfile.open(path,'r:*') as archive:
        members={m.name.rstrip('/'):m for m in archive.getmembers()}
        for name in (launcher,'updater_bootstrap','discord.png'):
            m=members.get(folder+'/'+name)
            if m is None or not m.isfile():raise ValueError(f'{channel}: upstream layout changed: {name}')
        body=archive.extractfile(members[folder+'/'+launcher]).read().decode()
        if not re.search(r'^CHANNEL='+re.escape(channel)+r'\s*$',body,re.M):
            raise ValueError(f'{channel}: launcher channel mismatch')
        boot=archive.extractfile(members[folder+'/updater_bootstrap']).read(20)
        if boot[:4]!=b'\x7fELF' or int.from_bytes(boot[18:20],'little')!=62:
            raise ValueError('Only an official Linux x86_64 bootstrap is supported')
    version=re.search(r'/apps/linux/([0-9]+(?:\.[0-9]+)+)/',url)
    if not version:raise ValueError('Version missing from the final official URL')
    return {'channel':channel,'version':version[1],'url':url,'sha256':sha256(path),
            'archive':path.name,'architecture':'x86_64'}


def complete(release):
    if not release or release.get('draft') or release.get('prerelease'):return False
    names={a['name'] for a in release.get('assets',[])}
    return {'catalog.json','SHA256SUMS','install.sh','native-discord','PKGBUILDS.zip'}<=names and all(
        any(n.startswith(f'native-discord-{c}-') and n.endswith('-x86_64.pkg.tar.zst') for n in names)
        for c in (*CHANNELS,'manager'))


def plan(output, repo, revision):
    if not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError('A full builder commit is required')
    output.mkdir(parents=True,exist_ok=True)
    apps=[]
    for channel in CHANNELS:
        path=output/(channel+'.tar.gz')
        endpoint='https://discord.com/api/download'+('' if channel=='stable' else '/'+channel)+'?platform=linux&format=tar.gz'
        final=download(endpoint,path)
        apps.append(describe(path,channel,final))
        print(channel,apps[-1]['version'],apps[-1]['sha256'])
    digest=hashlib.sha256(json.dumps({'builder':revision,'apps':apps},sort_keys=True).encode()).hexdigest()
    tag='sha-'+digest
    release=gh_json('api',f'repos/{repository(repo)}/releases/tags/{tag}')
    catalog={'schema':1,'repository':repo,'tag':tag,'builder':revision,'digest':digest,'channels':apps}
    (output/'plan.json').write_text(json.dumps(catalog,indent=2)+'\n')
    needed=not complete(release)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:
            f.write(f'build={str(needed).lower()}\ntag={tag}\n')
    print('Build required' if needed else 'All four channels and the manager are already published; skipping build and release')
    return needed


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--repository',required=True)
    p.add_argument('--revision',required=True)
    a=p.parse_args();plan(a.output,a.repository,a.revision)

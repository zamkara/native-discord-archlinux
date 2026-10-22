#!/usr/bin/env python3
"""Publish a verified complete suite; a partial upload is never made public."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

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
    # Draft tag endpoints can return 404 until publication. Resolve drafts from
    # the release list and use the immutable numeric release ID for every mutation.
    pages=gh_json('api','--paginate','--slurp',f'repos/{repo}/releases?per_page=100')
    matches=[r for page in pages for r in page if r.get('tag_name')==tag]
    release=next((r for r in matches if not r.get('draft')), matches[0] if matches else None)
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
        release=gh_json('api','--method','POST',f'repos/{repo}/releases','--input','-',
                        input=json.dumps({'tag_name':tag,'target_commitish':revision,
                          'draft':True,'prerelease':False,'name':'Native Discord '+catalog['digest'][:12],
                          'body':note.read_text()}))
    if not release or not isinstance(release.get('id'),int):
        raise RuntimeError('GitHub did not return a release ID')
    release_id=release['id']
    endpoint=f'repos/{repo}/releases/{release_id}'
    assets={a['name']:a['id'] for a in release.get('assets',[])}
    for path in sorted(root.iterdir()):
        if path.name in assets:
            subprocess.run(['gh','api','--method','DELETE',
                            f'repos/{repo}/releases/assets/{assets[path.name]}'],check=True)
        upload=f'https://uploads.github.com/{endpoint}/assets?name={quote(path.name,safe="")}'
        subprocess.run(['gh','api','--method','POST','--header','Content-Type: application/octet-stream',
                        upload,'--input',str(path)],check=True,stdout=subprocess.DEVNULL)
    staged=gh_json('api',endpoint)
    if not staged:raise RuntimeError('Uploaded release could not be read by its ID')
    remote={a['name']:a['size'] for a in staged['assets']}
    for path in root.iterdir():
        if remote.get(path.name)!=path.stat().st_size:raise RuntimeError('Incomplete upload: '+path.name)
    published=gh_json('api','--method','PATCH',endpoint,'--input','-',
                     input=json.dumps({'draft':False,'prerelease':False,'make_latest':'true'}))
    if not published or published.get('draft') or published.get('prerelease'):
        raise RuntimeError('GitHub did not confirm a published stable release')
    print(published['html_url'])



if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    p.add_argument('--repository',required=True);p.add_argument('--revision',required=True)
    a=p.parse_args();publish(a.root,a.repository,a.revision)

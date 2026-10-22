#!/usr/bin/env python3
"""Generate pinned native PKGBUILDs and build as an unprivileged Arch user."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from common import CHANNELS, HELPERS, repository, sha256
from native_discord import DEPS


def quote(s):
    return "'"+str(s).replace("'", "'\\''")+"'"


def generate(root, epoch):
    plan=json.loads((root/'plan.json').read_text());repo=repository(plan['repository'])
    if not epoch.isdigit():raise ValueError('SOURCE_DATE_EPOCH must be numeric')
    for item in plan['channels']:
        channel=item['channel'];folder,launcher,_,_=CHANNELS[channel]
        work=root/'work'/channel;work.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/item['archive'],work/'upstream.tar.gz')
        if sha256(work/'upstream.tar.gz')!=item['sha256']:raise ValueError('Upstream archive hash mismatch')
        metadata={'schema':1,'channel':channel,'bootstrap_version':item['version'],
                  'url':item['url'],'sha256':item['sha256'],'builder':plan['builder'],
                  'repository':repo,'app_updates':'official-discord-updater'}
        (work/'upstream.json').write_text(json.dumps(metadata,indent=2)+'\n')
        (work/'upstream-license.txt').write_text('Discord is proprietary software by Discord Inc.\nhttps://discord.com/terms\nhttps://discord.com/licenses\nThe Almatera license covers this builder only.\n')
        (work/'launch').write_text(f'#!/bin/sh\nexec /usr/bin/native-discord -o {channel} -- "$@"\n')
        (work/'app.desktop').write_text(f'[Desktop Entry]\nType=Application\nName=Discord {channel.title() if channel!="stable" else ""}\nComment=Official Discord client; official automatic updates\nExec=discord-native-{channel} %U\nIcon=discord-native-{channel}\nTerminal=false\nCategories=Network;InstantMessaging;\nMimeType=x-scheme-handler/discord;\nStartupWMClass={folder}\n')
        shutil.copy2(HELPERS/'unpack.py',work/'unpack.py')
        depends=' '.join(quote(d) for d in ['native-discord-manager',*DEPS])
        (work/'PKGBUILD').write_text(f'''# Generated from a pinned official Discord archive.
pkgname=native-discord-{channel}
pkgver={item['version']}
pkgrel=1.{epoch}
pkgdesc='Official Discord {channel.title()} bootstrap and native Arch integration'
arch=('x86_64')
url='https://discord.com'
license=('LicenseRef-Discord')
depends=({depends})
optdepends=('libappindicator-gtk3: system tray support')
options=('!strip' '!debug')
source=('upstream.tar.gz' 'upstream.json' 'upstream-license.txt' 'launch' 'app.desktop' 'unpack.py')
noextract=('upstream.tar.gz')
sha256sums=({' '.join(quote(sha256(work/name)) for name in ['upstream.tar.gz','upstream.json','upstream-license.txt','launch','app.desktop','unpack.py'])})
package() {{
  python "$srcdir/unpack.py" "$srcdir/upstream.tar.gz" "$srcdir/extracted" {quote(folder)}
  install -dm755 "$pkgdir/opt/native-discord/{channel}"
  cp -a "$srcdir/extracted/{folder}/." "$pkgdir/opt/native-discord/{channel}/"
  # Upstream's Debian postinst script must never run on Arch or touch user profiles.
  rm -f "$pkgdir/opt/native-discord/{channel}/postinst.sh"
  install -Dm755 "$srcdir/launch" "$pkgdir/usr/bin/discord-native-{channel}"
  install -Dm644 "$srcdir/app.desktop" "$pkgdir/usr/share/applications/discord-native-{channel}.desktop"
  install -Dm644 "$srcdir/extracted/{folder}/discord.png" "$pkgdir/usr/share/icons/hicolor/256x256/apps/discord-native-{channel}.png"
  install -Dm644 "$srcdir/upstream.json" "$pkgdir/usr/share/native-discord/{channel}.json"
  install -Dm644 "$srcdir/upstream-license.txt" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}}
''')
    work=root/'work/manager';work.mkdir(parents=True,exist_ok=True)
    manager=(HELPERS/'native_discord.py').read_text().replace("REPOSITORY = 'zamkara/native-discord-archlinux'",'REPOSITORY = '+repr(repo))
    (work/'native-discord').write_text(manager)
    shutil.copy2(HELPERS.parents[2]/'LICENSE',work/'LICENSE')
    (work/'manager.desktop').write_text('[Desktop Entry]\nType=Application\nName=Native Discord\nComment=Install and choose an official Discord channel\nExec=native-discord\nIcon=preferences-system\nTerminal=true\nCategories=Network;Settings;\n')
    (work/'PKGBUILD').write_text(f'''pkgname=native-discord-manager
pkgver=0.r{epoch}.g{plan['builder'][:12]}
pkgrel=1
pkgdesc='Terminal installer and channel selector for official Discord clients'
arch=('x86_64')
url='https://github.com/{repo}'
license=('LicenseRef-Almatera-Incubator')
depends=('python' 'curl' 'sudo')
options=('!strip' '!debug')
source=('native-discord' 'LICENSE' 'manager.desktop')
sha256sums=({' '.join(quote(sha256(work/name)) for name in ['native-discord','LICENSE','manager.desktop'])})
package() {{
  install -Dm755 "$srcdir/native-discord" "$pkgdir/usr/bin/native-discord"
  install -Dm644 "$srcdir/manager.desktop" "$pkgdir/usr/share/applications/native-discord.desktop"
  install -Dm644 "$srcdir/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}}
''')
    return plan


def build(root, epoch):
    plan=generate(root,epoch);release=root/'release';release.mkdir(exist_ok=True)
    recipes=root/'recipes';recipes.mkdir(exist_ok=True)
    packages={}
    for name in ('manager',*CHANNELS):
        work=root/'work'/name
        subprocess.run(['makepkg','--cleanbuild','--nodeps','--noconfirm'],cwd=work,check=True)
        files=list(work.glob('*.pkg.tar.zst'))
        if len(files)!=1:raise RuntimeError('Expected exactly one package per build')
        shutil.copy2(files[0],release/files[0].name);packages[name]=files[0].name
        (recipes/name).mkdir(exist_ok=True)
        # Include everything required to reproduce a recipe except the upstream tarball.
        for file in work.iterdir():
            if file.is_file() and file.name!='upstream.tar.gz' and not file.name.endswith('.pkg.tar.zst'):
                shutil.copy2(file,recipes/name/file.name)
        with (recipes/name/'SRCINFO').open('w') as f:
            subprocess.run(['makepkg','--printsrcinfo'],cwd=work,stdout=f,check=True)
    plan['packages']=packages
    (release/'catalog.json').write_text(json.dumps(plan,indent=2)+'\n')
    shutil.copy2(root/'work/manager/native-discord',release/'native-discord')
    installer=(HELPERS/'install.sh.in').read_text().replace('@REPOSITORY@',plan['repository']).replace('@TAG@',plan['tag'])
    (release/'install.sh').write_text(installer)
    shutil.make_archive(str(release/'PKGBUILDS'),'zip',recipes)
    (release/'SHA256SUMS').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in sorted(release.iterdir()) if p.name!='SHA256SUMS'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    p.add_argument('--epoch',required=True);p.add_argument('--generate-only',action='store_true')
    a=p.parse_args();(generate if a.generate_only else build)(a.root.resolve(),a.epoch)

#!/usr/bin/env python3
"""Install official Discord bootstraps and choose a channel. Discord updates itself."""
import argparse
import curses
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request

REPOSITORY = 'zamkara/native-discord-archlinux'
CHANNELS = {
    'stable': ('discord', 'discord', 'Discord'),
    'ptb': ('discord-ptb', 'discordptb', 'DiscordPTB'),
    'canary': ('discord-canary', 'discordcanary', 'DiscordCanary'),
    'development': ('discord-development', 'discorddevelopment', 'DiscordDevelopment'),
}
PREFIX = Path('/opt/native-discord')
DEPS = ['alsa-lib','at-spi2-core','cairo','curl','dbus','expat','gcc-libs','glib2',
        'glibc','gtk3','hicolor-icon-theme','libdrm','libnotify','libxcb','libxcomposite','libxdamage',
        'libpulse','libxext','libxfixes','libxkbcommon','libxrandr','libxss','libxtst','mesa',
        'nspr','nss','pango','python','sudo','xdg-utils','zenity']


def config_dir():
    return Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))


def active_channel():
    try:
        value=json.loads((config_dir()/'native-discord/settings.json').read_text())['channel']
        if value in CHANNELS:return value
    except (OSError,ValueError,KeyError,TypeError):pass
    return 'stable'


def select_channel(channel):
    if channel not in CHANNELS:raise ValueError('Unknown channel')
    path=config_dir()/'native-discord/settings.json'
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # A random temporary file avoids clobbering another process's pending selection.
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.settings-')
    try:
        with os.fdopen(fd,'w') as f:json.dump({'channel':channel},f);f.write('\n')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def installed(channel):
    return (PREFIX/channel/CHANNELS[channel][0]).is_file()


def status(channel):
    if not installed(channel):return 'Not installed'
    base=config_dir()/CHANNELS[channel][1]
    for folder in (base,*(p for p in sorted(base.glob('*')) if p.is_dir())):
        info=folder/'resources/build_info.json'
        try:
            version=json.loads(info.read_text()).get('version')
            if version:return str(version)
        except (OSError,ValueError,TypeError):pass
    return 'Installed; official updater manages app'


def fetch(url,path):
    # Release downloads are HTTPS and credentials are never passed to redirects.
    subprocess.run(['curl','-fLsS','--proto','=https','--proto-redir','=https',
                    '--retry','3','--connect-timeout','20','--max-time','300',
                    '-o',str(path),url],check=True)


def release_catalog():
    tag=os.environ.get('NATIVE_DISCORD_RELEASE','')
    if tag and not re.fullmatch(r'sha-[a-f0-9]{64}',tag):raise ValueError('Invalid requested release')
    endpoint='tags/'+tag if tag else 'latest'
    req=urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/releases/'+endpoint,
                              headers={'User-Agent':'native-discord'})
    with urllib.request.urlopen(req,timeout=30) as r:release=json.load(r)
    if release.get('draft') or release.get('prerelease'):raise ValueError('A published release is required')
    tag=release.get('tag_name','')
    if not re.fullmatch(r'sha-[a-f0-9]{64}',tag):raise ValueError('Invalid release identity')
    base=f'https://github.com/{REPOSITORY}/releases/download/{tag}/'
    with tempfile.TemporaryDirectory(prefix='native-discord-') as d:
        root=Path(d);fetch(base+'SHA256SUMS',root/'SHA256SUMS')
        sums=parse_checksums((root/'SHA256SUMS').read_text())
        fetch(base+'catalog.json',root/'catalog.json');verify(root/'catalog.json',sums)
        catalog=json.loads((root/'catalog.json').read_text())
    if catalog['repository']!=REPOSITORY or catalog['tag']!=tag:raise ValueError('Release metadata mismatch')
    return base,sums,catalog


def parse_checksums(text):
    out={}
    for line in text.splitlines():
        match=re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.+\-]+)',line)
        if not match or match[2] in out:raise ValueError('Invalid checksum manifest')
        out[match[2]]=match[1]
    return out


def verify(path,sums):
    if path.name not in sums:raise ValueError('Unlisted release asset')
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    if h.hexdigest()!=sums[path.name]:raise ValueError('Checksum mismatch: '+path.name)


def transaction(arguments):
    if os.geteuid()==0:raise RuntimeError('Run as your regular user; only pacman needs administrator privileges')
    with open('/dev/tty','rb',buffering=0) as tty:
        subprocess.run(['sudo','--','/usr/bin/pacman',*arguments],stdin=tty,check=True)


def install(channel):
    if platform.machine()!='x86_64':raise RuntimeError('Official Linux tarballs verified by this builder are x86_64 only')
    base,sums,catalog=release_catalog()
    packages=catalog['packages']
    with tempfile.TemporaryDirectory(prefix='native-discord-install-') as d:
        paths=[]
        for name in ('manager',channel):
            filename=packages[name]
            if not re.fullmatch(r'native-discord-'+name+r'-[A-Za-z0-9_.+\-]+-x86_64\.pkg\.tar\.zst',filename):
                raise ValueError('Unexpected package asset')
            path=Path(d)/filename;fetch(base+filename,path);verify(path,sums);paths.append(str(path))
        missing=subprocess.run(['/usr/bin/pacman','-T',*DEPS],capture_output=True,text=True)
        if missing.returncode not in (0,127):raise RuntimeError('Could not check system dependencies')
        if missing.stdout.strip():transaction(['-S','--needed','--',*missing.stdout.splitlines()])
        transaction(['-U','--',*paths])
    select_channel(channel)
    print(f'{channel.title()} installed. Discord downloads and updates its app directly from Discord on launch.')


def launch(channel,args):
    if os.geteuid()==0:raise RuntimeError('Discord must run as your regular user')
    launcher=PREFIX/channel/CHANNELS[channel][0]
    if not installed(channel):raise RuntimeError(f'{channel.title()} is not installed. Run native-discord -i {channel}')
    host=config_dir()/CHANNELS[channel][1]/CHANNELS[channel][2]
    if not os.access(host,os.X_OK):
        target=host.parent
        target.mkdir(parents=True,exist_ok=True)
        mode="--no-zenity" if sys.stdout.isatty() else "--zenity"
        result=subprocess.run([str(PREFIX/channel/"updater_bootstrap"),mode,str(target),
                               channel,"https://updates.discord.com/"],check=True,
                              stdout=subprocess.PIPE,text=True)
        relative=result.stdout.strip()
        if not re.fullmatch(r'app-[0-9]+(?:\.[0-9]+)+',relative):
            raise RuntimeError('Official bootstrap returned an unexpected application path')
        host=(target/relative/CHANNELS[channel][2]).resolve()
        if not host.is_relative_to(target.resolve()) or not os.access(host,os.X_OK):
            raise RuntimeError('Official bootstrap did not produce an executable application')
    # Launch only the executable produced by Discord's own updater. The packaged
    # official launcher and bootstrap are preserved byte-for-byte.
    os.execv(str(host),[str(host),*args])


def remove(channel):
    transaction(['-R','--','native-discord-'+channel])
    print('Package removed. Discord profile, account and downloaded app data were preserved.')


def tui():
    if not sys.stdin.isatty() or not sys.stdout.isatty():raise RuntimeError('An interactive terminal is required')
    selected=list(CHANNELS).index(active_channel())
    message='Up/Down Select | Enter Default | i Install | o Open | r Remove | q Quit'
    def screen(stdscr):
        nonlocal selected,message
        curses.curs_set(0);stdscr.keypad(True)
        while True:
            stdscr.erase();h,w=stdscr.getmaxyx()
            if h<12 or w<64:
                stdscr.addnstr(0,0,'Resize terminal to at least 64 x 12. Press q to quit.',max(0,w-1))
                stdscr.refresh()
                if stdscr.getch() in (ord('q'),27):return
                continue
            def line(y,text,attr=0):stdscr.addnstr(y,2,text,w-4,attr)
            line(1,'Native Discord')
            line(2,'Official Discord clients. App updates are handled by Discord.')
            for i,channel in enumerate(CHANNELS):
                mark='*' if channel==active_channel() else ' '
                label='PTB' if channel=='ptb' else channel.title()
                line(4+i,f'{mark} {label:<14} {status(channel)}',curses.A_REVERSE if i==selected else 0)
            line(h-3,message);line(h-2,'* Default channel. Profiles stay separate when switching.')
            stdscr.refresh();key=stdscr.getch()
            if key in (ord('q'),27):return
            if key in (curses.KEY_UP,ord('k')):selected=(selected-1)%len(CHANNELS)
            elif key in (curses.KEY_DOWN,ord('j')):selected=(selected+1)%len(CHANNELS)
            elif key in (10,13,curses.KEY_ENTER):
                select_channel(list(CHANNELS)[selected]);message='Default channel changed. Press o to open.'
            elif key in (ord('i'),ord('o'),ord('r')):
                channel=list(CHANNELS)[selected]
                curses.def_prog_mode();curses.endwin()
                try:
                    if key==ord('i'):install(channel)
                    elif key==ord('o'):launch(channel,[])
                    else:remove(channel)
                    message='Done.'
                except Exception as error:
                    print('Error:',error,file=sys.stderr);message=str(error)
                finally:
                    curses.reset_prog_mode();stdscr.clear()
    curses.wrapper(screen)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group()
    group.add_argument('-i','--install',choices=CHANNELS,metavar='CHANNEL')
    group.add_argument('-s','--switch',choices=CHANNELS,metavar='CHANNEL')
    group.add_argument('-o','--open',nargs='?',const='',choices=['',*CHANNELS],metavar='CHANNEL')
    group.add_argument('-r','--remove',choices=CHANNELS,metavar='CHANNEL')
    group.add_argument('-l','--list',action='store_true')
    p.add_argument('urls',nargs='*')
    a=p.parse_args(argv)
    if a.install:install(a.install)
    elif a.switch:select_channel(a.switch)
    elif a.open is not None:launch(a.open or active_channel(),a.urls)
    elif a.remove:remove(a.remove)
    elif a.list:
        for channel in CHANNELS:print(f'{channel:<14} {status(channel)}')
    else:tui()


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.CalledProcessError) as e:
        print('Error:',e,file=sys.stderr);sys.exit(1)

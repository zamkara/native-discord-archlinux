#!/usr/bin/env python3
"""Install official Discord bootstraps and choose a channel. Discord updates itself."""
import argparse
import curses
from collections import deque
import queue
import textwrap
import threading
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
                    '-o',str(path),url],check=True,capture_output=True,text=True)


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


class Cancelled(RuntimeError):
    pass


def clean_output(text):
    text=re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)', '', text)
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return ''.join(c for c in text if c in '\n\t' or ord(c)>=32).replace('\t','    ')


class ScreenFeedback:
    def __init__(self,events):self.events=events
    def log(self,text):
        for line in clean_output(str(text)).splitlines():
            self.events.put(('log',line[:2000]))
    def request(self,kind,text):
        reply=queue.Queue(maxsize=1)
        self.events.put(('prompt',(kind,text,reply)))
        return reply.get()


def notify(text,feedback=None):
    if feedback:feedback.log(text)
    else:print(text)


def capture_command(arguments,feedback,*,input=None,stdout_only=False):
    """Stream subprocess output into the UI; never inherit its terminal streams."""
    if input is not None:
        # Passwords only go through stdin. Never send this command's output to the log.
        return subprocess.run(arguments,input=input,capture_output=True,text=True)
    command=subprocess.Popen(arguments,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE if stdout_only else subprocess.STDOUT,
                             text=True,errors='replace',env={**os.environ,'LC_ALL':'C'})
    if stdout_only:
        def read_errors():
            for line in command.stderr:feedback.log(line)
        reader=threading.Thread(target=read_errors)
        reader.start();output=command.stdout.read();code=command.wait();reader.join()
    else:
        tail=deque(maxlen=40)
        for line in command.stdout:
            feedback.log(line);tail.append(line)
        output=''.join(tail);code=command.wait()
    command.stdout.close()
    if command.stderr:command.stderr.close()
    if code:raise RuntimeError(f'Command failed (exit {code}): '+clean_output(output[-1000:]).strip())
    return subprocess.CompletedProcess(arguments,code,output,'')


def transaction(arguments,feedback=None):
    if os.geteuid()==0:raise RuntimeError('Run as your regular user; only pacman needs administrator privileges')
    if feedback is None:
        with open('/dev/tty','rb',buffering=0) as tty:
            subprocess.run(['sudo','--','/usr/bin/pacman',*arguments],stdin=tty,check=True)
        return
    plan=subprocess.run(['/usr/bin/pacman','--print','--print-format','%n %v (%s bytes)',*arguments],
                        capture_output=True,text=True,env={**os.environ,'LC_ALL':'C'})
    if plan.returncode:raise RuntimeError(clean_output(plan.stderr).strip() or 'Could not resolve package transaction')
    if not plan.stdout.strip():
        feedback.log('No package changes needed.');return
    text=('Remove these packages?' if arguments[0]=='-R' else 'Install these packages?')+'\n\n'+plan.stdout
    if plan.stderr.strip():text+='\n'+clean_output(plan.stderr)
    feedback.log(text)
    if not feedback.request('confirm',text):raise Cancelled('Cancelled. No packages changed.')
    authenticated=subprocess.run(['/usr/bin/sudo','-n','-v'],stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    if not authenticated:
        for attempt in range(3):
            password=feedback.request('password','Administrator password' if attempt==0 else 'Authentication failed. Try again.')
            if password is None:raise Cancelled('Authentication cancelled. No packages changed.')
            result=capture_command(['/usr/bin/sudo','-S','-p','','-v'],feedback,input=password+'\n')
            del password
            if result.returncode==0:authenticated=True;break
        if not authenticated:raise RuntimeError('Authentication failed. No packages changed.')
    capture_command(['/usr/bin/sudo','-n','--','/usr/bin/pacman',
                     '--noconfirm','--color','never',*arguments],feedback)
    feedback.log('Package transaction completed.')


def install(channel,feedback=None):
    if platform.machine()!='x86_64':raise RuntimeError('Official Linux tarballs verified by this builder are x86_64 only')
    notify('Checking release catalog...',feedback)
    base,sums,catalog=release_catalog()
    packages=catalog['packages']
    with tempfile.TemporaryDirectory(prefix='native-discord-install-') as d:
        paths=[]
        for name in ('manager',channel):
            filename=packages[name]
            if not re.fullmatch(r'native-discord-'+name+r'-[A-Za-z0-9_.+\-]+-x86_64\.pkg\.tar\.zst',filename):
                raise ValueError('Unexpected package asset')
            version=filename.removeprefix('native-discord-'+name+'-').removesuffix('-x86_64.pkg.tar.zst')
            current=subprocess.run(['/usr/bin/pacman','-Q','native-discord-'+name],capture_output=True,text=True)
            current_version=current.stdout.strip().split(maxsplit=1)[-1] if current.returncode==0 else ''
            comparison=(subprocess.run(['/usr/bin/vercmp',current_version,version],capture_output=True,text=True)
                        if current_version and current_version!=version else None)
            if current_version==version or (comparison and comparison.returncode==0 and int(comparison.stdout)>=0):
                notify(f'{name.title()} integration is already current.',feedback)
                continue
            notify('Downloading '+filename+'...',feedback)
            path=Path(d)/filename;fetch(base+filename,path);verify(path,sums);paths.append(str(path))
        missing=subprocess.run(['/usr/bin/pacman','-T',*DEPS],capture_output=True,text=True)
        if missing.returncode not in (0,127):raise RuntimeError('Could not check system dependencies')
        if missing.stdout.strip():transaction(['-S','--needed','--',*missing.stdout.splitlines()],feedback)
        if paths:transaction(['-U','--',*paths],feedback)
    select_channel(channel)
    notify(f'{channel.title()} is ready. Discord handles its own app updates.',feedback)


def launch(channel,args,feedback=None,detach=False):
    if os.geteuid()==0:raise RuntimeError('Discord must run as your regular user')
    launcher=PREFIX/channel/CHANNELS[channel][0]
    if not installed(channel):raise RuntimeError(f'{channel.title()} is not installed. Run native-discord -i {channel}')
    host=config_dir()/CHANNELS[channel][1]/CHANNELS[channel][2]
    if not os.access(host,os.X_OK):
        target=host.parent
        target.mkdir(parents=True,exist_ok=True)
        mode="--no-zenity" if sys.stdout.isatty() else "--zenity"
        command=[str(PREFIX/channel/"updater_bootstrap"),
                 "--no-zenity" if feedback else mode,str(target),channel,"https://updates.discord.com/"]
        result=(capture_command(command,feedback,stdout_only=True) if feedback else
                subprocess.run(command,check=True,stdout=subprocess.PIPE,text=True))
        relative=result.stdout.strip()
        if not re.fullmatch(r'app-[0-9]+(?:\.[0-9]+)+',relative):
            raise RuntimeError('Official bootstrap returned an unexpected application path')
        host=(target/relative/CHANNELS[channel][2]).resolve()
        if not host.is_relative_to(target.resolve()) or not os.access(host,os.X_OK):
            raise RuntimeError('Official bootstrap did not produce an executable application')
    # Launch only the executable produced by Discord's own updater. The packaged
    # official launcher and bootstrap are preserved byte-for-byte.
    if detach:
        state=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'native-discord'
        state.mkdir(parents=True,exist_ok=True,mode=0o700)
        log=state/(channel+'.log')
        if log.exists() and log.stat().st_size>2*1024*1024:
            log.replace(log.with_suffix('.previous.log'))
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'a') as output:
            child=subprocess.Popen([str(host),*args],stdin=subprocess.DEVNULL,
                                   stdout=output,stderr=output,start_new_session=True)
        try:code=child.wait(timeout=0.3)
        except subprocess.TimeoutExpired:code=None
        if code not in (None,0):raise RuntimeError(f'Discord exited with code {code}. Log: {log}')
        notify(channel.title()+' opened.',feedback)
        return
    os.execv(str(host),[str(host),*args])


def remove(channel,feedback=None):
    transaction(['-R','--','native-discord-'+channel],feedback)
    notify('Package removed. Discord profile, account and downloaded app data were preserved.',feedback)


def tui():
    if not sys.stdin.isatty() or not sys.stdout.isatty():raise RuntimeError('An interactive terminal is required')
    events=queue.Queue(maxsize=256)
    feedback=ScreenFeedback(events)
    selected=list(CHANNELS).index(active_channel())
    logs=deque(maxlen=200)
    busy=False;prompt=None;password=[];prompt_scroll=0;message='Ready.'
    states={channel:status(channel) for channel in CHANNELS}
    current=active_channel()

    def perform(key,channel):
        try:
            if key=='i':install(channel,feedback)
            elif key=='o':launch(channel,[],feedback,detach=True)
            else:remove(channel,feedback)
            events.put(('done','Done.'))
        except Cancelled as error:events.put(('done',str(error)))
        except Exception as error:
            feedback.log('Error: '+str(error));events.put(('done',str(error)))

    def screen(stdscr):
        nonlocal selected,busy,prompt,password,prompt_scroll,message,states,current
        curses.curs_set(0);curses.raw();stdscr.keypad(True)
        while True:
            while True:
                try:kind,value=events.get_nowait()
                except queue.Empty:break
                if kind=='log':logs.append(value)
                elif kind=='prompt':prompt=value;password=[];prompt_scroll=0
                elif kind=='done':
                    busy=False;message=value
                    states={channel:status(channel) for channel in CHANNELS};current=active_channel()
            stdscr.erase();h,w=stdscr.getmaxyx()
            stdscr.timeout(100 if busy else -1)
            if h<18 or w<72:
                stdscr.addnstr(0,0,'Resize to at least 72 x 18. Transactions remain active.',max(0,w-1))
                stdscr.refresh();key=stdscr.getch()
                if key in (ord('q'),27,3) and not busy:return
                continue
            def line(y,text,attr=0):
                if 0<=y<h:stdscr.addnstr(y,2,clean_output(text),w-4,attr)
            line(1,'Native Discord')
            line(2,'Official clients. App updates are handled by Discord.')
            for i,channel in enumerate(CHANNELS):
                mark='*' if channel==current else ' '
                label='PTB' if channel=='ptb' else channel.title()
                line(4+i,f'{mark} {label:<14} {states[channel]}',curses.A_REVERSE if i==selected else 0)
            line(9,'Activity')
            for y,text in enumerate(list(logs)[-max(0,h-15):],11):line(y,text)
            line(h-4,message)
            line(h-3,'Working...' if busy else 'Up/Down Select | Enter Default | i Install | o Open | r Remove')
            line(h-2,'Wait for the transaction to finish.' if busy else '* Default channel | q Quit')
            if prompt:
                kind,text,reply=prompt
                wrapped=[]
                for part in clean_output(text).splitlines():
                    wrapped.extend(textwrap.wrap(part,w-8) or [''])
                # A dedicated screen keeps long plans visible without exposing terminal output.
                stdscr.erase()
                line(1,'Authentication' if kind=='password' else 'Confirm package transaction')
                prompt_scroll=min(prompt_scroll,max(0,len(wrapped)-(h-7)))
                for y,text in enumerate(wrapped[prompt_scroll:prompt_scroll+h-7],3):line(y,text)
                if len(wrapped)>h-7:line(h-3,'PgUp/PgDn: scroll the package plan')
                if kind=='password':
                    line(h-3,'Password: '+'*'*min(len(password),w-16))
                    line(h-2,'Enter Submit | Esc Cancel')
                else:line(h-2,'y Confirm | n / Esc Cancel')
            stdscr.refresh()
            try:key=stdscr.get_wch()
            except curses.error:continue
            if prompt:
                kind,text,reply=prompt
                if key in ('\x1b','\x03') or (kind=='confirm' and key in ('n','N')):
                    reply.put(None if kind=='password' else False);prompt=None;password=[]
                elif kind=='confirm' and key in (curses.KEY_NPAGE,curses.KEY_PPAGE):
                    prompt_scroll=max(0,prompt_scroll+(h-7)*(1 if key==curses.KEY_NPAGE else -1))
                elif kind=='confirm' and key in ('y','Y'):
                    reply.put(True);prompt=None
                elif kind=='password':
                    if key in ('\n','\r',curses.KEY_ENTER):
                        reply.put(''.join(password));prompt=None;password=[]
                    elif key in ('\b','\x7f',curses.KEY_BACKSPACE):
                        if password:password.pop()
                    elif isinstance(key,str) and key.isprintable() and len(password)<1024:password.append(key)
                continue
            if busy:
                if key in ('q','\x1b','\x03'):message='Transaction running. Wait for completion; nothing was interrupted.'
                continue
            if key in ('q','\x1b','\x03'):return
            if key in (curses.KEY_UP,'k'):selected=(selected-1)%len(CHANNELS)
            elif key in (curses.KEY_DOWN,'j'):selected=(selected+1)%len(CHANNELS)
            elif key in ('\n','\r',curses.KEY_ENTER):
                select_channel(list(CHANNELS)[selected]);current=active_channel()
                message='Default channel changed. Press o to open.'
            elif key in ('i','o','r'):
                channel=list(CHANNELS)[selected]
                if key in ('o','r') and not installed(channel):
                    message=channel.title()+' is not installed. Press i to install.'
                    continue
                busy=True;message={'i':'Preparing installation...','o':'Opening Discord...','r':'Preparing removal...'}[key]
                logs.clear();threading.Thread(target=perform,args=(key,channel),daemon=True).start()
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

"""Small, validated interfaces shared by the build scripts."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

CHANNELS = {
    'stable': ('Discord', 'discord', 'discord', 'Discord'),
    'ptb': ('DiscordPTB', 'discord-ptb', 'discordptb', 'DiscordPTB'),
    'canary': ('DiscordCanary', 'discord-canary', 'discordcanary', 'DiscordCanary'),
    'development': ('DiscordDevelopment', 'discord-development', 'discorddevelopment', 'DiscordDevelopment'),
}
HELPERS = Path(__file__).resolve().parent


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):h.update(chunk)
    return h.hexdigest()


def official_url(url):
    p=urlsplit(url)
    host=p.hostname or ''
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443):
        raise ValueError('Expected an official HTTPS download URL')
    if not any(host==domain or host.endswith('.'+domain) for domain in ('discord.com','discordapp.com','discordapp.net')):
        raise ValueError('Download redirected outside official Discord domains')
    return url


def repository(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*',value):raise ValueError('Invalid repository')
    return value


def download(url, destination):
    official_url(url)
    # curl is used deliberately: some Discord CDN edges reject urllib's TLS/user agent.
    result=subprocess.run(['curl','--fail','--silent','--show-error','--location',
        '--proto','=https','--proto-redir','=https','--retry','3','--connect-timeout','20',
        '--max-time','300','--output',str(destination),'--write-out','%{url_effective}',url],
        check=True,capture_output=True,text=True)
    official_url(result.stdout.strip())
    return result.stdout.strip()


def gh_json(*args, input=None):
    p=subprocess.run(['gh',*args],input=input,capture_output=True,text=True)
    if p.returncode:
        if 'HTTP 404' in p.stderr or 'release not found' in p.stderr.lower():return None
        raise RuntimeError(p.stderr.strip() or 'GitHub request failed')
    return json.loads(p.stdout)

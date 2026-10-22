import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HELPERS=Path(__file__).resolve().parents[1]
ROOT=HELPERS.parents[2]
sys.path.insert(0,str(HELPERS))
import common
import native_discord as manager
import prepare
import publish
from unpack import unpack


class InputTests(unittest.TestCase):
    def test_official_urls_only(self):
        for u in ('https://discord.com/api/download','https://development.dl2.discordapp.net/apps/linux/1.0/x'):
            self.assertEqual(common.official_url(u),u)
        for u in ('http://discord.com/file','https://discord.com.evil/x','https://evil.test/x','https://a@discord.com/x','https://discord.com:444/x'):
            with self.assertRaises(ValueError):common.official_url(u)

    def test_repository_cannot_inject_shell_or_paths(self):
        self.assertEqual(common.repository('owner/repo'),'owner/repo')
        for value in ('a/b/c','a/$(pwd)','a/b;evil','../bad'):
            with self.assertRaises(ValueError):common.repository(value)

    def test_release_requires_every_channel_and_manager(self):
        names=['catalog.json','SHA256SUMS','install.sh','native-discord','PKGBUILDS.zip']
        names += [f'native-discord-{c}-1-1-x86_64.pkg.tar.zst' for c in (*common.CHANNELS,'manager')]
        release={'assets':[{'name':n} for n in names]}
        self.assertTrue(prepare.complete(release))
        release['assets'].pop();self.assertFalse(prepare.complete(release))
        release['draft']=True;self.assertFalse(prepare.complete(release))

    def test_unchanged_complete_suite_skips_without_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'inputs'
            apps=[{'channel':c,'version':'1.2.3','sha256':'1'*64,'archive':c+'.tar.gz'} for c in common.CHANNELS]
            names=['catalog.json','SHA256SUMS','install.sh','native-discord','PKGBUILDS.zip']
            names += [f'native-discord-{c}-1-1-x86_64.pkg.tar.zst' for c in (*common.CHANNELS,'manager')]
            release={'assets':[{'name':n} for n in names]}
            with patch.object(prepare,'download',return_value='https://discord.com/archive'),patch.object(prepare,'describe',side_effect=apps),patch.object(prepare,'gh_json',return_value=release),patch.dict(os.environ,{'GITHUB_OUTPUT':str(Path(d)/'output')}),patch('sys.stdout',new=io.StringIO()):
                self.assertFalse(prepare.plan(out,'owner/repo','a'*40))
            self.assertIn('build=false', (Path(d)/'output').read_text())

    def test_upstream_channel_and_elf_are_verified(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'dev.tar.gz'
            def archive(channel):
                with tarfile.open(p,'w:gz') as tar:
                    for name,body in [('discord-development',f'#!/bin/sh\nCHANNEL={channel}\n'.encode()),('discord.png',b'PNG'),('updater_bootstrap',b'\x7fELF'+b'\0'*14+(62).to_bytes(2,'little'))]:
                        m=tarfile.TarInfo('DiscordDevelopment/'+name);m.size=len(body);tar.addfile(m,io.BytesIO(body))
            archive('development')
            result=prepare.describe(p,'development','https://development.dl2.discordapp.net/apps/linux/1.2.3/x.tar.gz')
            self.assertEqual(result['version'],'1.2.3')
            archive('canary')
            with self.assertRaisesRegex(ValueError,'mismatch'):prepare.describe(p,'development','https://discord.com/apps/linux/1.2.3/x')


class ArchiveTests(unittest.TestCase):
    def exercise(self,name,kind=tarfile.REGTYPE):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'archive.tar'
            with tarfile.open(p,'w') as tar:
                item=tarfile.TarInfo(name);item.type=kind
                if kind==tarfile.SYMTYPE:item.linkname='/etc/passwd'
                tar.addfile(item)
            unpack(p,Path(d)/'out','Discord')
            self.assertTrue((Path(d)/'out'/name).exists())

    def test_normal_archive(self):self.exercise('Discord/discord')
    def test_traversal_rejected(self):
        for name in ('../evil','Discord/../../evil','/etc/evil','Other/file'):
            with self.assertRaises(ValueError):self.exercise(name)
    def test_symlink_rejected(self):
        with self.assertRaises(ValueError):self.exercise('Discord/link',tarfile.SYMTYPE)
    def test_device_rejected(self):
        with self.assertRaises(ValueError):self.exercise('Discord/device',tarfile.CHRTYPE)


class ManagerTests(unittest.TestCase):
    def test_all_channels_separate_and_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'XDG_CONFIG_HOME':d}):
            for channel in common.CHANNELS:
                manager.select_channel(channel);self.assertEqual(manager.active_channel(),channel)
            self.assertEqual((Path(d)/'native-discord/settings.json').stat().st_mode & 0o777,0o600)
            with self.assertRaises(ValueError):manager.select_channel('../../bad')
            self.assertEqual(len({v[1] for v in manager.CHANNELS.values()}),4)

    def test_corrupt_settings_fall_back(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'XDG_CONFIG_HOME':d}):
            p=Path(d)/'native-discord';p.mkdir();(p/'settings.json').write_text('broken')
            self.assertEqual(manager.active_channel(),'stable')

    def test_no_tui_update_action(self):
        with patch('sys.stderr',new=io.StringIO()),self.assertRaises(SystemExit) as error:manager.main(['--update'])
        self.assertEqual(error.exception.code,2)

    def test_checksum_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'file';p.write_bytes(b'content')
            manager.verify(p,{'file':hashlib.sha256(b'content').hexdigest()})
            with self.assertRaises(ValueError):manager.verify(p,{'file':'0'*64})
            with self.assertRaises(ValueError):manager.verify(p,{})

    def test_checksum_paths_and_duplicates_rejected(self):
        for body in ('0'*64+'  ../bad','0'*64+'  file\n'+'0'*64+'  file'):
            with self.assertRaises(ValueError):manager.parse_checksums(body)

    def test_launch_uses_official_bootstrap_then_unmodified_launcher(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);prefix=root/'prefix';channel=prefix/'development';channel.mkdir(parents=True)
            app=channel/'discord-development';app.write_text('#!/bin/sh\n')
            with patch.object(manager,'PREFIX',prefix),patch.dict(os.environ,{'XDG_CONFIG_HOME':str(root/'config')}),patch('os.geteuid',return_value=1000),patch.object(manager.subprocess,'run') as run,patch.object(manager.os,'execv') as execute:
                host=root/'config/discorddevelopment/app-1.2.3/DiscordDevelopment'
                host.parent.mkdir(parents=True);host.write_text('test');host.chmod(0o755)
                run.return_value.stdout='app-1.2.3\n'
                manager.launch('development',['discord://test'])
                argv=run.call_args.args[0]
                self.assertEqual(argv[0],str(channel/'updater_bootstrap'))
                self.assertEqual(argv[-2:],['development','https://updates.discord.com/'])
                execute.assert_called_once_with(str(host),[str(host),'discord://test'])

    def test_pacman_confirmation_uses_tty(self):
        with patch('os.geteuid',return_value=1000),patch('builtins.open',unittest.mock.mock_open()) as op,patch.object(manager.subprocess,'run') as run:
            manager.transaction(['-U','--','file.pkg.tar.zst'])
            op.assert_called_once_with('/dev/tty','rb',buffering=0)
            self.assertEqual(run.call_args.args[0][:3],['sudo','--','/usr/bin/pacman'])


class PublishTests(unittest.TestCase):
    def test_complete_assets_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            packages={c:'native-discord-'+c+'-1-1-x86_64.pkg.tar.zst' for c in (*common.CHANNELS,'manager')}
            for name in (*packages.values(),'install.sh','native-discord','PKGBUILDS.zip'):
                (root/name).write_bytes(b'fixture')
            catalog={'packages':packages}
            (root/'catalog.json').write_text(json.dumps(catalog))
            (root/'SHA256SUMS').write_text(''.join(common.sha256(p)+'  '+p.name+'\n' for p in sorted(root.iterdir())))
            self.assertEqual(publish.validate(root),catalog)
            (root/'native-discord').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'mismatch'):publish.validate(root)

    def test_no_publish_with_missing_channel(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'catalog.json').write_text(json.dumps({'packages':{}}))
            (root/'SHA256SUMS').write_text(common.sha256(root/'catalog.json')+'  catalog.json\n')
            with self.assertRaisesRegex(ValueError,'four-channel'):publish.validate(root)


class DraftPublicationTests(unittest.TestCase):
    def exercise(self,resume=False,incomplete=False):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'release';root.mkdir();(root/'package').write_bytes(b'archive')
            tag='sha-'+'b'*64
            catalog={'tag':tag,'repository':'owner/repo','builder':'a'*40,'digest':'b'*64,'channels':[]}
            draft={'id':42,'draft':True,'tag_name':tag,'assets':[]}
            def api(*args,**kwargs):
                if '--paginate' in args:return [[draft]] if resume else [[]]
                if '--method' in args:
                    method=args[args.index('--method')+1]
                    if method=='POST':return draft
                    if method=='PATCH':return {'id':42,'draft':False,'prerelease':False,'html_url':'https://example.test/release'}
                self.assertEqual(args,('api','repos/owner/repo/releases/42'))
                return {'assets':[] if incomplete else [{'name':'package','size':7}]}
            with patch.object(publish,'validate',return_value=catalog),patch.object(publish,'gh_json',side_effect=api) as requests,patch.object(publish.subprocess,'run') as run,patch('sys.stdout',new=io.StringIO()):
                if incomplete:
                    with self.assertRaisesRegex(RuntimeError,'Incomplete upload'):publish.publish(root,'owner/repo','a'*40)
                else:publish.publish(root,'owner/repo','a'*40)
                calls=[c.args for c in requests.call_args_list]
                self.assertFalse(any('/tags/' in arg for call in calls for arg in call))
                self.assertTrue(any('/releases/42' in arg for call in calls for arg in call))
                self.assertIn('https://uploads.github.com/repos/owner/repo/releases/42/assets?name=package',run.call_args.args[0])
                posts=[c for c in calls if '--method' in c and c[c.index('--method')+1]=='POST']
                self.assertEqual(len(posts),0 if resume else 1)
                patches=[c for c in calls if '--method' in c and c[c.index('--method')+1]=='PATCH']
                self.assertEqual(len(patches),0 if incomplete else 1)

    def test_new_draft_publishes_by_id_when_tag_lookup_would_404(self):self.exercise()
    def test_existing_draft_is_resumed_without_duplicate(self):self.exercise(resume=True)
    def test_incomplete_upload_stays_draft(self):self.exercise(incomplete=True)


class LayoutTests(unittest.TestCase):
    def test_clean_root(self):
        self.assertEqual({p.name for p in ROOT.iterdir() if p.name!='.git'},{'README.md','LICENSE','.github'})
    def test_schedule_and_no_updater_disable(self):
        workflow=(ROOT/'.github/workflows/release.yml').read_text()
        self.assertIn("cron: '0 3 * * *'",workflow)
        self.assertIn('timezone: America/Los_Angeles',workflow)
        self.assertNotIn('newUpdater', (HELPERS/'build.py').read_text())
        self.assertNotIn('--no-sandbox',(HELPERS/'native_discord.py').read_text())
    def test_installer_not_executed_as_root_and_checksums(self):
        text=(HELPERS/'install.sh.in').read_text()
        self.assertIn('sha256',text)
        self.assertIn('$EUID -ne 0',text)
        self.assertIn('/dev/tty',text)


if __name__=='__main__':unittest.main()

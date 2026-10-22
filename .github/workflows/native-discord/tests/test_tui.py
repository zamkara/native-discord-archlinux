"""Real terminal and subprocess regression tests; no network, sudo or package changes."""
import fcntl
import io
import os
from pathlib import Path
import pty
import queue
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

HELPERS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HELPERS))
import native_discord as m


class FeedbackTests(unittest.TestCase):
    def test_process_output_is_captured_in_activity(self):
        events=queue.Queue();feedback=m.ScreenFeedback(events)
        result=m.capture_command([sys.executable,'-c','import sys; print("OUT"); print("ERR",file=sys.stderr)'],feedback)
        self.assertEqual(result.returncode,0)
        lines=[]
        while not events.empty():lines.append(events.get()[1])
        self.assertIn('OUT',lines);self.assertIn('ERR',lines)

    def test_terminal_control_sequences_are_removed(self):
        self.assertEqual(m.clean_output('\x1b[31mError\x1b[0m\x07'),'Error')

    def test_transaction_cancel_never_runs_sudo(self):
        feedback=unittest.mock.Mock();feedback.request.return_value=False
        with patch('os.geteuid',return_value=1000),patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'example 1.0 (123 bytes)\n','')) as run:
            with self.assertRaises(m.Cancelled):m.transaction(['-U','--','package'],feedback)
            self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.args[0][0],'/usr/bin/pacman')

    def test_password_only_uses_stdin_and_no_output_is_inherited(self):
        feedback=unittest.mock.Mock();feedback.request.side_effect=[True,'synthetic-password']
        responses=[subprocess.CompletedProcess([],0,'example 1.0 (123 bytes)\n',''),subprocess.CompletedProcess([],1,'','')]
        with patch('os.geteuid',return_value=1000),patch.object(m.subprocess,'run',side_effect=responses),patch.object(m,'capture_command') as capture:
            capture.return_value=subprocess.CompletedProcess([],0,'','')
            m.transaction(['-U','--','package'],feedback)
            auth=capture.call_args_list[0]
            self.assertEqual(auth.kwargs['input'],'synthetic-password\n')
            self.assertNotIn('synthetic-password',str(auth.args))
            self.assertIn('--noconfirm',capture.call_args_list[1].args[0])
            self.assertNotIn('synthetic-password',str(feedback.log.call_args_list))

    def test_fetch_does_not_inherit_the_terminal(self):
        with patch.object(m.subprocess,'run') as run:
            m.fetch('https://example.test/file',Path('/tmp/unused-test-path'))
            self.assertTrue(run.call_args.kwargs['capture_output'])

    def test_current_manager_is_not_reinstalled_or_downgraded(self):
        for current_version in ('1.0-1','2.0-1'):
            packages={'manager':'native-discord-manager-1.0-1-x86_64.pkg.tar.zst',
                      'development':'native-discord-development-1.0-1-x86_64.pkg.tar.zst'}
            def command(args,**kwargs):
                if args[:2]==['/usr/bin/pacman','-Q']:
                    return subprocess.CompletedProcess(args,0,'native-discord-manager '+current_version,'') if args[-1]=='native-discord-manager' else subprocess.CompletedProcess(args,1,'','')
                if args[0]=='/usr/bin/vercmp':return subprocess.CompletedProcess(args,0,'1','')
                return subprocess.CompletedProcess(args,0,'','')
            with patch.object(m,'release_catalog',return_value=('https://example.test/',{}, {'packages':packages})),patch.object(m,'fetch') as fetch,patch.object(m,'verify'),patch.object(m.subprocess,'run',side_effect=command),patch.object(m,'transaction') as transaction,patch.object(m,'select_channel'):
                m.install('development',unittest.mock.Mock())
                self.assertEqual(fetch.call_count,1)
                self.assertIn('development',fetch.call_args.args[0])
                self.assertEqual(transaction.call_count,1)

    def test_tui_launch_does_not_replace_the_tui_process(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);profile=root/'config/discorddevelopment';profile.mkdir(parents=True)
            host=profile/'DiscordDevelopment';host.write_text('app');host.chmod(0o755)
            prefix=root/'prefix/development';prefix.mkdir(parents=True);(prefix/'discord-development').write_text('launcher')
            with patch.object(m,'PREFIX',root/'prefix'),patch.dict(os.environ,{'XDG_CONFIG_HOME':str(root/'config'),'XDG_STATE_HOME':str(root/'state')}),patch('os.geteuid',return_value=1000),patch.object(m.os,'execv') as execute,patch.object(m.subprocess,'Popen') as spawn:
                spawn.return_value.wait.side_effect=subprocess.TimeoutExpired('DiscordDevelopment',0.3)
                m.launch('development',[],unittest.mock.Mock(),detach=True)
                execute.assert_not_called()
                self.assertTrue(spawn.call_args.kwargs['start_new_session'])
                self.assertEqual((root/'state/native-discord/development.log').stat().st_mode & 0o777,0o600)


class RealTerminalTests(unittest.TestCase):
    def test_missing_channel_progress_password_and_errors_stay_in_tui(self):
        with tempfile.TemporaryDirectory() as directory:
            code=f'''
import sys
sys.path.insert(0,{str(HELPERS)!r})
import native_discord as m
m.installed=lambda channel:False
m.status=lambda channel:'Not installed'
def install(channel,feedback):
    feedback.log('INTERNAL_PROGRESS')
    if not feedback.request('confirm','TEST_PACKAGE_PLAN'):raise m.Cancelled('Cancelled')
    password=feedback.request('password','TEST_PASSWORD_PROMPT')
    assert password=='synthetic-secret'
    raise RuntimeError('INLINE_TEST_FAILURE')
m.install=install
m.tui()
'''
            master,slave=pty.openpty()
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,100,0,0))
            process=subprocess.Popen([sys.executable,'-c',code],stdin=slave,stdout=slave,stderr=slave,
                env={**os.environ,'TERM':'xterm-256color','XDG_CONFIG_HOME':directory})
            os.close(slave);data=bytearray()
            def until(needle,timeout=5):
                start=len(data);end=time.monotonic()+timeout
                while time.monotonic()<end:
                    ready,_,_=select.select([master],[],[],0.1)
                    if ready:
                        try:block=os.read(master,65536)
                        except OSError:break
                        if not block:break
                        data.extend(block)
                        if needle in data[start:]:return
                self.fail('Terminal did not show '+repr(needle)+'; tail='+repr(bytes(data[-1200:])))
            try:
                until(b'Native Discord')
                os.write(master,b'o');until(b'Press i to install.')
                self.assertIsNone(process.poll())
                os.write(master,b'i');until(b'Confirm package transaction')
                os.write(master,b'y');until(b'TEST_PASSWORD_PROMPT')
                os.write(master,b'synthetic-secret\n');until(b'INLINE_TEST_FAILURE')
                self.assertIsNone(process.poll())
                self.assertNotIn(b'synthetic-secret',data)
                # No alternate-screen exit occurs before the explicit quit.
                self.assertNotIn(b'\x1b[?1049l',data)
                os.write(master,b'q');self.assertEqual(process.wait(timeout=5),0)
            finally:
                if process.poll() is None:process.kill();process.wait()
                os.close(master)


if __name__=='__main__':unittest.main()

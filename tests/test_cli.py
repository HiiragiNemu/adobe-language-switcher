import contextlib
import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from adobe_language_switcher import windows
from adobe_language_switcher.cli import main


class TestCLI(unittest.TestCase):
    def test_bad_installation(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(['inspect',tmp]),1)
            self.assertIn('No supported executable',err.getvalue())

    def test_identity(self):
        with patch.object(windows,'user_identity',return_value='user-A'), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(['restore','some-id','--yes','--expected-user','user-B']),1)
            self.assertIn('account differs',err.getvalue())

    def test_empty_history(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['history','--state',str(Path(tmp)/'missing')]),0)
            self.assertEqual(out.getvalue().strip(),'[]')
            self.assertFalse((Path(tmp)/'missing').exists())

    def test_worker_entrypoint(self):
        command=windows.worker_command(['gui'])
        self.assertEqual(command[1:],['-m','adobe_language_switcher','gui'])

    def test_apply_requires_confirmation(self):
        with patch('adobe_language_switcher.cli.inspect_installation'), patch('adobe_language_switcher.cli.build_plan') as plan, contextlib.redirect_stderr(io.StringIO()), patch('adobe_language_switcher.cli.Engine') as engine:
            plan.return_value.summary.return_value={}
            self.assertEqual(main(['apply','synthetic']),1)
            engine.assert_not_called()

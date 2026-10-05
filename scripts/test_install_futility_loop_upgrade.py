import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class UpgradeTest(unittest.TestCase):
    def test_upgrade_checks_stop_integrity_and_repeated_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            package=root/'package'
            bundle=root/'bundle'
            store=root/'store'
            state_path=store/'evals/test/loop_state.json'
            for directory in (package/'scripts',package/'config',bundle,state_path.parent):
                directory.mkdir(parents=True)
            shutil.copy2(Path(__file__).with_name('install_futility_loop_upgrade.py'),bundle/'install.py')
            old=package/'scripts/run_futility_loop.py'
            old.write_text('old controller')
            new=bundle/'run_futility_loop.py'
            new.write_text('new controller')
            sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            def write(path,value): path.write_text(json.dumps(value))
            write(bundle/'upgrade.json',dict(source_commit='test',payload_sha256=sha(new),supported_script_sha256=[sha(old)]))
            manifest=package/'package_manifest.json'
            write(manifest,dict(schema='chilo.futility_bo_loop_package.v1',external_contract_sha256='contract',files={}))
            write(package/'config/loop.json',dict(store_root=str(store),loop_id='test'))
            write(state_path,dict(stopped=False,active=None,contract_sha256='contract'))
            (package/'package-files.sha256').write_text(''.join(sha(p)+'  '+str(p.relative_to(package))+'\n' for p in (old,manifest)))
            command=[sys.executable,str(bundle/'install.py'),str(package)]
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(old.read_text(),'old controller')
            write(state_path,dict(stopped=True,active=None,contract_sha256='contract'))
            state_bytes=state_path.read_bytes()
            for _ in range(2):
                subprocess.run(command,check=True,capture_output=True)
                subprocess.run(['sha256sum','-c','package-files.sha256'],cwd=package,check=True,capture_output=True)
                self.assertEqual(state_path.read_bytes(),state_bytes)
            self.assertEqual(old.read_bytes(),new.read_bytes())
            self.assertTrue(any((package/'repair-backup').iterdir()))
            old.write_text('unexpected edit')
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(old.read_text(),'unexpected edit')

if __name__=='__main__': unittest.main()

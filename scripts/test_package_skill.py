"""Package completeness regressions; synthetic files only."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from package_skill import package

class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=self.base/'test-skill';self.root.mkdir()
        for directory in ['references','scripts','assets']:(self.root/directory).mkdir()
        (self.root/'SKILL.md').write_text('---\nname: test-skill\ndescription: Synthetic\n---\n[Reference](references/new.md)\n')
        (self.root/'README.md').write_text('synthetic test')
        (self.root/'references/new.md').write_text('new guidance')
        (self.root/'scripts/new.py').write_text('print(1)')
        (self.root/'assets/new.js').write_text('const test=1;')
        self.manifest={'version':'1.0.0','required_files':['SKILL.md','README.md','references/new.md','scripts/new.py','assets/new.js']}
        (self.root/'skill_manifest.json').write_text(json.dumps(self.manifest))
    def tearDown(self):self.temp.cleanup()
    def run_package(self):return package(self.root,self.base/'package.zip',self.base/'report.json')
    def test_resources_and_hashes_included_cache_excluded(self):
        cache=self.root/'scripts/__pycache__';cache.mkdir();(cache/'old.pyc').write_bytes(b'cache')
        report=self.run_package()
        self.assertEqual(report['counts']['scripts'],1)
        self.assertIn('references/new.md',report['files'])
        with zipfile.ZipFile(self.base/'package.zip') as z:self.assertEqual(z.read('test-skill/assets/new.js'),b'const test=1;')
    def test_missing_required_file_stops_packaging(self):
        (self.root/'scripts/new.py').unlink()
        with self.assertRaises(ValueError):self.run_package()
    def test_credential_file_in_resource_tree_rejected(self):
        (self.root/'scripts/.env').write_text('synthetic')
        with self.assertRaises(ValueError):self.run_package()
    def test_bad_link_rejected(self):
        (self.root/'references/new.md').write_text('[missing](missing.md)')
        with self.assertRaises(ValueError):self.run_package()

if __name__=='__main__':unittest.main()

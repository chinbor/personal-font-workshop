"""Synthetic fonts only; no personal font files required. Needs fontTools."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/font_metrics.py'

def fixture(path):
    builder=FontBuilder(2048,isTTF=True)
    builder.setupGlyphOrder(['.notdef','space','H','p'])
    builder.setupCharacterMap({32:'space',72:'H',112:'p'})
    glyphs={}
    for name in ['.notdef','space','H','p']:
        pen=TTGlyphPen(None)
        if name!='space':
            low=-400 if name=='p' else 0
            pen.moveTo((80,low));pen.lineTo((700,low));pen.lineTo((700,1450));pen.lineTo((80,1450));pen.closePath()
        glyphs[name]=pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name:(1200,0 if name=='space' else 80) for name in glyphs})
    builder.setupHorizontalHeader(ascent=3200,descent=-800,lineGap=100)
    builder.setupNameTable({'familyName':'Trial Original','styleName':'Regular','uniqueFontIdentifier':'TrialOriginal-Regular-1',
        'fullName':'Trial Original Regular','psName':'TrialOriginal-Regular','version':'Version 1.000'})
    builder.setupOS2(version=4,sTypoAscender=3200,sTypoDescender=-800,sTypoLineGap=100,
        usWinAscent=3200,usWinDescent=800,usWeightClass=400,fsSelection=192)
    builder.setupPost(isFixedPitch=1)
    builder.save(path)

class FontMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'input.ttf';fixture(self.source)
        self.original=self.source.read_bytes()
    def run_cli(self,*args):
        self.assertTrue(SCRIPT.is_file(),'Generic font inspection/repair tool missing')
        return subprocess.run([sys.executable,str(SCRIPT),*map(str,args)],capture_output=True,text=True,encoding='utf8')
    def repair(self,output=None,extra=()):
        return self.run_cli('repair',self.source,output or self.root/'fixed','--family','Trial Fix',
            '--postscript','TrialFix-Regular','--version','1.001','--ascent','1700','--descent','500','--line-gap','40',*extra)
    def test_inspect_does_not_modify_font(self):
        r=self.run_cli('inspect',self.source);self.assertEqual(r.returncode,0,r.stderr)
        report=json.loads(r.stdout)
        self.assertEqual(report['em'],2048)
        self.assertEqual(report['sha256'],hashlib.sha256(self.original).hexdigest())
        self.assertEqual(report['outline_bounds'][1],-400)
        self.assertEqual(self.source.read_bytes(),self.original)
    def test_compare_detects_same_and_different_files(self):
        r=self.run_cli('inspect',self.source,'--compare',self.source)
        self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(json.loads(r.stdout)['same_file_bytes'])
        self.assertEqual(self.repair().returncode,0)
        r=self.run_cli('inspect',self.source,'--compare',self.root/'fixed/TrialFix-Regular.ttf')
        self.assertEqual(r.returncode,0,r.stderr);self.assertFalse(json.loads(r.stdout)['same_file_bytes'])
    def test_repair_uses_requested_metrics_and_preserves_other_tables(self):
        r=self.repair();self.assertEqual(r.returncode,0,r.stderr)
        a=TTFont(self.source,lazy=True);b=TTFont(self.root/'fixed/TrialFix-Regular.ttf',lazy=True)
        self.addCleanup(a.close);self.addCleanup(b.close)
        self.assertEqual((b['hhea'].ascent,b['hhea'].descent,b['hhea'].lineGap),(1700,-500,40))
        self.assertEqual((b['OS/2'].sTypoAscender,b['OS/2'].sTypoDescender,b['OS/2'].usWinDescent),(1700,-500,500))
        self.assertEqual(b['head'].unitsPerEm,2048)
        self.assertEqual(b['name'].getDebugName(1),'Trial Fix')
        for tag in a.reader.keys():
            if tag not in {'head','hhea','OS/2','name'}:self.assertEqual(a.reader[tag],b.reader[tag],tag)
        self.assertEqual(self.source.read_bytes(),self.original)
        report=json.loads((self.root/'fixed/repair-report.json').read_text())
        self.assertEqual(report['editor_verification'],'pending')
    def test_rejects_clipping(self):
        r=self.repair(extra=('--ascent','1000'))
        self.assertNotEqual(r.returncode,0);self.assertIn('clip',r.stderr)
        self.assertFalse((self.root/'fixed').exists())
    def test_rejects_overwrite(self):
        dest=self.root/'fixed';dest.mkdir();(dest/'keep.txt').write_text('keep')
        r=self.repair();self.assertNotEqual(r.returncode,0);self.assertIn('exists',r.stderr)
        self.assertEqual((dest/'keep.txt').read_text(),'keep')
    def test_requires_new_internal_family(self):
        r=self.repair(extra=('--family','Trial Original'))
        self.assertNotEqual(r.returncode,0);self.assertIn('family',r.stderr)
    def test_rejects_case_only_family_change(self):
        r=self.repair(extra=('--family','trial original'))
        self.assertNotEqual(r.returncode,0);self.assertIn('family',r.stderr)
    def test_preserves_hint_tables_and_glyph_programs(self):
        from array import array
        from fontTools.ttLib import newTable
        from fontTools.ttLib.tables.ttProgram import Program
        f=TTFont(self.source)
        for tag in ('fpgm','prep'):
            table=newTable(tag);table.program=Program();table.program.fromBytecode([0xB0,0,0x21]);f[tag]=table
        cvt=newTable('cvt ');cvt.values=array('h',[40,80]);f['cvt ']=cvt
        f['glyf']['H'].program=Program();f['glyf']['H'].program.fromBytecode([0xB0,0,0x21])
        f.save(self.source);f.close()
        r=self.repair();self.assertEqual(r.returncode,0,r.stderr)
        a=TTFont(self.source,lazy=True);b=TTFont(self.root/'fixed/TrialFix-Regular.ttf',lazy=True)
        self.addCleanup(a.close);self.addCleanup(b.close)
        for tag in ('fpgm','prep','cvt ','glyf'):self.assertEqual(a.reader[tag],b.reader[tag],tag)
    def test_rejects_bad_postscript_name(self):
        r=self.repair(extra=('--postscript','../bad'))
        self.assertNotEqual(r.returncode,0);self.assertFalse((self.root/'fixed').exists())
    def test_rejects_non_regular_style(self):
        f=TTFont(self.source);f['OS/2'].usWeightClass=700;f.save(self.source);f.close()
        r=self.repair();self.assertNotEqual(r.returncode,0);self.assertIn('Regular',r.stderr)
    def test_rejects_negative_descent(self):
        r=self.repair(extra=('--descent','-500'))
        self.assertNotEqual(r.returncode,0);self.assertFalse((self.root/'fixed').exists())

if __name__=='__main__':unittest.main()

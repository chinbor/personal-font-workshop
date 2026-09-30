"""Run using: fontforge -lang=py -script build_font.py project.json NEW_OUTPUT_DIR"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from project import load,require

def build(manifest,output):
    import fontforge
    import psMat
    doc,root=load(manifest)
    dest=Path(output).resolve()
    require(not dest.exists(),'Output already exists; choose a new version directory')
    dest.mkdir(parents=True)
    font=fontforge.font(); font.encoding='UnicodeFull'
    font.em=doc['em']; font.ascent=doc['ascent']; font.descent=doc['descent']
    font.familyname=doc['family']; font.fontname=doc['postscript_name']
    font.fullname=doc['family']+' Regular'; font.weight='Regular'; font.version=doc['version']
    font.os2_weight=doc['weight_class']; font.os2_width=5
    # FontForge defaults these fields to offsets from font bounds/em metrics.
    for name in ('hhea_ascent_add','hhea_descent_add','os2_typoascent_add',
                 'os2_typodescent_add','os2_winascent_add','os2_windescent_add'):
        setattr(font,name,False)
    font.os2_typoascent=doc['line_ascent']; font.os2_typodescent=-doc['line_descent']; font.os2_typolinegap=doc['line_gap']
    font.hhea_ascent=doc['line_ascent']; font.hhea_descent=-doc['line_descent']; font.hhea_linegap=doc['line_gap']
    font.os2_winascent=doc['line_ascent']; font.os2_windescent=doc['line_descent']; font.os2_use_typo_metrics=True
    font.sfnt_names=(('English (US)','Family',doc['family']),('English (US)','SubFamily','Regular'),
        ('English (US)','Fullname',font.fullname),('English (US)','PostScriptName',font.fontname),
        ('English (US)','Version','Version '+doc['version']),('English (US)','UniqueID',font.fontname+'-'+doc['version']))
    if doc.get('copyright'): font.copyright=doc['copyright']
    missing=font.createChar(-1,'.notdef'); pen=missing.glyphPen()
    width=doc['default_advance']; left=width*.15; right=width*.85; top=doc['em']*.65; inset=doc['em']*.045
    pen.moveTo((left,0)); pen.lineTo((right,0)); pen.lineTo((right,top)); pen.lineTo((left,top)); pen.closePath()
    pen.moveTo((left+inset,inset)); pen.lineTo((left+inset,top-inset)); pen.lineTo((right-inset,top-inset)); pen.lineTo((right-inset,inset)); pen.closePath(); pen=None
    missing.correctDirection(); missing.width=width
    for record in doc['glyphs']:
        cp=record['codepoint']; glyph=font.createChar(cp)
        if record['file'] is not None:
            glyph.importOutlines(str(root/record['file']),scale=False)
            a,b,c,d=glyph.boundingBox(); x0,y0,x1,y1=record['target_bounds']
            require(c>a and d>b,'Imported empty outline: U+%04X'%cp)
            sx=(x1-x0)/(c-a); sy=(y1-y0)/(d-b)
            require(abs(sx/sy-1)<.005,'Aspect ratio mismatch; do not stretch U+%04X'%cp)
            # Restore the explicitly designed absolute font-unit bbox, NOT a shared fit-to-box.
            glyph.transform(psMat.scale(sy)); a,b,c,d=glyph.boundingBox()
            glyph.transform(psMat.translate(x0-a,y0-b))
            glyph.removeOverlap(); glyph.correctDirection(); glyph.round()
            # Integer rounding can turn near-tangent segments into intersections.
            glyph.removeOverlap(); glyph.correctDirection(); glyph.addExtrema('all')
        glyph.width=record['advance']
    if doc['autohint']: font.selection.all(); font.autoHint()
    stem=doc['postscript_name']; sfd=dest/(stem+'.sfd'); ttf=dest/(stem+'.ttf')
    font.save(str(sfd)); font.generate(str(ttf)); font.close()
    check=fontforge.open(str(ttf)); issues=[]; rows=[]
    require(check.familyname==doc['family'] and check.fontname==stem,'Generated internal names differ')
    expected_metrics={'hhea_ascent':doc['line_ascent'],'hhea_descent':-doc['line_descent'],
        'hhea_linegap':doc['line_gap'],'os2_typoascent':doc['line_ascent'],
        'os2_typodescent':-doc['line_descent'],'os2_typolinegap':doc['line_gap'],
        'os2_winascent':doc['line_ascent'],'os2_windescent':doc['line_descent']}
    metrics={name:getattr(check,name) for name in expected_metrics}
    for name,value in expected_metrics.items():
        if metrics[name]!=value: issues.append({'error':'line metric mismatch','field':name,'actual':metrics[name],'expected':value})
    for r in doc['glyphs']:
        cp=r['codepoint']
        if cp not in check: issues.append({'codepoint':cp,'error':'missing'}); continue
        g=check[cp]; bounds=list(g.boundingBox()); state=g.validate(True)
        if g.width!=r['advance']: issues.append({'codepoint':cp,'error':'advance mismatch'})
        empty=len(g.foreground)==0
        if empty!=(cp in (32,160)): issues.append({'codepoint':cp,'error':'unexpected blank/visible outline'})
        if state: issues.append({'codepoint':cp,'validation_bitmask':state})
        if not empty:
            expected=r['target_bounds']
            if max(abs(a-b) for a,b in zip(bounds,expected))>3: issues.append({'codepoint':cp,'error':'bounds changed by more than 3 units'})
            if bounds[1]<-doc['line_descent'] or bounds[3]>doc['line_ascent']: issues.append({'codepoint':cp,'error':'vertical clipping risk'})
        rows.append({'codepoint':cp,'advance':g.width,'bounds':bounds,'validation':state})
    check.close()
    report={'status':'structural-pass' if not issues else 'failed','family':doc['family'],'postscript_name':stem,
        'character_count':len(doc['glyphs']),'spacing':doc['spacing'],'issues':issues,'glyphs':rows,'line_metrics':metrics,
        'visual_review':'required: intended editor at 12/14/16/20px; no visual quality claim from this script'}
    (dest/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    require(not issues,'Generated font needs repair; inspect build-report.json. Outputs retained for diagnosis.')
    print('STRUCTURAL PASS. Visual/editor review still required. Output: '+str(dest))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('manifest'); parser.add_argument('output')
    args=parser.parse_args()
    try: build(args.manifest,args.output)
    except ImportError: sys.exit('Run with FontForge Python, not ordinary Python; install FontForge with Python support.')
    except (ValueError,OSError,KeyError,TypeError) as exc: sys.exit('ERROR: '+str(exc))

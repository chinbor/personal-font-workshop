"""Inspect font identity/metrics or make an explicit metrics-only Regular TTF trial.

Requires Python 3.8+ and fontTools. Never installs fonts or modifies editor settings.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    from fontTools.ttLib import TTFont, TTLibError
    from fontTools.pens.boundsPen import BoundsPen
except ImportError:
    sys.exit('Missing fontTools. Install it in your chosen Python environment: python -m pip install fonttools')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def open_font(path):
    font=TTFont(path,lazy=True,recalcBBoxes=False,recalcTimestamp=False)
    require(font.flavor is None,'Use a standalone SFNT font, not a webfont')
    require(all(tag in font for tag in ('head','hhea','OS/2','name','hmtx','cmap')),
            'Required font tables missing')
    return font


def outline_bounds(font):
    glyphs=font.getGlyphSet()
    pen=BoundsPen(glyphs)
    for name in glyphs:
        glyphs[name].draw(pen)
    return list(pen.bounds) if pen.bounds else [0,0,0,0]


def inspect(path):
    with open_font(path) as font:
        h=font['hhea'];o=font['OS/2'];n=font['name']
        return {'path':str(Path(path).resolve()),'sha256':sha256(path),
            'family':n.getDebugName(16) or n.getDebugName(1),
            'style':n.getDebugName(17) or n.getDebugName(2),
            'postscript':n.getDebugName(6),'version':n.getDebugName(5),
            'em':font['head'].unitsPerEm,'characters':len(font.getBestCmap() or {}),
            'outline_bounds':outline_bounds(font),
            'hhea':[h.ascent,h.descent,h.lineGap],
            'typo':[o.sTypoAscender,o.sTypoDescender,o.sTypoLineGap],
            'win':[o.usWinAscent,o.usWinDescent],
            'use_typo_metrics':bool(o.fsSelection&128),
            'mapped_advances':sorted({font['hmtx'][g][0] for g in (font.getBestCmap() or {}).values()}),
            'editor_verification':'not established by file inspection'}


def repair(args):
    source=Path(args.source).resolve();dest=Path(args.output).resolve()
    require(not dest.exists(),'Output directory exists; choose a new directory')
    require(re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,62}',args.postscript) is not None,
            'Use a safe ASCII PostScript name, max 63 characters')
    require(args.family.strip() and not any(ord(c)<32 for c in args.family),'Invalid family name')
    require(re.fullmatch(r'\d+\.\d{1,4}',args.version) is not None and 0<float(args.version)<32768,
            'Use a positive version such as 1.001')
    require(0<args.ascent<=32767 and 0<=args.descent<=32767 and 0<=args.line_gap<=32767,
            'Metrics must fit signed 16-bit fields; ascent positive, descent/gap nonnegative')
    before=inspect(source)
    with open_font(source) as font:
        require('glyf' in font and not any(t in font for t in ('fvar','CFF ','CFF2','DSIG')),
                'Repair supports unsigned static TrueType outlines only, not variable/CFF/signed fonts')
        os2=font['OS/2']
        require(os2.version>=4,'Repair requires OS/2 version 4+ for USE_TYPO_METRICS; adapt older fonts separately')
        require(os2.usWeightClass==400 and not os2.fsSelection&33 and not font['head'].macStyle&3
                and before['style']=='Regular','Repair supports upright Regular (weight 400) only')
        old_families={font['name'].getDebugName(i).strip().casefold() for i in (1,16,21)
                      if font['name'].getDebugName(i)}
        require(args.family.strip().casefold() not in old_families,'Choose a new family for side-by-side editor testing')
        require(args.postscript.casefold()!=(before['postscript'] or '').casefold(),'Choose a new PostScript name')
        bounds=before['outline_bounds']
        require(args.ascent>=bounds[3] and args.descent>=-bounds[1],
                'Requested metrics would clip an outline; inspect full glyph bounds')
        # Snapshot serialized tables before any editing. Keep this strict rather than
        # silently accepting recompiled geometry or lost hinting as "metrics only".
        raw={tag:font.reader[tag] for tag in font.reader.keys()}
        font['hhea'].ascent=args.ascent; font['hhea'].descent=-args.descent
        font['hhea'].lineGap=args.line_gap
        os2.sTypoAscender=args.ascent;os2.sTypoDescender=-args.descent
        os2.sTypoLineGap=args.line_gap;os2.usWinAscent=args.ascent;os2.usWinDescent=args.descent
        os2.fsSelection|=128
        font['head'].fontRevision=float(args.version)
        names={1:args.family,2:'Regular',3:args.postscript+'-'+args.version,
            4:args.family+' Regular',5:'Version '+args.version,6:args.postscript,
            16:args.family,17:'Regular',21:args.family,22:'Regular'}
        table=font['name']
        for record in list(table.names):
            if record.nameID in names:
                table.setName(names[record.nameID],record.nameID,record.platformID,record.platEncID,record.langID)
        for name_id in (1,2,3,4,5,6,16,17):
            table.setName(names[name_id],name_id,3,1,0x409)
        dest.mkdir(parents=True)
        target=dest/(args.postscript+'.ttf')
        font.save(target)
    issues=[]
    allowed={'head','hhea','OS/2','name'}
    with open_font(target) as check:
        if set(raw)!=set(check.reader.keys()):issues.append('Table inventory changed')
        preserved=[]
        for tag in raw:
            if tag not in allowed:
                if tag not in check.reader or raw[tag]!=check.reader[tag]:issues.append('Unexpected table change: '+tag)
                else:preserved.append(tag)
    after=inspect(target)
    if after['hhea']!=[args.ascent,-args.descent,args.line_gap] or after['typo']!=after['hhea']:
        issues.append('Exported line metrics differ from request')
    if after['win']!=[args.ascent,args.descent] or not after['use_typo_metrics']:
        issues.append('Exported Windows metrics differ from request')
    if after['family']!=args.family or after['postscript']!=args.postscript:
        issues.append('Exported internal names differ from request')
    if sha256(source)!=before['sha256']:issues.append('Source file changed during operation')
    report={'status':'metrics-only-pass' if not issues else 'failed','before':before,'after':after,
        'byte_identical_tables':preserved,'issues':issues,'editor_verification':'pending',
        'scope':'Only metrics/names/revision changed; not a general font-quality certification'}
    (dest/'repair-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    require(not issues,'Verification failed; outputs retained for diagnosis: '+str(dest))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    audit=commands.add_parser('inspect',help='Read identity, hashes and metrics; never changes fonts')
    audit.add_argument('source');audit.add_argument('--compare',help='Known installed/delivered file path; no system scanning')
    fix=commands.add_parser('repair',help='Make a new static Regular TTF trial from explicit design metrics')
    fix.add_argument('source');fix.add_argument('output',help='New directory; existing directories are refused')
    for flag in ('family','postscript','version'):fix.add_argument('--'+flag,required=True)
    for flag in ('ascent','descent','line-gap'):fix.add_argument('--'+flag,type=int,required=True)
    args=parser.parse_args()
    if args.command=='repair':result=repair(args)
    else:
        result=inspect(args.source)
        if args.compare:
            result['comparison']=inspect(args.compare)
            result['same_file_bytes']=result['sha256']==result['comparison']['sha256']
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,TTLibError) as exc:sys.exit('ERROR: '+str(exc))

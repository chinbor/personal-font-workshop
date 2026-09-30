"""Plan/validate a personal font project. Python 3.8+, standard library only."""
import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

def filename(codepoint):
    return 'glyphs/U%04X.svg' % codepoint

def new_project(family, postscript, characters=None, nbsp=False, spacing='monospace', advance=600):
    codes=sorted(set(range(32,127)) if characters is None else {ord(c) for c in characters}|{32})
    if nbsp and 160 not in codes: codes.append(160)
    return {
        'format':1,'family':family,'postscript_name':postscript,'version':'0.100',
        'em':1000,'ascent':800,'descent':200,'line_ascent':850,'line_descent':250,'line_gap':0,
        'spacing':spacing,'default_advance':advance,'weight_class':400,'autohint':False,
        'required_codepoints':codes,
        'glyphs':[{'codepoint':cp,'character':chr(cp),'file':None if cp in (32,160) else filename(cp),
                   'target_bounds':None,'advance':advance} for cp in codes]
    }

def require(condition,message):
    if not condition: raise ValueError(message)

def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def check_svg(path):
    raw=path.read_text(encoding='utf-8-sig')
    require('<!DOCTYPE' not in raw.upper() and '<!ENTITY' not in raw.upper(),'Unsupported SVG DTD/entity: '+str(path))
    root=ET.fromstring(raw)
    paths=0
    for e in root.iter():
        tag=e.tag.rsplit('}',1)[-1]
        require(tag in ('svg','g','path','title','desc'), 'Unsupported SVG element '+tag+': '+str(path))
        for attr in e.attrib:
            local=attr.rsplit('}',1)[-1]
            require(local in ('width','height','viewBox','version','id','d','fill','fill-rule'),
                    'Unsupported SVG attribute '+local+'; flatten transforms/styles and expand strokes: '+str(path))
        require(e.attrib.get('fill','#000').lower() in ('#000','#000000','black'), 'SVG must contain black filled outlines: '+str(path))
        if tag=='path':
            paths+=1
            data=e.attrib.get('d','').strip()
            parts=re.findall(r'[Mm][^Mm]*',data)
            require(parts and all(p.rstrip().endswith(('Z','z')) for p in parts), 'Every SVG contour must be explicitly closed: '+str(path))
    require(paths>0,'No SVG paths: '+str(path))

def validate(doc, root, files=True):
    require(doc.get('format')==1,'Unsupported project format')
    require(isinstance(doc.get('family'),str) and doc['family'].strip(),'family must not be empty')
    require(re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,62}',doc.get('postscript_name','')) is not None,'Use a safe ASCII postscript_name (max 63 characters)')
    require(re.fullmatch(r'\d+\.\d+',doc.get('version','')) is not None,'version must be numeric, e.g. 0.100')
    for key in ('em','ascent','descent','line_ascent','line_descent','default_advance','weight_class'):
        require(isinstance(doc.get(key),int) and not isinstance(doc[key],bool) and doc[key]>0,key+' must be a positive integer')
    require(doc['ascent']+doc['descent']==doc['em'],'ascent + descent must equal em')
    require(16<=doc['em']<=16384,'em must be 16..16384')
    require(1<=doc['weight_class']<=1000,'weight_class must be 1..1000')
    require(isinstance(doc.get('line_gap'),int) and doc['line_gap']>=0,'line_gap must be nonnegative')
    require(isinstance(doc.get('autohint'),bool),'autohint must be true or false')
    require(doc.get('spacing') in ('monospace','proportional'),'Unknown spacing mode')
    records=doc.get('glyphs',[])
    require(isinstance(records,list) and records,'glyphs must not be empty')
    seen=set(); paths=set(); base=Path(root).resolve()
    for g in records:
        cp=g.get('codepoint')
        require(isinstance(cp,int) and not isinstance(cp,bool) and 0<=cp<=0x10ffff and not 0xd800<=cp<=0xdfff,'Invalid Unicode codepoint')
        require(cp not in seen,'Duplicate Unicode codepoint: U+%04X'%cp); seen.add(cp)
        require(g.get('character')==chr(cp),'character/codepoint mismatch: U+%04X'%cp)
        require(isinstance(g.get('advance'),int) and 0<g['advance']<=32767,'Invalid advance: U+%04X'%cp)
        if doc['spacing']=='monospace': require(g['advance']==doc['default_advance'],'All monospace advances, including spaces, must match')
        if cp in (32,160):
            require(g.get('file') is None and g.get('target_bounds') is None,'Space/NBSP must be blank, with no file or bounds')
            continue
        name=g.get('file')
        require(isinstance(name,str) and name,'Missing SVG file: U+%04X'%cp)
        p=Path(name); target=(base/p).resolve()
        require(not p.is_absolute() and base in target.parents,'SVG paths must stay inside the project directory')
        require('\\' not in name and not any(c in name for c in ':*?"<>|'),'Use portable relative SVG filenames with forward slashes')
        require(name.casefold() not in paths,'Duplicate SVG filename on case-insensitive filesystems'); paths.add(name.casefold())
        bounds=g.get('target_bounds')
        require(isinstance(bounds,list) and len(bounds)==4 and all(number(v) for v in bounds),'Missing/invalid target_bounds: U+%04X'%cp)
        x0,y0,x1,y1=bounds
        require(x1>x0 and y1>y0,'Degenerate target_bounds: U+%04X'%cp)
        require(-doc['line_descent']<=y0<y1<=doc['line_ascent'],'target_bounds outside vertical line metrics: U+%04X'%cp)
        require(0<=x0<x1<=g['advance'],'This basic Latin builder requires outlines inside their advance: U+%04X'%cp)
        if files:
            require(target.is_file(),'Missing SVG: '+str(target)); check_svg(target)
    required=doc.get('required_codepoints')
    require(isinstance(required,list) and required and all(isinstance(cp,int) for cp in required),'required_codepoints must be a nonempty list')
    require(set(required)==seen,'Character coverage differs from required_codepoints')
    require(32 in seen,'Include U+0020 SPACE')
    return doc

def load(path):
    path=Path(path).resolve()
    doc=json.loads(path.read_text(encoding='utf-8-sig'))
    return validate(doc,path.parent),path.parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init',help='Create a new, non-overwriting project plan; outlines are not generated')
    init.add_argument('directory'); init.add_argument('--family',required=True); init.add_argument('--postscript',required=True)
    init.add_argument('--characters',default=None,help='Trial subset; default is all printable ASCII')
    init.add_argument('--nbsp',action='store_true'); init.add_argument('--spacing',choices=['monospace','proportional'],default='monospace')
    init.add_argument('--advance',type=int,default=600)
    check=sub.add_parser('check'); check.add_argument('manifest')
    args=parser.parse_args()
    if args.command=='check':
        doc,_=load(args.manifest); print('PASS: %d mapped characters, inputs and placement checked'%len(doc['glyphs'])); return
    root=Path(args.directory).resolve()
    require(not root.exists(),'Destination exists; choose a new project directory')
    doc=new_project(args.family,args.postscript,args.characters,args.nbsp,args.spacing,args.advance)
    # Validate identity/settings before writing, allowing the deliberate unfinished outline plan.
    require(re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,62}',args.postscript) is not None,'Invalid --postscript')
    require(bool(args.family.strip()) and 0<args.advance<=32767,'Invalid family/advance')
    root.mkdir(parents=True); (root/'glyphs').mkdir()
    (root/'project.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf8')
    proof=''.join(chr(cp) for cp in doc['required_codepoints'] if cp not in (32,160))
    candidates=['Il1|  O0o  rn m  2Z  5S  6G  8B','{} [] () <> / \\',
        ':; ,. \'" `~ +-*/% =! &|^_','const count = 10;',
        'if (value != null) { return value; }','A A  A   A']
    supported={chr(cp) for cp in doc['required_codepoints']}
    lines=[proof,' '.join(proof)]
    lines.extend(line for line in candidates if set(line)<=supported)
    (root/'proof.txt').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print('Created outline plan. Fill SVG files and target_bounds before building: '+str(root/'project.json'))

if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,TypeError,OSError,ET.ParseError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr); sys.exit(2)

#!/usr/bin/env python3
"""Build a shareable PDF from the canonical public technical report and charts."""
from __future__ import annotations
import argparse
from functools import partial
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

from verify_research_figures import verify_figure_provenance

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/research/technical-report.md'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_link(target, source=SOURCE, root=ROOT):
    """Preserve URL query/fragment syntax when mapping a repository-relative link."""
    url = urlsplit(target)
    if url.scheme or url.netloc:
        return target
    destination = (source.parent / url.path).resolve() if url.path else source.resolve()
    try:
        relative = destination.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError('Report link escapes repository') from exc
    kind = 'tree' if destination.is_dir() else 'blob'
    result = f'https://github.com/laxman-kc/UAV-VLA-Lab/{kind}/main/' + quote(relative.as_posix(), safe='/')
    if url.query:
        result += '?' + url.query
    if url.fragment:
        result += '#' + url.fragment
    return result


def build(output):
    figure_verification = verify_figure_provenance()
    import matplotlib
    import reportlab
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle

    fonts = Path(matplotlib.get_data_path()) / 'fonts/ttf'
    for face, name in [('LabSans','DejaVuSans.ttf'), ('LabBold','DejaVuSans-Bold.ttf'), ('LabMono','DejaVuSansMono.ttf')]:
        pdfmetrics.registerFont(TTFont(face, str(fonts / name)))
    pdfmetrics.registerFontFamily('LabSans', normal='LabSans', bold='LabBold', italic='LabSans', boldItalic='LabBold')
    navy, teal, gray = map(colors.HexColor, ['#102c3b','#087e83','#526874'])
    styles = {
        'body': ParagraphStyle('body', fontName='LabSans', fontSize=9, leading=14, spaceAfter=8, textColor=navy),
        'title': ParagraphStyle('title', fontName='LabBold', fontSize=25, leading=31, spaceAfter=18, textColor=navy, keepWithNext=True),
        'h2': ParagraphStyle('h2', fontName='LabBold', fontSize=14, leading=19, spaceBefore=17, spaceAfter=8, textColor=navy, keepWithNext=True),
        'caption': ParagraphStyle('caption', fontName='LabSans', fontSize=7.5, leading=11, spaceAfter=13, textColor=gray),
        'cell': ParagraphStyle('cell', fontName='LabSans', fontSize=7, leading=10, textColor=navy),
        'bullet': ParagraphStyle('bullet', fontName='LabSans', fontSize=9, leading=14, spaceAfter=6, textColor=navy, leftIndent=13, firstLineIndent=-10),
    }
    def inline(text):
        text = text.replace('–','-').replace('—','-').replace('‑','-').replace('−','-')
        saved=[]
        def link(match):
            label, target=match.groups()
            target = repository_link(target)
            saved.append('<link href="' + html.escape(target,quote=True) + '" color="#087e83">' + html.escape(label) + '</link>')
            return f'LINKTOKEN{len(saved)-1}TOKEN'
        text=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,text)
        text=html.escape(text)
        text=re.sub(r'\*\*([^*]+)\*\*',r'<b>\1</b>',text)
        text=re.sub(r'`([^`]+)`',r'<font name="LabMono" size="8">\1</font>',text)
        for i, value in enumerate(saved): text=text.replace(f'LINKTOKEN{i}TOKEN',value)
        return text

    output.parent.mkdir(parents=True,exist_ok=True)
    doc=SimpleDocTemplate(str(output),pagesize=letter,rightMargin=48,leftMargin=48,topMargin=53,bottomMargin=48,
                          title='UAV-VLA-Lab: Audited adaptation of a released UAV policy in simulation',
                          author='UAV-VLA-Lab contributors', subject='Technical research report; a small single-map simulation study')
    story=[]; inputs=[SOURCE]; lines=SOURCE.read_text().splitlines(); i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line: i+=1;continue
        image=re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)',line)
        if image:
            caption, path=image.groups(); p=(SOURCE.parent/path).resolve().with_suffix('.png')
            with PILImage.open(p) as im: w,h=im.size
            width=doc.width; height=width*h/w
            story.append(Image(str(p),width=width,height=height))
            story.append(Paragraph(inline(caption),styles['caption']));inputs.append(p);i+=1;continue
        if line.startswith('|'):
            table=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                row=[c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c) for c in row):
                    table.append([Paragraph(inline(c),styles['cell']) for c in row])
                i+=1
            t=Table(table,colWidths=[doc.width/len(table[0])]*len(table[0]),repeatRows=1,hAlign='LEFT',splitByRow=0)
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7f1f2')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,0),(-1,0),.8,teal),('LINEBELOW',(0,1),(-1,-1),.4,colors.HexColor('#dbe4e5'))]))
            story.extend([t,Spacer(1,10)]);continue
        if line.startswith('# '): story.append(Paragraph(inline(line[2:]),styles['title']));i+=1;continue
        if line.startswith('## '): story.append(Paragraph(inline(line[3:]),styles['h2']));i+=1;continue
        if line.startswith('- ') or re.match(r'\d+\. ',line):
            story.append(Paragraph(inline(line),styles['bullet']));i+=1;continue
        paragraph=[line];i+=1
        while i<len(lines) and lines[i].strip() and not re.match(r'^(#|\||!\[|- |\d+\. )',lines[i].strip()):
            paragraph.append(lines[i].strip());i+=1
        story.append(Paragraph(inline(' '.join(paragraph)),styles['body']))
    def footer(c, doc):
        c.setStrokeColor(colors.HexColor('#dbe4e5'));c.line(48,35,564,35)
        c.setFont('LabSans',7);c.setFillColor(gray)
        c.drawString(48,23,'UAV-VLA-Lab | simulation-sft-v1 | Technical report')
        c.drawRightString(564,23,str(doc.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer,canvasmaker=lambda *a,**kw: canvas.Canvas(*a,**{**kw,'invariant':1}))
    record={'schema_version':'uav-vla-lab.report-pdf.v1','source': [{'file':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in inputs],
            'figure_verification':figure_verification,
            'renderer':{'file':'tools/render_technical_report.py','sha256':sha(Path(__file__))},
            'versions':{'reportlab':reportlab.Version,'matplotlib':matplotlib.__version__},
            'output':{'file':output.name,'bytes':output.stat().st_size,'sha256':sha(output)},
            'scope':'PDF rendition of the canonical public technical report and its three numeric charts; no new experiment'}
    output.with_suffix('.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record['output']))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'output/pdf/uav-vla-lab-technical-report.pdf')
    build(p.parse_args().output)

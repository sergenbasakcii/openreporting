"""Render the evidence matrix from its JSON source; do not turn open controls green."""
from collections import Counter
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    controls = json.loads((ROOT / 'docs/enterprise-controls.json').read_text(encoding='utf8'))['controls']
    assert len(controls) >= 100 and len({c['id'] for c in controls}) == len(controls)
    assert all(re.fullmatch(r'[A-Z][0-9]{2,3}',c['id']) and c['status'] in {'V','R','P','O','E'} for c in controls)
    for control in controls:
        evidence = (ROOT / control['evidence']).resolve()
        assert evidence.is_relative_to(ROOT) and evidence.is_file(),control['id']
    path = ROOT / 'docs/ENTERPRISE_REVIEW.md'
    intro = path.read_text(encoding='utf8').split('## A —')[0]
    counts = Counter(c['status'] for c in controls)
    summary = 'Durum dağılımı: '+', '.join(f'{key}: {counts[key]}' for key in ('V','R','P','O','E'))+'.'
    intro = re.sub(r'Durum dağılımı: [^\n]+',summary,intro)
    sections = {}
    for control in controls:
        sections.setdefault((control['id'][0],control['area']),[]).append(control)
    output = intro
    def cell(value):
        return value.replace('|',r'\|').replace('\n',' ')
    for (prefix,title),items in sections.items():
        output += f'## {prefix} — {title}\n\n| Kimlik | Kontrol | Durum | Öncelik | Kanıt / kalan iş |\n| --- | --- | --- | --- | --- |\n'
        for c in items:
            output += f"| {c['id']} | {cell(c['control'])} | {c['status']} | {c['priority']} | [{c['evidence']}](../{c['evidence']}) — {cell(c['note'])} |\n"
        output += '\n'
    path.write_text(output,encoding='utf8')
    print(f'{len(controls)} unique evidence controls rendered; {dict(counts)}')


if __name__ == '__main__':
    main()

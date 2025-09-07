#!/usr/bin/env python3
# import sys
import re
import html
import argparse
from pathlib import Path

INPUT_PATH = Path("developer.rhino3d.com/api/RhinoScriptSyntax/index.html")
OUTPUT_PATH = Path("ref_api_rhinoscriptsyntax_all.txt")

def read_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def html_to_text(s):
    s = re.sub(r'<[^>]+>', '', s)
    return html.unescape(s)

ANCHOR_RE = re.compile(r'<a\s+role="button"\s+class="code_accordion"[^>]*>\s*<div[^>]+id=["\']([^"\']+)["\'][^>]*>([^<]+)</div>\s*</a>', re.IGNORECASE)
CODEPANEL_RE = re.compile(r'<div\s+class="code_panel">', re.IGNORECASE)
NEXT_BLOCK_RE = re.compile(r'(?=<a\s+role="button"\s+class="code_accordion"|<h2\b|$)', re.IGNORECASE)
SIG_RE = re.compile(r'<pre[^>]*>\s*<code[^>]*class=["\']language-python["\'][^>]*>([\s\S]*?)</code>\s*</pre>', re.IGNORECASE)

def iter_blocks(html_text):
    pos = 0
    while True:
        m = ANCHOR_RE.search(html_text, pos)
        if not m:
            break
        func_name = m.group(2).strip()
        m2 = CODEPANEL_RE.search(html_text, m.end())
        if not m2:
            pos = m.end()
            continue
        m3 = NEXT_BLOCK_RE.search(html_text, m2.end())
        end = m3.start() if m3 else len(html_text)
        panel_html = html_text[m2.end():end]
        yield (func_name, panel_html)
        pos = end

def norm(s): return (s or "").strip().lower()

def build_type_mapper(style):
    """Return a mapper(label:str)->str according to requested style."""
    # Pythonic types (ids as str, colors as tuple, etc.)
    py_map = {
        'none':'None', 'void':'None',
        'bool':'bool','boolean':'bool',
        'number':'float','double':'float','float':'float',
        'int':'int','integer':'int',
        'str':'str','string':'str',
        'guid':'str','uuid':'str',
        'date':'datetime.date','datetime.date':'datetime.date',
        'color':'Tuple[int, int, int]',
        'point':'Tuple[float, float, float]','point3d':'Tuple[float, float, float]',
        'vector':'Tuple[float, float, float]','vector3d':'Tuple[float, float, float]',
        'interval':'Tuple[float, float]',
        'plane':'Any',
        'matrix':'List[List[float]]','transform':'List[List[float]]',
    }
    # .NET-flavored (Plane, System.Guid, etc.).
    dn_map = {
        'none':'None', 'void':'None',
        'bool':'bool','boolean':'bool',
        'number':'float','double':'float','float':'float',
        'int':'int','integer':'int',
        'str':'str','string':'str',
        'guid':'System.Guid','uuid':'System.Guid',
        'date':'datetime.date','datetime.date':'datetime.date',
        'color':'System.Drawing.Color',
        'point':'Rhino.Geometry.Point3d','point3d':'Rhino.Geometry.Point3d',
        'vector':'Rhino.Geometry.Vector3d','vector3d':'Rhino.Geometry.Vector3d',
        'interval':'Tuple[float, float]',
        'plane':'Rhino.Geometry.Plane',
        'matrix':'Rhino.Geometry.Transform','transform':'Rhino.Geometry.Transform',
    }
    base_map = dn_map if style == 'dotnet' else py_map

    def map_type(label):
        t = norm(label)
        if not t: return 'Any'
        t = t.replace('–','-')
        # handle unions "number or guid" -> prefer first concrete
        if ' or ' in t:
            for part in [p.strip() for p in t.split(' or ') if p.strip()]:
                mt = base_map.get(part, None)
                if mt: return mt
            # If none matched, fall back to first
            return map_type(t.split(' or ',1)[0])

        # plural hints
        if t.startswith('list of ') or t.startswith('array of '):
            inner = t.split(' of ',1)[1].strip()
            return f'List[{map_type(inner)}]'
        if t.startswith('tuple of '):
            inner = t.split(' of ',1)[1].strip()
            m = re.match(r'(\d+)\s+([a-zA-Z0-9_.]+)s?$', inner)
            if m:
                n, base = int(m.group(1)), m.group(2)
                inner_t = map_type(base)
                return 'Tuple[' + ', '.join([inner_t]*n) + ']'
            return 'Tuple[Any, ...]'

        # base lookups
        if t in base_map:
            return base_map[t]

        # comma-annotations like "number, optional"
        if ',' in t:
            first = t.split(',',1)[0].strip()
            return map_type(first)

        # bracketed list hints: "[guid, ...]"
        if t.startswith('[') and '...' in t and ('guid' in t or 'uuid' in t):
            return f'List[{base_map.get("guid","str")}]'

        # heuristics
        if 'point' in t: return base_map.get('point')
        if 'vector' in t: return base_map.get('vector')
        if 'color' in t: return base_map.get('color')
        if 'interval' in t: return base_map.get('interval')
        if 'plane' in t: return base_map.get('plane')
        if 'transform' in t or 'matrix' in t: return base_map.get('transform')

        return 'Any'
    return map_type

PARAM_LINE_RE = re.compile(r'^\s*([A-Za-z_][\w,\s]*)\s*\(([^)]*)\)\s*:?', re.IGNORECASE)
OPTIONAL_TAG_RE = re.compile(r'\boptional\b', re.IGNORECASE)


def parse_params_block(pre_text, map_type):
    """
    Returns dict name -> {'type': '...', 'optional': bool}
    Supports grouped names like "width, height (number)" and lines without trailing colon.
    """
    mapping = {}
    for raw_line in pre_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        # ignore continuation/explanatory lines that are indented
        if (line.startswith('  ') or line.startswith('	')) and mapping:
            continue
        m = PARAM_LINE_RE.match(line.strip())
        if not m:
            # robust fallback
            if '(' in line and ')' in line:
                left = line.split(':',1)[0]
                names_part = left.split('(')[0].strip()
                inner = left[left.find('(')+1:left.rfind(')')]
                names = [n.strip() for n in names_part.split(',') if n.strip()]
                inner_clean = inner.split(',')[0].strip()
                optional = bool(OPTIONAL_TAG_RE.search(line))
                for nm in names:
                    mapping[nm] = {'type': map_type(inner_clean), 'optional': optional}
            continue
        names_part, type_label = m.groups()
        names = [n.strip() for n in names_part.split(',') if n.strip()]
        inner_clean = (type_label or '').split(',')[0].strip()
        optional = bool(OPTIONAL_TAG_RE.search(line))
        for nm in names:
            mapping[nm] = {'type': map_type(inner_clean), 'optional': optional}
    return mapping

def parse_returns_block(pre_text, map_type):
    lines = [ln.strip() for ln in pre_text.splitlines() if ln.strip()]
    ret_type = None
    saw_none = False
    for ln in lines:
        if re.search(r'\bNone on error\b', ln, re.IGNORECASE):
            saw_none = True
        token = ln.split(':',1)[0]
        t = map_type(token)
        if t != 'None' and ret_type is None:
            ret_type = t
        if t == 'None' and ret_type is None:
            ret_type = 'None'
    if ret_type is None:
        ret_type = 'None'
    if saw_none and ret_type != 'None' and not ret_type.startswith('Optional['):
        ret_type = f'Optional[{ret_type}]'
    return ret_type

def parse_signature(sig_text):
    sig_text = sig_text.strip().replace('\r','')
    sig_text = sig_text.splitlines()[0]
    m = re.match(r'^\s*([A-Za-z_]\w*)\s*\(\s*(.*?)\s*\)\s*$', sig_text)
    if not m:
        return None, []
    name, params_raw = m.groups()
    params = []
    if params_raw:
        parts = []
        depth = 0
        buf = []
        for ch in params_raw:
            if ch == '(':
                depth += 1
                buf.append(ch)
            elif ch == ')':
                depth = max(0, depth-1)
                buf.append(ch)
            elif ch == ',' and depth == 0:
                parts.append(''.join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        if buf:
            parts.append(''.join(buf).strip())
        for p in parts:
            if not p:
                continue
            if '=' in p:
                n, d = p.split('=',1)
                params.append((n.strip(), d.strip()))
            else:
                params.append((p.strip(), None))
    return name, params

def build_typed_signature(func_name, sig_params, param_types, returns_type):
    items = []
    for name, default in sig_params:
        pinfo = param_types.get(name, {'type': 'Any', 'optional': False})
        ann = pinfo['type']
        optional = pinfo['optional']
        if optional and default is None and ann not in ('Any','None') and not ann.startswith('Optional['):
            ann = f'Optional[{ann}]'
            default = 'None'
        if default is None:
            items.append(f'{name}: {ann}')
        else:
            items.append(f'{name}: {ann} = {default}')
    args_str = ', '.join(items)
    return f'rhinoscriptsyntax.{func_name}({args_str}) -> {returns_type}'

def extract_all(input_html, output_txt, type_style='dotnet'):
    text = read_text(input_html)
    map_type = build_type_mapper(type_style)
    lines = []
    for func_name, panel_html in iter_blocks(text):
        m_sig = SIG_RE.search(panel_html)
        if not m_sig:
            continue
        sig_text = html_to_text(m_sig.group(1)).strip()
        func_name, sig_params = parse_signature(sig_text)
        if not func_name:
            continue

        # parameters block: first <pre> after a header containing "Parameters"
        m_params_hdr = re.search(r'<h[1-6][^>]*>\s*Parameters\s*:?\s*</h[1-6]>', panel_html, re.IGNORECASE)
        param_types = {}
        if m_params_hdr:
            m_pre = re.search(r'<pre[^>]*>([\s\S]*?)</pre>', panel_html[m_params_hdr.end():], re.IGNORECASE)
            if m_pre:
                params_block = html_to_text(m_pre.group(1))
                param_types = parse_params_block(params_block, map_type)

        # returns block
        returns_type = 'None'
        m_ret_hdr = re.search(r'<h[1-6][^>]*>\s*Returns\s*:?\s*</h[1-6]>', panel_html, re.IGNORECASE)
        if m_ret_hdr:
            m_ret_pre = re.search(r'<pre[^>]*>([\s\S]*?)</pre>', panel_html[m_ret_hdr.end():], re.IGNORECASE)
            if m_ret_pre:
                returns_type = parse_returns_block(html_to_text(m_ret_pre.group(1)), map_type)

        lines.append(build_typed_signature(func_name, sig_params, param_types, returns_type))

    lines = sorted(set(lines))
    with open(output_txt, 'w', encoding='utf-8') as f:
        for ln in lines:
            f.write(ln + '\n')
    print(f"Extracted {len(lines)} signatures to {output_txt}")

def main():
    # ap = argparse.ArgumentParser(description="Extract typed signatures from RhinoScriptSyntax HTML index.")
    # ap.add_argument("input_html", help="Path to index.html")
    # ap.add_argument("output_txt", nargs="?", default="rss_signatures.txt", help="Output text file")
    # ap.add_argument("--type-style", choices=["dotnet","python"], default="dotnet", help="Choose type mapping style")
    # args = ap.parse_args()
    # extract_all(args.input_html, args.output_txt, args.type_style)
    extract_all(INPUT_PATH, OUTPUT_PATH, type_style='dotnet')

if __name__ == "__main__":
    main()

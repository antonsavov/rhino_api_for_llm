
#!/usr/bin/env python3
# Extract Python-style method signatures from RhinoCommon HTML.
#
# Notes:
# - Processes files starting with "M_" and ending with ".htm" or ".html".
# - Derives fully-qualified method target (namespace.class.method) and *parameter types* from the
#   <meta name="Microsoft.Help.Id" ...> tag, because it contains fully-qualified types.
# - Derives *parameter names*, return type, and static/instance info from the C# "Syntax" code block.
# - Produces one line per method, e.g.:
#   Rhino.ApplicationSettings.AppearanceSettings.SetPaintColor(whichColor: Rhino.ApplicationSettings.PaintColor, c: System.Drawing.Color, forceUiUpdate: bool) -> None
#
# No external dependencies: uses only Python stdlib.
# Best-effort type mapping for common .NET types to Python typing names (float, int, bool, str).
# Unknown types are kept as-is (often fully-qualified Rhino/System types).
#
# © Anton Savov 2025 - MIT License

import os
import re
import html
import sys

# ---------- Configuration (overridden by CLI args if provided) ----------
INPUT_DIRS = [r"grasshopper-api-docs/api/grasshopper/html",r"rhinocommon-api-docs/api/RhinoCommon/html"]
OUTPUT_PATHS = [r"ref_api_grasshopper_all.txt", r"ref_api_rhinocommon_all.txt"]

# ---------- Helpers ----------

def read_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def extract_help_id(html_text):
    """
    Return the Microsoft.Help.Id content string, e.g.:
    'M:Rhino.Display.ColorHSL.CreateFromLCH(Rhino.Display.ColorLCH)'
    or for ctors:
    'M:Rhino.Display.ColorHSL.#ctor(System.Double,System.Double,System.Double)'
    """
    m = re.search(r'<meta[^>]+name=["\']Microsoft\.Help\.Id["\'][^>]+content=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
    if not m:
        return None
    return html.unescape(m.group(1))

def extract_csharp_pre(html_text):
    """
    Extract the C# Syntax code block inside the ..._code_Div1 container.
    Returns plain text (HTML tags stripped), or None if not found.
    """
    # Find the C# tab content block (conventionally *_code_Div1)
    m = re.search(r'<div[^>]+id=["\'][^"\']*_code_Div1["\'][\s\S]*?<pre[^>]*>([\s\S]*?)</pre>', html_text, re.IGNORECASE)
    if not m:
        # Fallback: first <pre> on page
        m = re.search(r'<pre[^>]*>([\s\S]*?)</pre>', html_text, re.IGNORECASE)
        if not m:
            return None
    pre_html = m.group(1)
    # Strip tags
    pre_text = re.sub(r'<[^>]+>', '', pre_html)
    # Unescape entities
    pre_text = html.unescape(pre_text)
    # Normalize whitespace
    pre_text = pre_text.replace('\r', '')
    return pre_text.strip()

def split_types_list(s):
    """
    Split a comma-separated type list that may contain nested generics like Dict{K,V}
    Uses angle-bracket style <...> and/or curly braces {..} (docs sometimes vary).
    Also ignores commas inside angle brackets or curly braces.
    """
    parts = []
    buf = []
    depth_angle = 0
    depth_curly = 0
    depth_paren = 0  # just in case
    for ch in s:
        if ch == '<':
            depth_angle += 1
            buf.append(ch)
        elif ch == '>':
            depth_angle = max(0, depth_angle - 1)
            buf.append(ch)
        elif ch == '{':
            depth_curly += 1
            buf.append(ch)
        elif ch == '}':
            depth_curly = max(0, depth_curly - 1)
            buf.append(ch)
        elif ch == '(':
            depth_paren += 1
            buf.append(ch)
        elif ch == ')':
            depth_paren = max(0, depth_paren - 1)
            buf.append(ch)
        elif ch == ',' and (depth_angle == 0 and depth_curly == 0 and depth_paren == 0):
            parts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf).strip())
    # Remove empty strings
    parts = [p for p in parts if p]
    return parts

def parse_help_id(help_id):
    """
    Parse the Microsoft.Help.Id string for methods.
    Returns:
        container_fqn (e.g., 'Rhino.Display.ColorHSL')
        method_raw (e.g., 'CreateFromLCH' or '#ctor')
        param_types (list of fully-qualified types as in the meta)
    """
    if not help_id or not help_id.startswith('M:'):
        return None, None, []
    body = help_id[2:]  # strip 'M:'
    # Split on first '(' to isolate method target vs params
    if '(' in body:
        left, right = body.split('(', 1)
        params_part = right.rsplit(')', 1)[0] if ')' in right else right
    else:
        left = body
        params_part = ''
    # Method name is the segment after last '.'
    # But there is a special '#ctor'
    if '.#ctor' in left:
        container_fqn = left.split('.#ctor')[0]
        method_raw = '#ctor'
    else:
        container_fqn, method_raw = left.rsplit('.', 1)

    param_types = split_types_list(params_part) if params_part else []
    return container_fqn, method_raw, param_types

CS_ACCESS_KWS = {'public','private','protected','internal'}
CS_MODIFIER_KWS = {'static','virtual','override','sealed','extern','unsafe','abstract','new','readonly','partial','async'}

def parse_csharp_signature(cs_text, container_simple):
    """
    From the C# code snippet, derive:
      - return_type (string), or None for constructors
      - method_name (string), e.g., 'SetPaintColor' or container name for constructor
      - param_names (list)
      - is_static (bool)
    container_simple is the simple class/struct name (e.g., 'ColorHSL')
    """
    if not cs_text:
        return None, None, [], False

    # Reduce to the first signature block: from start to first closing paren ')'
    # This should cover most cases including multi-line parameter lists.
    # Remove trailing method body or semicolons.
    text = cs_text.strip()
    # Keep only up to the first closing parenthesis followed by optional tokens
    # to avoid parsing property accessors or multiple overloads in the same block.
    if ')' in text:
        text = text[:text.index(')')+1]

    # Collapse whitespace for easier parsing
    oneline = ' '.join(text.replace('\n', ' ').split())
    # Example:
    # 'public static void SetPaintColor( PaintColor whichColor, Color c, bool forceUiUpdate )'
    # 'public ColorHSL( Color rgb )'

    is_static = ' static ' in f' {oneline} '

    # Extract parameter list (between outermost parentheses)
    params_part = ''
    if '(' in oneline and ')' in oneline:
        head, params = oneline.split('(', 1)
        params_part = params.rsplit(')', 1)[0].strip()
    else:
        head = oneline

    # Clean head: remove access & modifiers
    head_tokens = [t for t in head.strip().split() if t not in CS_ACCESS_KWS and t not in CS_MODIFIER_KWS]
    # Now, head_tokens is like ['void','SetPaintColor'] or ['ColorHSL'] (constructor)
    method_name = None
    return_type = None
    if len(head_tokens) == 1:
        # Constructor: e.g., ['ColorHSL']
        method_name = head_tokens[0]
        return_type = None  # constructors return None in Python
    elif len(head_tokens) >= 2:
        return_type = head_tokens[-2]
        method_name = head_tokens[-1]

    # Parameter names: split on commas not in generic angles/curly
    param_names = []
    if params_part:
        parts = split_types_list(params_part)
        for p in parts:
            # Remove default values and ref/out/params/in keywords
            p = p.strip()
            p = re.sub(r'\s*=\s*[^,]+$', '', p)  # remove default = value
            p = re.sub(r'^(this|ref|out|params|in)\s+', '', p)
            # Name is the last token
            tokens = p.split()
            if tokens:
                name = tokens[-1]
                # Strip trailing commas if any
                name = name.rstrip(',')
                # Handle array indicator on name (should be on type, but be safe)
                name = name.replace('[]','')
                # Clean @ prefixes (verbatim identifiers)
                name = name.lstrip('@')
                # Fallback for weird cases
                if not re.match(r'^[A-Za-z_]\w*$', name):
                    name = f'arg{len(param_names)+1}'
                param_names.append(name)
            else:
                param_names.append(f'arg{len(param_names)+1}')
    return return_type, method_name, param_names, is_static

# Basic .NET -> Python type mapping
def map_dotnet_to_python(t, container_fqn=None, container_simple=None):
    t = t.strip()
    # Common aliases
    aliases = {
        'System.Void': 'None',
        'void': 'None',
        'System.Boolean': 'bool',
        'bool': 'bool',
        'System.Double': 'float',
        'double': 'float',
        'System.Single': 'float',
        'float': 'float',
        'System.Int32': 'int',
        'int': 'int',
        'System.Int64': 'int',
        'long': 'int',
        'System.String': 'str',
        'string': 'str',
        'System.Object': 'Any',
        'object': 'Any',
    }
    # Arrays: Type[]
    if t.endswith('[]'):
        inner = t[:-2].strip()
        return f'List[{map_dotnet_to_python(inner, container_fqn, container_simple)}]'
    # Nullable: Nullable{T} or T?
    m = re.match(r'(?:System\.)?Nullable\{(.+)\}$', t)
    if m:
        inner = m.group(1).strip()
        return f'Optional[{map_dotnet_to_python(inner, container_fqn, container_simple)}]'
    if t.endswith('?') and not t.endswith('??'):
        inner = t[:-1]
        return f'Optional[{map_dotnet_to_python(inner, container_fqn, container_simple)}]'
    # Generics like List{T}, Dictionary{K,V}, IEnumerable{T}
    m = re.match(r'(?P<base>[\w\.]+)\{(?P<inner>.+)\}$', t)
    if m:
        base = m.group('base')
        inner = m.group('inner')
        inner_parts = split_types_list(inner)
        mapped_inners = [map_dotnet_to_python(p, container_fqn, container_simple) for p in inner_parts]
        base_map = {
            'System.Collections.Generic.List': 'List',
            'System.Collections.Generic.IList': 'List',
            'System.Collections.Generic.IReadOnlyList': 'Sequence',
            'System.Collections.Generic.IEnumerable': 'Iterable',
            'System.Collections.Generic.ICollection': 'Sequence',
            'System.Collections.Generic.Dictionary': 'Dict',
            'System.Collections.Generic.IDictionary': 'Dict',
            'System.Tuple': 'Tuple',
        }
        py_base = base_map.get(base, base.split('.')[-1])  # fallback: last segment
        inner_str = ', '.join(mapped_inners)
        return f'{py_base}[{inner_str}]'
    # If simple alias exists
    if t in aliases:
        return aliases[t]
    # If return type equals the container simple name, qualify it
    if container_simple and t == container_simple:
        return container_fqn or t
    return t  # keep as-is (e.g., Rhino.Display.ColorLCH, System.Drawing.Color, etc.)

def build_signature_line(container_fqn, method_raw, param_types, cs_return_type, cs_method_name, param_names, is_static):
    # Determine final method name
    container_simple = container_fqn.split('.')[-1] if container_fqn else None
    if method_raw == '#ctor' or (cs_method_name and container_simple and cs_method_name == container_simple):
        py_method_name = '__init__'
        py_return = 'None'
    else:
        py_method_name = cs_method_name or method_raw
        # Return type mapping (best effort)
        py_return = map_dotnet_to_python(cs_return_type or 'None', container_fqn, container_simple)

    # Parameter annotations
    ann_types = []
    for t in param_types:
        ann_types.append(map_dotnet_to_python(t, container_fqn, container_simple))

    # Align parameter names count with types
    if len(param_names) != len(ann_types):
        # Fallback: generate arg1, arg2, ...
        param_names = [f'arg{i+1}' for i in range(len(ann_types))]

    params = []
    if py_method_name == '__init__' or (not is_static and cs_method_name):
        params.append('self')
    for name, ann in zip(param_names, ann_types):
        params.append(f'{name}: {ann}')

    qualified = f'{container_fqn}.{py_method_name}'
    return f'{qualified}({", ".join(params)}) -> {py_return}'

def process_file(path):
    html_text = read_text(path)
    help_id = extract_help_id(html_text)
    container_fqn, method_raw, param_types = parse_help_id(help_id or '')
    cs_text = extract_csharp_pre(html_text)
    cs_return_type, cs_method_name, param_names, is_static = parse_csharp_signature(cs_text or '', container_fqn.split('.')[-1] if container_fqn else None)

    if not container_fqn or not (method_raw or cs_method_name):
        return None  # not a method page
    try:
        line = build_signature_line(container_fqn, method_raw, param_types, cs_return_type, cs_method_name, param_names, is_static)
        return line
    except Exception as e:
        return None

def filter_namespace(input_file, output_file, namespace="Rhino.Geometry"):
    with open(input_file, "r", encoding="utf-8") as infile, \
         open(output_file, "w", encoding="utf-8") as outfile:
        
        for line in infile:
            if line.startswith(namespace):
                outfile.write(line)

def main():

    for input_dir, output_txt in zip(INPUT_DIRS, OUTPUT_PATHS):       
        if not input_dir:
            print("ERROR: Please provide an input directory.")
            sys.exit(2)

        input_dir = os.path.abspath(os.path.expanduser(input_dir))
        out_path = os.path.abspath(os.path.expanduser(output_txt))

        total = 0
        found = 0
        lines = []

        for root, dirs, files in os.walk(input_dir):
            for fn in files:
                if not (fn.startswith('M_') and fn.lower().endswith(('.htm', '.html'))):
                    continue
                total += 1
                fp = os.path.join(root, fn)
                line = process_file(fp)
                if line:
                    lines.append(line)
                    found += 1

        # Sort for stability
        lines.sort()
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            for ln in lines:
                f.write(ln + '\n')

        print(f"Processed {total} method files; extracted {found} signatures.")
        print(f"Output written to: {out_path}")
    
    # save only Rhino.Geometry methods to a separate file
    # Change these filenames as needed
    input_filename = OUTPUT_PATHS[1]  # assuming Rhinocommon output
    output_filename = "ref_api_rhinocommon_geometry.txt"
    filter_namespace(input_filename, output_filename, namespace="Rhino.Geometry")
    print(f"Filtered lines saved to {output_filename}")

if __name__ == "__main__":
    main()

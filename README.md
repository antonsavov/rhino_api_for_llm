# Rhino and Grasshopper API for LLMs

## Overview

This repo contains guidelines how to feed large language models (LLMs) with accurate context and call signatures so they can generate GhPython code with fewer hallucinations.

It includes a tool that converts the docs for **RhinoCommon**, **Grasshopper** and **Rhinoscriptsyntax** API into clean, Python-style method signatures in **.txt** format suitable to add to prompts to reduce method hallucinations.

## Usage

Pick one of the sample prompts (`Generic`, `Rhinocommon` or `Rhinoscriptsyntax`, `plain` or `SDK` mode) and modify it to your case. The `Generic` prompt let's the LLM decide which API to use. Keeping the API open like this leads to best results. Attach the suitable files to the prompt: 

For the Rhino Generic prompt:
- `ref_grasshopper_python_component.pdf`


For a RhinoCommon prompts:
- `ref_api_rhinocommon_geometry.txt`
- `ref_grasshopper_python_component.pdf`
- (optional) `ref_api_grasshopper.txt`
- (optional) `ref_api_rhinocommon_all.txt`


For Rhinoscriptsyntax prompts:
- `ref_api_rhinoscriptsyntax_all.txt`
- `ref_grasshopper_python_component.pdf`


## Setup

### 1. Clone McNeel's published API docs (offline HTML)

* RhinoCommon:

  ```bash
  git clone --depth=1 -b gh-pages https://github.com/mcneel/rhinocommon-api-docs
  ```
* Grasshopper:

  ```bash
  git clone --depth=1 -b gh-pages https://github.com/mcneel/grasshopper-api-docs
  ```

* Rhinoscript Syntax

  ```bash
  wget --mirror --convert-links --adjust-extension --page-requisites --no-parent \
  https://developer.rhino3d.com/api/RhinoScriptSyntax/
  ```

Run the commands above from the root of this project so the downloaded folders are at the root of the project.


### 2. Extract the API Signatures

Run the extraction scripts to generate Python-style method signatures for both APIs:

```bash
python extract_api_signatures.py
python extract_rhinoscriptsyntax_signatures.py
```

This will process the HTML files in both documentation folders and output two text files:
- `ref_api_grasshopper.txt`
- `ref_api_rhinocommon_all.txt`
- `ref_api_rhinocommon_geometry.txt`
- `ref_api_rhinoscriptsyntax_all.txt`

Each line in these files contains a fully-qualified method signature, e.g.:
```python
# example line in ref_api_rhinocommon_geometry.txt
Rhino.Geometry.Rectangle3d.__init__(self, plane: Rhino.Geometry.Plane, width: Rhino.Geometry.Interval, height: Rhino.Geometry.Interval) -> None

# example line in ref_api_rhinoscriptsyntax.txt
rhinoscriptsyntax.AddRectangle(plane: Rhino.Geometry.Plane, width: float, height: float) -> System.Guid
```

**How It Works**

- The script scans HTML files for method documentation.
- It extracts method names, parameter types, and return types using both metadata and C# code blocks.
- .NET types are mapped to Python types where possible.
- Output is sorted and written to the specified text files.


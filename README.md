# Rhino and Grasshopper API for LLMs

## Overview

This repo contains guidelines how to feed large language models (LLMs) with accurate context and call signatures so they can generate GhPython code with fewer hallucinations.

It includes a tool that converts the docs for **RhinoCommon** and **Grasshopper** API into clean, Python-style method signatures in **.txt** format.

## Usage

Modify the sample prompt (`sample_prompt_plain.md` or `sample_prompt_sdk_mode.md`) to your case. Attach the following files to the prompt: 

- `ref_api_methods_signatures_rhinocommon.txt`
- `ref_api_methods_signatures_grasshopper.txt`
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

Run the commands above from the root of this project so the downloaded folders are at the root of the project.


### 2. Extract the API Signatures

Run the extraction script to generate Python-style method signatures for both APIs:

```bash
python extract_api_signatures.py
```

This will process the HTML files in both documentation folders and output two text files:
- `ref_api_methods_signatures_grasshopper.txt`
- `ref_api_methods_signatures_rhinocommon.txt`

Each line in these files contains a fully-qualified method signature, e.g.:
```
Rhino.Geometry.Arc.__init__(self, center: Rhino.Geometry.Point3d, radius: float, angleRadians: float) -> None
```

**How It Works**

- The script scans HTML files for method documentation.
- It extracts method names, parameter types, and return types using both metadata and C# code blocks.
- .NET types are mapped to Python types where possible.
- Output is sorted and written to the specified text files.


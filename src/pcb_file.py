from __future__ import annotations

import json
import os
import re
import shutil
import tempfile

# Tokens relevant for S-expression scanning: whole quoted strings (so parens and
# "(model" inside them are ignored), the start of a (model ...) block, and parens.
_SEXPR_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\(model\s|[()]')
_TITLE_BLOCK_RE = re.compile(r"\(title_block\b(.*?)\n\s*\)", re.DOTALL)
_TB_FIELD_RE = re.compile(r'\((title|date|rev|company)\s+"((?:[^"\\]|\\.)*)"\)')
_TEXT_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def strip_3d_models(content: str) -> str:
    """Remove every (model ...) block from a .kicad_pcb file's text."""
    out: list[str] = []
    pos = 0
    skip_start = -1
    depth = 0
    for m in _SEXPR_TOKEN_RE.finditer(content):
        tok = m.group(0)
        if skip_start < 0:
            if tok.startswith("(model"):
                out.append(content[pos:m.start()])
                skip_start = m.start()
                depth = 1
        elif tok[0] == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
            if depth == 0:
                pos = m.end()
                skip_start = -1
    out.append(content[pos:] if skip_start < 0 else content[pos:skip_start])
    return "".join(out)


def make_bare_board_copy(project: str) -> tuple[str, str]:
    """Write a copy of the project's board without 3D models into a temp dir.

    The .kicad_pro/.kicad_prl are copied alongside under the same name so
    project-level settings (text variables) still apply.
    Returns (temp_dir, pcb_copy_path); the caller removes temp_dir when done.
    """
    base = os.path.splitext(project)[0]
    name = os.path.basename(base)
    with open(base + ".kicad_pcb", encoding="utf-8") as fh:
        content = fh.read()
    tmp_dir = tempfile.mkdtemp(prefix="kicad-export-bare-")
    try:
        pcb_copy = os.path.join(tmp_dir, name + ".kicad_pcb")
        with open(pcb_copy, "w", encoding="utf-8") as fh:
            fh.write(strip_3d_models(content))
        for ext in (".kicad_pro", ".kicad_prl"):
            if os.path.isfile(base + ext):
                shutil.copyfile(base + ext, os.path.join(tmp_dir, name + ext))
    except OSError:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    return tmp_dir, pcb_copy


def _project_text_vars(project: str) -> dict[str, str]:
    try:
        with open(project, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    tv = data.get("text_variables")
    return {str(k): str(v) for k, v in tv.items()} if isinstance(tv, dict) else {}


def read_title_block(project: str) -> dict[str, str]:
    """Return title/date/rev/company from the board (falling back to the root
    schematic), with ${VAR} text variables expanded from the .kicad_pro."""
    base = os.path.splitext(project)[0]
    fields: dict[str, str] = {}
    for ext in (".kicad_pcb", ".kicad_sch"):
        try:
            with open(base + ext, encoding="utf-8") as fh:
                m = _TITLE_BLOCK_RE.search(fh.read())
        except OSError:
            continue
        if not m:
            continue
        for key, value in _TB_FIELD_RE.findall(m.group(1)):
            fields.setdefault(key, value.replace('\\"', '"').replace("\\\\", "\\"))
        if "title" in fields:
            break

    text_vars = _project_text_vars(project)
    text_vars.setdefault("PROJECTNAME", os.path.basename(base))
    return {
        k: _TEXT_VAR_RE.sub(lambda vm: text_vars.get(vm.group(1), vm.group(0)), v)
        for k, v in fields.items()
    }

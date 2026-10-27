# Spec 4 — Remove dead code

[← index](README.md)

## Problem

`src/ui_helpers.py` contains one function:

```python
def bind_mousewheel(root, canvas):
    ...
```

It uses the tkinter API (`canvas.bind`, `root.bind_all`, `root.unbind_all`, `event.delta`, `event.num`) from a previous version of the app that used tkinter instead of wxPython. It is not imported anywhere in the current codebase.

## Change

Delete `src/ui_helpers.py`.

Confirm no references remain:

```powershell
Select-String -Path "src\*.py" -Pattern "ui_helpers" -Recurse
```

Expected: no output.

## Files affected

| File | Change |
|------|--------|
| `src/ui_helpers.py` | deleted |

## Note

If mousewheel scrolling on the advanced-settings `wx.ScrolledWindow` is wanted in the future, the wx equivalent is a single `EVT_MOUSEWHEEL` binding on the scroll window — no shared helper needed.

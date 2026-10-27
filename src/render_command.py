from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class RenderOptions:
    # Required
    board: str
    output: str
    width: int
    height: int
    side: str
    background: str
    quality: str

    # Optional — empty string means the flag is omitted
    floor: bool = False
    perspective: bool = False
    zoom: str = ""
    pan: str = ""
    pivot: str = ""
    rotate: str = ""
    light_top: str = ""
    light_bottom: str = ""
    light_side: str = ""
    light_camera: str = ""
    light_side_elevation: str = ""


def build_kicad_cli_args(options: RenderOptions) -> list[str]:
    """Return the kicad-cli argv list (no shell, no quoting needed)."""
    args = [
        "kicad-cli", "pcb", "render",
        "--output", options.output,
        "--width", str(options.width),
        "--height", str(options.height),
        "--side", options.side,
        "--background", options.background,
        "--quality", options.quality,
    ]
    if options.floor:
        args.append("--floor")
    if options.perspective:
        args.append("--perspective")
    for flag, value in [
        ("--zoom", options.zoom),
        ("--pan", options.pan),
        ("--pivot", options.pivot),
        ("--rotate", options.rotate),
        ("--light-top", options.light_top),
        ("--light-bottom", options.light_bottom),
        ("--light-side", options.light_side),
        ("--light-camera", options.light_camera),
        ("--light-side-elevation", options.light_side_elevation),
    ]:
        if value:
            # CLI11 re-inserts the value extracted from --flag=value back into the
            # argument stream; if it starts with '-' CLI11 treats it as an unknown
            # flag.  Wrapping in single quotes prevents that (the value then starts
            # with "'"), and kicad-cli's format parser strips the quotes before
            # interpreting the number.  Double quotes trigger "Invalid rotation
            # format", so single quotes are the correct delimiter here.
            quoted = f"'{value}'" if value.startswith("-") else value
            args.append(f"{flag}={quoted}")
    args.append(options.board)
    return args


def build_kicad_cli_command(options: RenderOptions) -> str:
    """Shell-quoted command string (fallback when shell=True is required)."""
    return subprocess.list2cmdline(build_kicad_cli_args(options))


def wrap_for_windows(kicad_cmd_path: str, cmd: str) -> str:
    """Prepend kicad-cmd.bat so kicad-cli is on PATH when cmd runs."""
    return f'cmd.exe /c ""{kicad_cmd_path}" && {cmd}"'

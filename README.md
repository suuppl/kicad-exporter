# KiCad Export

Export a KiCad project's renders, schematic PDF, layout PDF (Board2Pdf), STEP model,
fabrication files (Fabrication Toolkit) and a combined PDF — from a wxPython GUI, the
command line, or a Docker image for CI.

## GUI (Windows, local KiCad)

```bash
uv run main.py
```

Needs KiCad 9 plus the Board2Pdf and Fabrication Toolkit plugins (KiCad PCM). Set the
`kicad-cmd.bat` and board2pdf paths under *Project Paths*. *Project settings → Export…*
saves all options to `<name>_export_settings.json` next to the `.kicad_pro`; commit it so
the CLI and CI produce the same output.

## CLI

```bash
uv run main.py hw/board.kicad_pro                         # Bulk Export selection from the settings
uv run main.py hw/board.kicad_pro -t renders,schematic -o out/
uv run main.py hw/board.kicad_pro -t all --keep-going
```

Targets: `renders`, `schematic`, `layout`, `step`, `fab`, `combined`, `all`. Fabrication
files are written to `production/` next to the board (as the plugin does) and copied to
`<output>/production/` (`--no-fab-copy` skips the copy, e.g. when the output folder is
committed next to `production/`). The exit code is non-zero if any target fails.

## Docker / CI

The image bundles KiCad 9.0.7 (with its 3D-model library), Board2Pdf 1.9.3,
Fabrication Toolkit 5.3.0 (both pinned by SHA-256 to the KiCad PCM releases) and the CLI.

```bash
docker build -t kicad-exporter .
docker run --rm -v "$PWD:/work" kicad-exporter hw/board.kicad_pro -t all -o export
```

Mount the repository root, not just the project folder, so libraries referenced as
`${KIPRJMOD}/../…` resolve. In CI, add `-u "$(id -u):$(id -g)"` so outputs belong to the
runner user.

`.github/workflows/docker-image.yml` publishes the image to
[`ghcr.io/id-photonics-gmbh/kicad-exporter`](https://github.com/orgs/ID-Photonics-GmbH/packages/container/package/kicad-exporter)
on pushes to `main` and `v*` tags. `docker/example-workflow.yml` is a ready-to-copy
workflow for a project repository.

The image is private. To pull it locally, log in with a token that has `read:packages`:

```bash
echo "$TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
docker pull ghcr.io/id-photonics-gmbh/kicad-exporter:latest
```

For a project repository's workflow to pull it, grant that repository read access under
the package's *Package settings → Manage Actions access*.

To update KiCad or a plugin, change `KICAD_IMAGE` or the `ADD --checksum` lines in the
`Dockerfile` (URLs and hashes are in `https://gitlab.com/kicad/addons/repository/-/raw/main/packages-v1.json`).
After changing Python dependencies, regenerate the image's requirements:

```bash
uv export --no-default-groups --no-hashes --no-emit-project --python 3.11 -o docker/requirements.txt
```

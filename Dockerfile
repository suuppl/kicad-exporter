# syntax=docker/dockerfile:1.7
#
# Headless kicad-exporter: kicad-cli + Board2Pdf + Fabrication Toolkit + this app's CLI.
#
#   docker build -t kicad-exporter .
#   docker run --rm -v "$PWD:/work" kicad-exporter hw/board.kicad_pro -o export
#
# Plugin versions match the KiCad PCM packages (sha256 from repository.kicad.org).

# -full ships KiCad's symbol/footprint/3D-model libraries, needed for renders and STEP.
ARG KICAD_IMAGE=kicad/kicad:9.0.7-full
FROM ${KICAD_IMAGE}

USER root

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-venv \
 && rm -rf /var/lib/apt/lists/*

# Venv on top of KiCad's Python: --system-site-packages keeps pcbnew and wx importable,
# so one interpreter runs this app and both plugins.
COPY docker/requirements.txt /tmp/requirements.txt
RUN python3 -m venv --system-site-packages /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt pymupdf==1.27.2.3 \
 && rm /tmp/requirements.txt

# KiCad plugins, installed under the directory names the PCM uses.
ADD --checksum=sha256:a1a252cb2db000d1b8d13c27aae5c8237b2ed957e4dafbe61ddb497b454d0245 \
    https://links.dennevi.com/Board2Pdf_v1.9.3.zip /tmp/board2pdf.zip
ADD --checksum=sha256:70fe1ecc4858c5c44a3aedb6eafff80515e7837e48921c983c6fb2d8b19d9938 \
    https://github.com/bennymeg/Fabrication-Toolkit/releases/download/v5.3.0/Fabrication-Toolkit-5.3.0.zip /tmp/fab.zip
COPY docker/install_plugin.py /tmp/install_plugin.py
RUN python3 /tmp/install_plugin.py /tmp/board2pdf.zip /opt/kicad-plugins/com_gitlab_dennevi_Board2Pdf \
 && python3 /tmp/install_plugin.py /tmp/fab.zip /opt/kicad-plugins/com_github_bennymeg_JLC-Plugin-for-KiCad \
 && rm /tmp/*.zip /tmp/install_plugin.py

COPY main.py /opt/kicad-exporter/
COPY src/ /opt/kicad-exporter/src/
COPY docker/kicad-export /usr/local/bin/kicad-export
RUN chmod 755 /usr/local/bin/kicad-export

ENV KICAD_PYTHON=/opt/venv/bin/python \
    KICAD_EXPORT_BOARD2PDF=/opt/kicad-plugins/com_gitlab_dennevi_Board2Pdf/board2pdf-cli.py \
    KICAD_EXPORT_FAB_PLUGINS_DIR=/opt/kicad-plugins \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER kicad
WORKDIR /work
ENTRYPOINT ["kicad-export"]
CMD ["--help"]

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Headless export (CI / Docker): main.py <project.kicad_pro> [options]
        from src.cli import main
        sys.exit(main())
    from src.kicad_export_gui import KiCadExportApp
    KiCadExportApp().MainLoop()

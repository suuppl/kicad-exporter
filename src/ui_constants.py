BACKGROUNDS = ["default", "transparent", "opaque"]
QUALITIES = ["basic", "high", "user"]

RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "720p":  (1280, 720),
    "1080p": (1920, 1080),
    "2K":    (2560, 1440),
    "4K":    (3840, 2160),
}

# Ordered list of side keys used by kicad-cli (or our "corner" pseudo-side).
SIDE_KEYS = ["top", "bottom", "left", "right", "front", "back", "top-left-front"]

SIDE_LABELS: dict[str, str] = {
    "top":           "Top",
    "bottom":        "Bottom",
    "left":          "Left",
    "right":         "Right",
    "front":         "Front",
    "back":          "Back",
    "top-left-front": "Corner",
}

# Default advanced-settings values used exclusively for the corner render.
CORNER_ZOOM  = "1"
CORNER_PAN   = "1,1,0"
CORNER_PIVOT = "0,0,0"
CORNER_ROTATE = "-50,0,27"

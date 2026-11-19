"""Portable PNG images embedded in saved phrase HTML."""

import base64
import re
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

_PNG_PREFIX = "data:image/png;base64,"
_MAX_EDGE = 1600
_MAX_PNG_BYTES = 12 * 1024 * 1024
PREVIEW_SIZE_ATTR = "data-copasta-preview-size"
MIN_PREVIEW_EDGE = 32
MAX_PREVIEW_EDGE = 560

_PREVIEW_ATTRIBUTE = re.compile(
    rf'(<img) {PREVIEW_SIZE_ATTR}="[0-9]{{1,3}}"(?= src="{_PNG_PREFIX})'
)


def strip_preview_sizes(html):
    """Remove Copasta's display metadata before sending the HTML to another app."""
    return _PREVIEW_ATTRIBUTE.sub(r"\1", html)


@dataclass(frozen=True)
class PhraseImage:
    png: bytes
    preview_edge: int | None = None

    @classmethod
    def from_image(cls, image):
        image = ImageOps.exif_transpose(image).convert("RGBA")
        image.thumbnail((_MAX_EDGE, _MAX_EDGE), Image.LANCZOS)
        output = BytesIO()
        image.save(output, format="PNG")
        return cls(output.getvalue())

    @classmethod
    def from_html_src(cls, src, preview_size=None):
        if not src.startswith(_PNG_PREFIX):
            return None
        encoded = src[len(_PNG_PREFIX):]
        if len(encoded) > 4 * ((_MAX_PNG_BYTES + 2) // 3):
            return None
        try:
            png = base64.b64decode(encoded, validate=True)
            if len(png) > _MAX_PNG_BYTES:
                return None
            with Image.open(BytesIO(png), formats=["PNG"]) as image:
                if max(image.size) > _MAX_EDGE:
                    return None
                image.load()
        except (OSError, ValueError, Image.DecompressionBombError):
            return None
        if preview_size and preview_size.isascii() and preview_size.isdecimal() and len(preview_size) <= 3:
            edge = min(MAX_PREVIEW_EDGE, max(MIN_PREVIEW_EDGE, int(preview_size)))
            return cls(png, edge)
        return cls(png)

    def open(self):
        return Image.open(BytesIO(self.png), formats=["PNG"])

    def to_html(self):
        encoded = base64.b64encode(self.png).decode("ascii")
        size = f' {PREVIEW_SIZE_ATTR}="{self.preview_edge}"' if self.preview_edge is not None else ""
        return f'<img{size} src="{_PNG_PREFIX}{encoded}">'

    def to_dib(self):
        """Make a Windows clipboard bitmap with a white background for alpha."""
        output = BytesIO()
        with self.open() as image:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            background.save(output, format="BMP")
        return output.getvalue()[14:]  # CF_DIB omits the BMP file header.

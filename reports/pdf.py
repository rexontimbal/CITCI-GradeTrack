"""PDF rendering — xhtml2pdf, not WeasyPrint. WeasyPrint needs the GTK3/
Pango/Cairo native libraries, which aren't pip-installable and aren't
present on this Windows dev machine (confirmed: `import weasyprint` raises
OSError: cannot load library 'libgobject-2.0-0'); xhtml2pdf is pure-Python
over reportlab and works with no system install on Windows or Linux, at the
cost of weaker CSS support — fine for the fairly simple print layouts here.
"""

import base64
import io
import os

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.template.loader import render_to_string
from PIL import Image, ImageDraw, ImageFont
from xhtml2pdf import pisa


def link_callback(uri, rel):
    """Resolve an <img> src used in a PDF template to an absolute filesystem
    path, so rendering never depends on an HTTP round trip (previously
    `request.build_absolute_uri(...)` + a real fetch — breaks with no
    server running, e.g. from the shell or in tests). Static files are
    found via django.contrib.staticfiles.finders (works in DEBUG without a
    collectstatic run); anything else is resolved against STATIC_ROOT/
    MEDIA_ROOT. Resolving outside those roots is rejected — this is the
    only thing standing between a crafted uri and arbitrary file access."""
    if uri.startswith("data:"):
        return uri  # already-embedded image (e.g. the watermark) — no file lookup needed

    if uri.startswith(settings.STATIC_URL):
        relative_path = uri[len(settings.STATIC_URL):]
        found = finders.find(relative_path)
        path = found if found and not isinstance(found, (list, tuple)) else (found[0] if found else None)
        if path is None:
            path = os.path.join(settings.STATIC_ROOT, relative_path)
        # finders.find() may resolve into any of STATICFILES_DIRS (dev) or
        # STATIC_ROOT (post-collectstatic) — both are legitimate roots.
        allowed_roots = [os.path.abspath(d) for d in settings.STATICFILES_DIRS] + [os.path.abspath(settings.STATIC_ROOT)]
    elif uri.startswith(settings.MEDIA_URL):
        relative_path = uri[len(settings.MEDIA_URL):]
        path = os.path.join(settings.MEDIA_ROOT, relative_path)
        allowed_roots = [os.path.abspath(settings.MEDIA_ROOT)]
    else:
        raise ValueError(f"PDF image uri must be under {settings.STATIC_URL} or {settings.MEDIA_URL}: {uri!r}")

    path = os.path.abspath(path)
    if not any(os.path.commonpath([path, root]) == root for root in allowed_roots):
        raise ValueError(f"PDF image uri resolved outside its allowed root: {uri!r}")
    if not os.path.isfile(path):
        raise ValueError(f"PDF image file not found: {uri!r} -> {path}")
    return path


def watermark_data_uri(text):
    """A pale, diagonally-rotated PNG of `text` as a data: URI — xhtml2pdf
    (reportlab-based) doesn't implement CSS `transform`/`rotate` at all
    (confirmed: it silently drops the property and warns), so the rotation
    has to happen in the image itself, not in CSS. Pillow (already a
    dependency) draws the text, then rotates the whole image; xhtml2pdf
    renders a plain `position: absolute` `<img>` with a data: URI src fine."""
    try:
        font = ImageFont.truetype("arial.ttf", 70)
    except OSError:
        font = ImageFont.load_default()

    # Oversized transparent canvas so the diagonal text never clips.
    canvas = Image.new("RGBA", (1000, 260), (255, 255, 255, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 70), text, font=font, fill=(200, 30, 30, 90))
    rotated = canvas.rotate(30, expand=True)

    buffer = io.BytesIO()
    rotated.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_pdf(template_name, context, filename, inline=True):
    """Render a Django template to a PDF HttpResponse. The template is
    expected to extend templates/reports/pdf/_pdf_base.html for the shared
    print stylesheet (A4 portrait, header/footer frames)."""
    html = render_to_string(template_name, context)
    buffer = io.BytesIO()
    result = pisa.CreatePDF(src=html, dest=buffer, encoding="utf-8", link_callback=link_callback)
    if result.err:
        raise ValueError(f"Failed to render PDF ({template_name}): {result.err} error(s)")

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    disposition = "inline" if inline else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response

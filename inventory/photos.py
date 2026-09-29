"""Decode bounded uploads and store only re-encoded, metadata-free thumbnails."""
import base64
import binascii
import io
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from .validation import ApiError


def thumbnail(value):
    try:
        if not isinstance(value, str) or len(value) > 2_800_000:
            raise ValueError()
        raw = base64.b64decode(value, validate=True)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError()
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=("JPEG", "PNG", "WEBP")) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP') or source.width * source.height > 16_000_000:
                    raise ValueError()
                source.load()
                frame = ImageOps.exif_transpose(source).convert('RGBA')
                frame = ImageOps.fit(frame, (256, 256), method=Image.Resampling.LANCZOS)
                clean = Image.new('RGB', (256, 256), 'white')
                clean.paste(frame, mask=frame.getchannel('A'))
                output = io.BytesIO()
                clean.save(output, format='JPEG', quality=85)
                return output.getvalue()
    except (ValueError, OSError, SyntaxError, binascii.Error, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ApiError('INVALID_PHOTO', 'Escolha uma imagem JPG, PNG ou WebP de até 2 MB e 16 megapixels.', 422) from None

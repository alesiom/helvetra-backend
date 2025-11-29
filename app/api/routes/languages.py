"""
Languages endpoint.
Returns the list of supported translation languages.
"""

from fastapi import APIRouter

router = APIRouter()

SUPPORTED_LANGUAGES = [
    {"code": "de", "name": "German", "native_name": "Deutsch"},
    {"code": "gsw", "name": "Swiss German", "native_name": "Schwyzerdütsch"},
    {"code": "fr", "name": "French", "native_name": "Français"},
    {"code": "it", "name": "Italian", "native_name": "Italiano"},
    {"code": "en", "name": "English", "native_name": "English"},
]


@router.get("/languages")
async def get_languages() -> dict:
    """Return all supported languages for translation."""
    return {
        "success": True,
        "data": SUPPORTED_LANGUAGES,
    }

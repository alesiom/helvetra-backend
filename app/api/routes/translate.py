"""
Translation endpoint.
Handles text translation requests between supported languages.
"""

from fastapi import APIRouter, HTTPException

from app.schemas.translate import TranslateRequest, TranslateResponse
from app.services.translation import translate_text

router = APIRouter()


@router.post("/translate", response_model=TranslateResponse)
async def translate(request: TranslateRequest) -> TranslateResponse:
    """
    Translate text from source language to target language.
    Validates input, calls translation service, and returns result.
    """
    try:
        result = await translate_text(
            text=request.text,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
            formality=request.formality,
        )
        return TranslateResponse(
            success=True,
            data={
                "translation": result.translation,
                "source_lang": request.source_lang,
                "target_lang": request.target_lang,
            },
            meta={
                "characters": len(request.text),
                "processing_time_ms": result.processing_time_ms,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

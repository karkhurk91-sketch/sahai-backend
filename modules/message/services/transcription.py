import tempfile
import os
import httpx
from groq import Groq
from modules.common.config import GROQ_API_KEY
from modules.common.logger import get_logger

logger = get_logger(__name__)

async def transcribe_voice_note(audio_url: str, access_token: str) -> str:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(audio_url, headers={"Authorization": f"Bearer {access_token}"})
            if resp.status_code != 200:
                logger.error(f"Failed to download audio: {resp.status_code}")
                return ""
            audio_bytes = resp.content

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        groq_client = Groq(api_key=GROQ_API_KEY)
        with open(tmp_path, "rb") as f:
            transcription = groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                response_format="text"
            )
        os.unlink(tmp_path)
        return transcription if isinstance(transcription, str) else transcription.text
    except Exception as e:
        logger.error(f"Voice transcription failed: {e}")
        return ""

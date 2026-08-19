"""Google Cloud Speech-to-Text v2 (Chirp 2) implementation of STTProvider.

Auth uses Application Default Credentials — locally that's gcloud's
ADC; on Cloud Run that's the runtime service account
(`dess-run-sa@`), which was granted `roles/speech.client` in
Slice 0.

Uses the inline `recognizers/_` config rather than a pre-created
Recognizer resource. Inline is simpler and verified working in the
2026-05-21 smoke tests; if we ever need adapted recognizers (custom
vocabularies, multi-recognizer fan-out), that's a separate slice.

Audio decoding is auto-detected by `AutoDetectDecodingConfig`. Slice 1
verified this works for LINEAR16 WAV; the M4A test failed (Google
silently returned no results), so we constrain the accepted
content-types to WAV/MP3/WebM/FLAC at the route layer. M4A clients
must transcode before upload — covered in the Slice 2 recorder.
"""

from __future__ import annotations

from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech

from app.services.voice.stt_base import (
    RawTranscript,
    STTAudioTooLargeError,
    STTProviderError,
    STTUnsupportedAudioError,
)

# Content types Chirp 2 reliably decodes via AutoDetectDecodingConfig.
# Verified 2026-05-21 against WAV; the others are per Google's docs.
_ACCEPTED_CONTENT_TYPES = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/webm",
        "audio/ogg",
        "audio/flac",
    }
)

# Speech-to-Text v2 inline sync recognition limits.
_MAX_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_PROVIDER_NAME = "google_chirp"


class STTChirpProvider:
    """Sync Chirp 2 recognition via Cloud Speech-to-Text v2."""

    def __init__(
        self,
        *,
        project: str,
        region: str,
        model: str = "chirp_2",
        client: speech_v2.SpeechClient | None = None,
    ) -> None:
        self._project = project
        self._region = region
        self._model = model
        self._client = client or speech_v2.SpeechClient(
            client_options={"api_endpoint": f"{region}-speech.googleapis.com"}
        )

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str,
        max_duration_sec: int,
    ) -> RawTranscript:
        if content_type not in _ACCEPTED_CONTENT_TYPES:
            raise STTUnsupportedAudioError(
                f"content-type {content_type!r} not supported. "
                f"Accepted: {sorted(_ACCEPTED_CONTENT_TYPES)}"
            )
        if len(audio_bytes) > _MAX_PAYLOAD_BYTES:
            raise STTAudioTooLargeError(
                f"audio is {len(audio_bytes):,} bytes, "
                f"max is {_MAX_PAYLOAD_BYTES:,} for sync recognition"
            )

        request = cloud_speech.RecognizeRequest(
            recognizer=(
                f"projects/{self._project}/locations/{self._region}" f"/recognizers/_"
            ),
            config=cloud_speech.RecognitionConfig(
                auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                language_codes=["en-US"],
                model=self._model,
            ),
            content=audio_bytes,
        )

        try:
            response = self._client.recognize(request=request)
        except Exception as exc:  # noqa: BLE001 — provider errors are opaque
            raise STTProviderError(f"Chirp call failed: {exc}") from exc

        text = " ".join(
            alt.transcript
            for result in response.results
            for alt in result.alternatives[:1]
        ).strip()

        # v2 returns `result_end_offset` on each result — a Duration
        # proto representing how far into the audio that result lands.
        # The last result's offset is effectively the audio length.
        # Empty response (no speech detected) gets 0.0 — billing-wise
        # that still represents a call but the cost will round to 0.
        if response.results:
            last_offset = response.results[-1].result_end_offset
            duration_sec = last_offset.seconds + last_offset.microseconds / 1_000_000
        else:
            duration_sec = 0.0

        return RawTranscript(
            text=text,
            duration_sec=float(duration_sec),
            provider=_PROVIDER_NAME,
            model_id=self._model,
        )

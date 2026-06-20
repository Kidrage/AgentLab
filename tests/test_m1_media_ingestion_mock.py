"""M1-6: Media ingestion mock — deterministic unit tests."""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent_runtime.ingestion.ingestion_contract import IngestionContract
from agent_runtime.ingestion.media_ingestion import ingest_media, assess_media_quality


def test_ingest_media_supervision_mock_image():
    contract = IngestionContract(
        artifact_id="media_img",
        source_path="/tmp/test.png",
        source_type="media",
        provider="supervision_mock",
    )
    result = ingest_media(contract, media_bytes=b"\x89PNG\r\n\x1a\nfake png data here")
    assert result.status == "ingested"
    assert result.provider == "supervision_mock"
    assert len(result.output_assets) == 2
    assert result.content_hash
    assert result.metadata["mime_type"] == "image/png"
    assert result.metadata["media_type"] == "image"


def test_ingest_media_video():
    contract = IngestionContract(
        artifact_id="media_vid",
        source_path="/tmp/clip.mp4",
        source_type="media",
        provider="supervision_mock",
    )
    result = ingest_media(contract, media_bytes=b"fake mp4 bytes here")
    assert result.status == "ingested"
    assert result.metadata["media_type"] == "video"
    assert result.metadata["mime_type"] == "video/mp4"


def test_ingest_media_audio():
    contract = IngestionContract(
        artifact_id="media_aud",
        source_path="/tmp/sound.mp3",
        source_type="media",
        provider="supervision_mock",
    )
    result = ingest_media(contract, media_bytes=b"fake mp3 data")
    assert result.metadata["media_type"] == "audio"
    assert result.metadata["mime_type"] == "audio/mpeg"


def test_ingest_media_missing_file():
    contract = IngestionContract(
        artifact_id="media_missing",
        source_path="/tmp/definitely_missing_m1_6.mp4",
        source_type="media",
        provider="supervision_mock",
    )
    result = ingest_media(contract)
    assert result.status == "failed"
    assert result.requires_human_review is True


def test_ingest_media_unsupported_provider():
    contract = IngestionContract(
        artifact_id="media_bad",
        source_path="/tmp/x.png",
        source_type="media",
        provider="codebase_memory_mock",  # not a media provider
    )
    result = ingest_media(contract, media_bytes=b"data")
    assert result.status == "failed"
    assert any("not supported" in w for w in result.warnings)


def test_ingest_media_empty_file():
    contract = IngestionContract(
        artifact_id="media_empty",
        source_path="/tmp/empty.png",
        source_type="media",
        provider="supervision_mock",
    )
    result = ingest_media(contract, media_bytes=b"")
    assert result.requires_human_review is True
    assert any("empty" in w.lower() for w in result.warnings)


def test_ingest_media_large_file_warns():
    contract = IngestionContract(
        artifact_id="media_large",
        source_path="/tmp/large.mp4",
        source_type="media",
        provider="supervision_mock",
    )
    result = ingest_media(contract, media_bytes=b"x" * 150_000_000)
    assert any("100MB" in w for w in result.warnings)


def test_assess_media_quality_pass():
    from agent_runtime.ingestion.ingestion_contract import IngestionResult

    result = IngestionResult(
        artifact_id="media_q",
        source_path="/tmp/x.png",
        source_type="media",
        provider="supervision_mock",
        status="ingested",
        output_assets=["media_q_vision.yml"],
        content_hash="ghi789",
        metadata={"size_bytes": 1024},
    )
    q = assess_media_quality(result)
    assert q.confidence == 1.0
    assert q.checks_passed == 3


def test_assess_media_quality_empty():
    from agent_runtime.ingestion.ingestion_contract import IngestionResult

    result = IngestionResult(
        artifact_id="media_empty",
        source_path="/tmp/x.png",
        source_type="media",
        provider="supervision_mock",
        status="ingested",
        output_assets=[],
        content_hash="",
        metadata={"size_bytes": 0},
    )
    q = assess_media_quality(result)
    assert q.confidence < 1.0
    assert q.checks_failed == 3


def test_ingest_media_from_real_tempfile():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\nfake png content for testing")
        tmp_path = f.name

    try:
        contract = IngestionContract(
            artifact_id="media_real",
            source_path=tmp_path,
            source_type="media",
            provider="supervision_mock",
        )
        result = ingest_media(contract)
        assert result.status == "ingested"
        assert result.content_hash
    finally:
        Path(tmp_path).unlink(missing_ok=True)

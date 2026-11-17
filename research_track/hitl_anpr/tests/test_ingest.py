import pytest
from PIL import Image

from anpr_hitl.ingest import encode_jpeg_without_metadata, ingest_video, sample_indices
from anpr_hitl.manifest import manifest_hash, read_manifest
from anpr_hitl.splits import VideoRegistry
from conftest import make_video


@pytest.mark.parametrize("count, native, fps, expected", [
    (100, 25.0, 2.0, [0, 12, 25, 38, 50, 62, 75, 88]),
    (300, 30.0, 2.0, list(range(0, 300, 15))),
    (10, 30.0, 2.0, [0]),
    (0, 30.0, 2.0, []),
    (50, 24000 / 1001, 2.0, [0, 12, 24, 36, 48]),
])
def test_sampling_is_deterministic_by_timestamp(count, native, fps, expected):
    assert sample_indices(count, native, fps) == expected
    assert sample_indices(count, native, fps) == sample_indices(count, native, fps)


def test_ingest_samples_drops_blur_and_duplicates_and_is_reproducible(tmp_path, cfg, store):
    video = make_video(tmp_path / "gate cam 1.mp4", fps=25, seconds=4, static_from=60, blur_frames={25})
    result = ingest_video(video, store, cfg, group="gate1")
    # 2 fps x 4 s = 8 samples at frames 0,12,25,38,50,62,75,88: 25 is blurred, 62/75/88 repeat frame 59
    assert result.sampled == 8
    assert result.dropped_blur == 1
    assert result.dropped_duplicate >= 2
    assert [r["frame_idx"] for r in result.rows] == [0, 12, 38, 50, 62][: result.kept]
    first_hash = manifest_hash(read_manifest(store.frames_manifest))

    again = ingest_video(video, store, cfg, group="gate1")
    assert again.skipped_existing and again.kept == result.kept
    forced = ingest_video(video, store, cfg, group="gate1", force=True)
    assert manifest_hash(read_manifest(store.frames_manifest)) == first_hash
    assert forced.kept == result.kept


def test_split_is_assigned_before_frames_and_recorded_on_every_row(tmp_path, cfg, store):
    video = make_video(tmp_path / "v.mp4", seconds=2)
    result = ingest_video(video, store, cfg, group="site-a", split="gold")
    registry = VideoRegistry(store.videos_registry, cfg.seed, 0.2, 0.1)
    assert registry.split_of(result.video_id) == "gold"
    assert {r["split"] for r in result.rows} == {"gold"}
    assert all((store.root / r["path"]).is_file() for r in result.rows)


def test_written_frames_carry_no_exif_or_gps(tmp_path):
    import cv2
    import numpy as np

    # Positive control: a phone-style JPEG with GPS and camera EXIF.
    source = tmp_path / "phone.jpg"
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"                                   # Make
    exif[0x8825] = {1: "N", 2: (30.0, 45.0, 51.0), 3: "E", 4: (76.0, 46.0, 7.0)}  # GPSInfo (Chandigarh)
    Image.fromarray((np.random.default_rng(1).random((120, 160, 3)) * 255).astype("uint8")).save(source, exif=exif)
    with Image.open(source) as img:
        assert img.getexif().get_ifd(0x8825), "control image must carry GPS"

    out = tmp_path / "frame.jpg"
    out.write_bytes(encode_jpeg_without_metadata(cv2.imread(str(source)), 95))
    with Image.open(out) as img:
        assert not img.getexif() and "exif" not in img.info and not img.getexif().get_ifd(0x8825)

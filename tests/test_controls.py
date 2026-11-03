import pytest

from auto_factory.control.computer import normalized_to_pixel
from auto_factory.control.drag import visible_offsets


@pytest.mark.parametrize(
    ("coordinate", "size", "expected"),
    [(0, 1920, 0), (500, 1920, 960), (1000, 1920, 1919)],
)
def test_normalized_to_pixel(coordinate: int, size: int, expected: int) -> None:
    assert normalized_to_pixel(coordinate, size) == expected


def test_normalized_to_pixel_rejects_invalid_coordinate() -> None:
    with pytest.raises(ValueError):
        normalized_to_pixel(1001, 1920)


def test_visible_offsets_shrink_with_zoom() -> None:
    camera = {
        "centre": {"dx": 0.5, "dy": 0},
        "zoom": 2,
        "resolution": {"width": 3200, "height": 1920},
    }

    assert visible_offsets(camera) == {"dx": (-24.5, 25.5), "dy": (-15, 15)}

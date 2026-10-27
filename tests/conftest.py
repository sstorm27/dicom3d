import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from make_phantom import make_volume, write_series  # noqa: E402

SPACING = (1.0, 1.0, 2.0)


@pytest.fixture(scope="session")
def phantom_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("phantom")
    write_series(make_volume(spacing=SPACING), out, spacing=SPACING)
    return out

"""app/access/, app/garmin_api/ and app/garmin_login/ are copies of the MyCommons
building blocks `access`, `garmin_api` and `garmin_login`. Locally
(MyCommons cloned next to this repo) the copy must match it; in CI, where the
private MyCommons repo is not available, the check is skipped."""
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SYNC = REPO.parent / "MyCommons" / "sync.sh"


@pytest.mark.skipif(not SYNC.is_file(), reason="MyCommons is not cloned next to this repo")
@pytest.mark.parametrize("block", ["access", "garmin_api", "garmin_login", "dem"])
def test_the_copy_matches_mycommons(block):
    r = subprocess.run([str(SYNC), "--check", block, str(REPO / "app")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

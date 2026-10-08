from pathlib import Path
"""Release-integrity regression tests (v0.89 audit fixes).

v0.89.0 reused one build artifact but (a) ran every test from the checkout,
where ``pythonpath = ["."]`` lets source modules shadow the installed wheel,
(b) installed only ``ls dist/*.whl | head -n 1``, and (c) published
``dist/*`` — including an sdist that was never tested — with no digest check.
"""
import os
import subprocess
import sys
import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
WORKFLOWS = os.path.join(REPO_ROOT, ".github", "workflows")
VERIFY_DIST = os.path.join(REPO_ROOT, ".github", "scripts", "verify_dist.py")
SMOKE = os.path.join(REPO_ROOT, ".github", "scripts", "wheel_smoke.py")


def _load(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _runs(job):
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def _verify(*args):
    return subprocess.run([sys.executable, VERIFY_DIST, *args],
                          capture_output=True, text=True, timeout=60)


def _dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "soma_governance-0.0.0-py3-none-any.whl").write_bytes(b"wheel bytes")
    (d / "soma_governance-0.0.0.tar.gz").write_bytes(b"sdist bytes")
    return d


def test_publish_never_rebuilds_and_verifies_digests():
    publish = _load("publish.yml")["jobs"]["publish"]
    runs = _runs(publish)
    assert "python -m build" not in runs, "publish must not rebuild the artifact"
    assert "verify_dist.py verify dist" in runs
    assert "twine upload dist/*" not in runs, "publish must upload only verified files"
    assert "needs" in publish and "validate" in str(publish["needs"])


def test_digest_verification_failure_cannot_be_masked_by_a_pipe():
    """`verify ... | tee` exits 0 when verify fails (no pipefail by default)."""
    for workflow, job in (("publish.yml", "publish"), ("validate.yml", "validate"),
                          ("validate.yml", "build-wheel")):
        for step in _load(workflow)["jobs"][job]["steps"]:
            run = step.get("run", "")
            if "verify_dist.py" not in run:
                continue
            for line in run.splitlines():
                if "verify_dist.py" in line:
                    assert "|" not in line, f"{workflow}:{job} pipes verify_dist output: {line}"


def test_build_records_digests_and_smoke_tests_sdist():
    build = _load("validate.yml")["jobs"]["build-wheel"]
    runs = _runs(build)
    assert "verify_dist.py record dist" in runs
    assert "wheel_smoke.py" in runs and "-I" in runs, "sdist must be smoke-tested"


def test_validate_matrix_smoke_tests_wheel_source_hidden():
    validate = _load("validate.yml")["jobs"]["validate"]
    runs = _runs(validate)
    assert "verify_dist.py verify dist" in runs
    assert "head -n 1" not in runs, "must install the single verified wheel, not the first match"
    smoke = [s.get("run", "") for s in validate["steps"] if "wheel_smoke.py" in s.get("run", "")]
    assert smoke, "matrix must smoke-test the installed wheel"
    assert "env -u PYTHONPATH" in smoke[0] and "python -I" in smoke[0]
    assert 'cd "$RUNNER_TEMP"' in smoke[0], "smoke must run outside the checkout"


def test_verify_dist_accepts_recorded_artifacts(tmp_path):
    d = _dist(tmp_path)
    assert _verify("record", str(d)).returncode == 0
    proc = _verify("verify", str(d))
    assert proc.returncode == 0, proc.stderr
    assert len(proc.stdout.split()) == 2


def test_verify_dist_rejects_tampered_artifact(tmp_path):
    d = _dist(tmp_path)
    assert _verify("record", str(d)).returncode == 0
    with open(d / "soma_governance-0.0.0-py3-none-any.whl", "ab") as f:
        f.write(b"tampered")
    proc = _verify("verify", str(d))
    assert proc.returncode == 1 and "sha256" in proc.stderr


def test_verify_dist_rejects_unlisted_artifact(tmp_path):
    d = _dist(tmp_path)
    assert _verify("record", str(d)).returncode == 0
    (d / "soma_governance-0.0.1-py3-none-any.whl").write_bytes(b"other")
    assert _verify("verify", str(d)).returncode == 1


def test_wheel_smoke_refuses_when_source_can_shadow_site_packages():
    env = dict(os.environ, PYTHONPATH=REPO_ROOT)
    proc = subprocess.run([sys.executable, "-I", SMOKE], capture_output=True,
                          text=True, timeout=60, env=env)
    assert proc.returncode == 1 and "PYTHONPATH" in proc.stderr
    env.pop("PYTHONPATH")
    proc = subprocess.run([sys.executable, SMOKE], capture_output=True,
                          text=True, timeout=60, env=env, cwd=REPO_ROOT)
    assert proc.returncode == 1 and "-I" in proc.stderr

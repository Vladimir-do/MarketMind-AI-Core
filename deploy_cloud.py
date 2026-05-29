import os
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
FUNCTION_NAME = "wb-parser-function"
SOURCE_FILE = ROOT / "cloud_wb_function.py"
ENV_FILE = ROOT / ".env"
RUNTIME = os.getenv("YC_FUNCTION_RUNTIME", "python312")
ENTRYPOINT = "cloud_wb_function.handler"


def main() -> int:
    if not SOURCE_FILE.exists():
        print(f"Missing function source: {SOURCE_FILE}")
        return 1

    if not shutil.which("yc"):
        print("Yandex Cloud CLI not found. Install it and run `yc init` once.")
        return 1

    try:
        ensure_function()
        archive_path = build_archive()
        create_version(archive_path)
        allow_public_invoke()
        function_id = get_function_id()
        function_url = f"https://functions.yandexcloud.net/{function_id}"
        upsert_env("WB_CLOUD_FUNCTION_URL", function_url)
    except subprocess.CalledProcessError as e:
        print(e.stdout or "")
        print(e.stderr or "")
        print(f"yc command failed with exit code {e.returncode}")
        return e.returncode
    except Exception as e:
        print(f"Deploy failed: {e}")
        return 1

    print(f"WB cloud function deployed: {function_url}")
    print(f"Saved WB_CLOUD_FUNCTION_URL to {ENV_FILE}")
    return 0


def ensure_function() -> None:
    result = run_yc(
        "serverless", "function", "get",
        "--name", FUNCTION_NAME,
        check=False,
    )
    if result.returncode == 0:
        print(f"Function already exists: {FUNCTION_NAME}")
        return

    print(f"Creating function: {FUNCTION_NAME}")
    run_yc("serverless", "function", "create", "--name", FUNCTION_NAME)


def build_archive() -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="wb-function-"))
    archive_path = tmp_dir / "wb-function.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as zf:
        zf.write(SOURCE_FILE, SOURCE_FILE.name)
    return archive_path


def create_version(archive_path: Path) -> None:
    print("Uploading function version")
    run_yc(
        "serverless", "function", "version", "create",
        "--function-name", FUNCTION_NAME,
        "--runtime", RUNTIME,
        "--entrypoint", ENTRYPOINT,
        "--memory", "128m",
        "--execution-timeout", "30s",
        "--source-path", str(archive_path),
    )


def allow_public_invoke() -> None:
    print("Making function public")
    run_yc(
        "serverless", "function", "allow-unauthenticated-invoke",
        FUNCTION_NAME,
    )


def get_function_id() -> str:
    result = run_yc(
        "serverless", "function", "get",
        "--name", FUNCTION_NAME,
        "--format", "json",
    )
    payload = json.loads(result.stdout)
    function_id = payload.get("id")
    if not function_id:
        raise RuntimeError("Cannot read function id from yc output")
    return function_id


def upsert_env(key: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    prefix = f"{key}="
    new_line = f"{key}={value}"

    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            lines[idx] = new_line
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Wildberries cloud parser")
        lines.append(new_line)

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_yc(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["yc", *args]
    print("+ " + " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())

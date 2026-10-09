import json
import os
import sys
import time
import tarfile
import zipfile
import urllib.request
import urllib.error
import shutil


def fail(message):
    sys.stderr.write(str(message) + "\n")
    sys.exit(1)


def read_request():
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        fail("invalid JSON input: " + str(exc))


def require_string(name, value, default=None):
    if value is None:
        return default
    if not isinstance(value, str) or value == "":
        fail(name + " must be a non-empty string")
    return value


def normalise_archive_type(archive_type, url_or_path):
    if archive_type not in ("auto", "zip", "tar", "tar.gz", "tar.gz"):
        fail("archive_type must be one of auto, zip, tar, tar.gz")
    if archive_type != "auto":
        return archive_type
    lowered = (url_or_path or "").lower()
    if lowered.endswith(".zip"):
        return "zip"
    if lowered.endswith(".tar.gz") or lowered.endswith(".tgz"):
        return "tar.gz"
    if lowered.endswith(".tar"):
        return "tar"
    # Try to infer from magic bytes later in the caller. Return auto marker.
    return None


def detect_archive_from_bytes(path):
    # tar/tar.gz can be detected by looking at the beginning. zip starts with PK.
    with open(path, "rb") as stream:
        head = stream.read(4)
    if head[:2] == b"PK":
        return "zip"
    if head[:2] == b"\x1f\x8b":
        return "tar.gz"
    # A plain tar archive usually has the ustar magic bytes at offset 257.
    with open(path, "rb") as stream:
        stream.seek(257)
        magic = stream.read(8)
    if magic[:6] == b"ustar\x00" or magic[:6] == b"ustar ":
        return "tar"
    fail("could not auto-detect archive type; pass archive_type explicitly")


def is_file_path(path):
    return "://" not in path and os.path.exists(path)


def safe_extract_zip(archive, dest, max_total_bytes=200 * 1024 * 1024):
    dest_real = os.path.realpath(dest)
    extracted_bytes = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            member = info.filename
            if member.endswith("/"):
                continue
            target = os.path.realpath(os.path.join(dest_real, member))
            try:
                common = os.path.commonpath([dest_real, target])
            except ValueError as exc:
                fail("zip member resolves outside cache directory: " + member + " " + str(exc))
            if common != dest_real or not target.startswith(dest_real + os.sep):
                fail("zip member resolves outside cache directory: " + member)
            if info.file_size > max_total_bytes - extracted_bytes:
                fail("zip member would exceed extraction byte budget")
            extracted_bytes += info.file_size
            extracted_path = zf.extract(info, dest_real)
            try:
                os.chmod(extracted_path, 0o755)
            except OSError:
                pass
    return extracted_bytes


def safe_extract_tar(archive, dest, max_total_bytes=200 * 1024 * 1024):
    dest_real = os.path.realpath(dest)
    with tarfile.open(archive) as tf:
        extracted_bytes = 0
        for member in tf.getmembers():
            if member.isdir():
                continue
            target = os.path.realpath(os.path.join(dest_real, member.name))
            try:
                common = os.path.commonpath([dest_real, target])
            except ValueError as exc:
                fail("tar member resolves outside cache directory: " + member.name + " " + str(exc))
            if common != dest_real or not target.startswith(dest_real + os.sep):
                fail("tar member resolves outside cache directory: " + member.name)
            if member.size > max_total_bytes - extracted_bytes:
                fail("tar member would exceed extraction byte budget")
            extracted_bytes += member.size
            tf.extract(member, dest_real)
            try:
                os.chmod(target, 0o755)
            except OSError:
                pass
    return extracted_bytes


def download_archive(url, dest, timeout_seconds):
    timeout = timeout_seconds if isinstance(timeout_seconds, int) and timeout_seconds > 0 else None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            with open(dest, "wb") as out:
                shutil.copyfileobj(response, out)
    except urllib.error.HTTPError as exc:
        fail("download HTTP error " + str(exc.code) + " for " + url + ": " + str(exc))
    except urllib.error.URLError as exc:
        fail("download URL error for " + url + ": " + str(exc.reason))
    except OSError as exc:
        fail("download error for " + url + ": " + str(exc))
    return os.path.getsize(dest)


def make_url(template, browser_name, browser_version, executable_name, platform):
    try:
        return template.format(
            browser_name=browser_name,
            version=browser_version,
            platform=platform,
            executable_name=executable_name,
        )
    except KeyError as exc:
        fail("source_url_template has an unsupported placeholder: " + str(exc))
    except Exception as exc:
        fail("failed to render source_url_template: " + str(exc))


def find_existing_executable(cache_path, executable_name):
    if not os.path.isdir(cache_path):
        return None
    for dirpath, dirnames, filenames in os.walk(cache_path):
        if executable_name in filenames:
            candidate = os.path.join(dirpath, executable_name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
            if os.path.isfile(candidate):
                try:
                    os.chmod(candidate, 0o755)
                    return candidate
                except OSError:
                    return candidate
    return None


def locate_executable_after_extract(target_cache, extract_subdir, executable_name):
    if extract_subdir:
        candidate = os.path.join(target_cache, extract_subdir, executable_name)
        if os.path.isfile(candidate):
            try:
                os.chmod(candidate, 0o755)
            except OSError:
                pass
            return candidate
    existing = find_existing_executable(target_cache, executable_name)
    if existing:
        return existing
    fail("extracted archive did not contain executable_name: " + executable_name)


def main():
    args = read_request()
    browser_name = require_string("browser_name", args.get("browser_name"))
    browser_version = require_string("browser_version", args.get("browser_version"))
    executable_name = require_string("executable_name", args.get("executable_name"))
    cache_dir = require_string("cache_dir", args.get("cache_dir"))
    platform = require_string("platform", args.get("platform"), "linux64")
    source_url_template = args.get("source_url_template")
    source_path = args.get("source_path")
    archive_type = args.get("archive_type", "auto")
    extract_subdir = require_string("extract_subdir", args.get("extract_subdir"), "")
    force_download = bool(args.get("force_download", False))
    clean_cache = bool(args.get("clean_cache", False))
    timeout_seconds = args.get("timeout_seconds")

    resolved_cache_dir = os.path.abspath(cache_dir)
    cache_entry = browser_name + "/" + browser_version
    target_cache = os.path.join(resolved_cache_dir, cache_entry)

    cleaned = False
    if clean_cache:
        cleaned = os.path.isdir(target_cache)
        if cleaned:
            shutil.rmtree(target_cache)

    if os.path.isdir(resolved_cache_dir):
        existing = find_existing_executable(resolved_cache_dir, executable_name)
        if existing and not force_download:
            print(json.dumps({
                "status": "cached",
                "cache_path": os.path.abspath(os.path.dirname(existing)),
                "browser_path": os.path.abspath(existing),
                "source_url": None,
                "source_kind": "existing",
                "cleaned": cleaned,
                "cache_entry": cache_entry,
                "downloaded_bytes": None,
            }))
            return

    # Prefer an explicit source_url_template only when it produces an http(s) URL. Otherwise use source_path. If neither is present, fail with a clear message.
    rendered_url = None
    if isinstance(source_url_template, str):
        rendered_url = make_url(source_url_template, browser_name, browser_version, executable_name, platform)
        if not rendered_url.lower().startswith(("http://", "https://", "file://")):
            fail("source_url_template must render an http, https, or file URL")

    source_kind = "network"
    archive_path = None
    local_source = None
    if source_path:
        local_source = source_path
        if not is_file_path(local_source):
            fail("source_path does not exist or looks like a remote URL: " + local_source)
        source_kind = "local"
    elif rendered_url and rendered_url.lower().startswith("file://"):
        local_source = urllib.request.url2pathname(rendered_url[len("file://"):])
        if not is_file_path(local_source):
            fail("file URL source does not exist: " + local_source)
        source_kind = "local"
    elif rendered_url:
        local_source = None
    else:
        fail("either source_path or a http/https source_url_template is required when installation is needed")

    os.makedirs(resolved_cache_dir, exist_ok=True)
    os.makedirs(target_cache, exist_ok=True)

    download_bytes = None
    temp_archive = None
    if source_kind == "network":
        temp_archive = os.path.join(target_cache, ".download." + str(int(time.time() * 1000)) + ".tmp")
        download_bytes = download_archive(rendered_url, temp_archive, timeout_seconds)
        archive_path = temp_archive
    elif source_kind == "local":
        archive_path = local_source
    else:
        fail("unexpected source_kind")

    detected_type = archive_type
    if detected_type == "auto" or detected_type is None:
        # Try filename first; if unknown, inspect magic bytes.
        detected_type = normalise_archive_type("auto", archive_path)
        if detected_type is None:
            detected_type = detect_archive_from_bytes(archive_path)
    if detected_type not in ("zip", "tar", "tar.gz"):
        fail("unsupported archive type: " + str(detected_type))

    extracted_bytes = 0
    try:
        if detected_type == "zip":
            extracted_bytes = safe_extract_zip(archive_path, target_cache)
        else:
            if detected_type == "tar.gz" or detected_type == "tar":
                extracted_bytes = safe_extract_tar(archive_path, target_cache)
            else:
                fail("unsupported archive type: " + str(detected_type))
    except zipfile.BadZipFile as exc:
        fail("bad zip archive: " + str(exc))
    except tarfile.ReadError as exc:
        fail("bad tar archive: " + str(exc))
    except OSError as exc:
        fail("extraction error: " + str(exc))
    finally:
        if temp_archive:
            try:
                os.unlink(temp_archive)
            except OSError:
                pass

    browser_path = locate_executable_after_extract(target_cache, extract_subdir, executable_name)
    print(json.dumps({
        "status": "recovered" if cleaned else "installed",
        "cache_path": os.path.abspath(target_cache),
        "browser_path": os.path.abspath(browser_path),
        "source_url": rendered_url,
        "source_kind": source_kind,
        "cleaned": cleaned,
        "cache_entry": cache_entry,
        "downloaded_bytes": download_bytes if source_kind == "network" else None,
        "archive_type": detected_type,
        "extracted_bytes": extracted_bytes,
    }))


if __name__ == "__main__":
    main()

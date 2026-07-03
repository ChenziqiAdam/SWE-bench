"""Issue media extraction and local caching for multimodal scientific issues."""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMAGE_RE = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s)>'\"]+")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}
_IMAGE_HOST_MARKERS = (
    "user-images.githubusercontent.com",
    "private-user-images.githubusercontent.com",
    "github.com/user-attachments/assets/",
)
_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def extract_image_urls(text: str) -> list[str]:
    """Extract likely issue image URLs from GitHub-flavored Markdown/HTML."""
    if not text:
        return []

    candidates: list[str] = []
    candidates.extend(m.group(1) for m in _MARKDOWN_IMAGE_RE.finditer(text))
    candidates.extend(m.group(1) for m in _HTML_IMAGE_RE.finditer(text))
    candidates.extend(m.group(0) for m in _URL_RE.finditer(text))

    seen: set[str] = set()
    urls: list[str] = []
    for raw in candidates:
        url = raw.strip().rstrip(".,;")
        if not url.startswith(("http://", "https://")):
            continue
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        is_image = suffix in _IMAGE_EXTS or any(marker in url for marker in _IMAGE_HOST_MARKERS)
        if is_image and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _extension_for(url: str, content_type: str | None) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in _IMAGE_EXTS:
        return suffix
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
        if ext:
            return ".jpg" if ext == ".jpe" else ext
    return ".bin"


def _verify_png_without_pillow(data: bytes, sha256: str) -> dict:
    """Verify basic PNG structure and read dimensions without optional deps."""
    if len(data) < 33 or not data.startswith(_PNG_SIGNATURE):
        raise ValueError("invalid PNG signature")
    chunk_len = struct.unpack(">I", data[8:12])[0]
    chunk_type = data[12:16]
    if chunk_type != b"IHDR" or chunk_len != 13:
        raise ValueError("missing PNG IHDR chunk")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise ValueError("invalid PNG dimensions")
    return {
        "verified": True,
        "format": "PNG",
        "width": width,
        "height": height,
        "sha256": sha256,
    }


def verify_image_file(path: str | Path) -> dict:
    """Validate a downloaded image and return structured metadata."""
    image_path = Path(path)
    data = image_path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    suffix = image_path.suffix.lower()

    if suffix == ".svg":
        try:
            root = ET.fromstring(data.decode("utf-8", errors="replace"))
            tag = root.tag.rsplit("}", 1)[-1].lower()
            if tag != "svg":
                raise ValueError(f"root tag is {tag!r}, not 'svg'")
            return {
                "verified": True,
                "format": "SVG",
                "width": root.attrib.get("width"),
                "height": root.attrib.get("height"),
                "sha256": sha256,
            }
        except Exception as e:
            return {"verified": False, "verify_error": str(e), "sha256": sha256}

    if suffix == ".png":
        try:
            return _verify_png_without_pillow(data, sha256)
        except Exception:
            pass

    try:
        from PIL import Image

        with Image.open(image_path) as img:
            img.verify()
        with Image.open(image_path) as img:
            width, height = img.size
            fmt = img.format
        return {
            "verified": True,
            "format": fmt,
            "width": width,
            "height": height,
            "sha256": sha256,
        }
    except Exception as e:
        return {"verified": False, "verify_error": str(e), "sha256": sha256}


def _download_image(url: str, dest_dir: Path, github_token: str | None = None) -> dict:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    headers = {"User-Agent": "swebench-eval-pipeline"}
    if github_token and "github" in urlparse(url).netloc:
        headers["Authorization"] = f"token {github_token}"

    try:
        with requests.get(url, headers=headers, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            ext = _extension_for(url, content_type)
            dest = dest_dir / f"{digest}{ext}"
            total = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > _MAX_IMAGE_BYTES:
                        raise ValueError(f"image exceeds {_MAX_IMAGE_BYTES} byte limit")
                    f.write(chunk)
            metadata = {
                "url": url,
                "path": str(dest.resolve()),
                "filename": dest.name,
                "content_type": content_type,
                "bytes": total,
                "ok": True,
            }
            metadata.update(verify_image_file(dest))
            return metadata
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)}


def attach_issue_media(
    instances: list[dict],
    output_dir: str | Path,
    github_token: str | None = None,
) -> list[dict]:
    """Download issue images and attach ``issue_image_urls`` / ``issue_images`` fields."""
    media_root = Path(output_dir) / "issue_media"
    manifest: dict[str, list[dict]] = {}

    for inst in instances:
        instance_id = inst["instance_id"]
        urls = inst.get("issue_image_urls") or extract_image_urls(inst.get("problem_statement") or "")
        inst["issue_image_urls"] = urls
        images: list[dict] = []
        if urls:
            dest_dir = media_root / instance_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            for url in urls:
                images.append(_download_image(url, dest_dir, github_token=github_token))
        inst["issue_images"] = images
        manifest[instance_id] = images

    media_root.mkdir(parents=True, exist_ok=True)
    with open(media_root / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    n_urls = sum(len(inst.get("issue_image_urls") or []) for inst in instances)
    n_ok = sum(1 for inst in instances for img in inst.get("issue_images") or [] if img.get("ok"))
    n_verified = sum(
        1 for inst in instances for img in inst.get("issue_images") or [] if img.get("verified")
    )
    logger.info(
        f"Issue media: found {n_urls} image URL(s), downloaded {n_ok}, verified {n_verified}."
    )
    return instances


def format_issue_media_for_prompt(instance: dict) -> str:
    """Return concise prompt text pointing agents at downloaded issue images."""
    images = [img for img in (instance.get("issue_images") or []) if img.get("ok")]
    urls = instance.get("issue_image_urls") or []
    if not images and not urls:
        return ""

    lines = [
        "Issue images/media referenced by the GitHub issue:",
        "Inspect these local image files when the issue depends on visual/domain-specific evidence.",
    ]
    for img in images:
        lines.append(f"- local: {img['path']}")
        lines.append(f"  source: {img['url']}")
        if img.get("verified"):
            size = ""
            if img.get("width") and img.get("height"):
                size = f", {img['width']}x{img['height']}"
            lines.append(f"  verified: yes ({img.get('format')}{size}, sha256={img.get('sha256')})")
        else:
            lines.append(f"  verified: no ({img.get('verify_error', 'unknown verification error')})")
    for url in urls:
        if not any(img.get("url") == url for img in images):
            lines.append(f"- source only, download failed or unavailable: {url}")
    return "\n".join(lines) + "\n\n"

import io
import json
import builtins

from swebench.eval_pipeline.media_assets import (
    attach_issue_media,
    extract_image_urls,
    format_issue_media_for_prompt,
    verify_image_file,
)
from swebench.eval_pipeline.prompt_builder import build_agent_prompt

def _tiny_png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()



def test_extract_image_urls_from_markdown_html_and_github_assets():
    text = """
    ![plot](https://github.com/user-attachments/assets/abc-123)
    <img width="400" src="https://user-images.githubusercontent.com/1/foo.png">
    plain https://example.com/not-image.txt
    plain https://example.com/figure.webp?raw=1
    """

    assert extract_image_urls(text) == [
        "https://github.com/user-attachments/assets/abc-123",
        "https://user-images.githubusercontent.com/1/foo.png",
        "https://example.com/figure.webp?raw=1",
    ]


def test_attach_issue_media_downloads_and_prompts_with_local_paths(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"content-type": "image/png"}
        data = _tiny_png_bytes()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield self.data

    def fake_get(url, **kwargs):
        assert kwargs["headers"]["User-Agent"] == "swebench-eval-pipeline"
        return FakeResponse()

    monkeypatch.setattr("swebench.eval_pipeline.media_assets.requests.get", fake_get)

    instances = [
        {
            "instance_id": "demo__repo-1",
            "repo": "demo/repo",
            "problem_statement": "See ![plot](https://example.com/figure.png)",
            "file_contents": {},
        }
    ]

    attach_issue_media(instances, tmp_path)

    inst = instances[0]
    assert inst["issue_image_urls"] == ["https://example.com/figure.png"]
    assert inst["issue_images"][0]["ok"] is True
    assert inst["issue_images"][0]["verified"] is True
    assert inst["issue_images"][0]["format"] == "PNG"
    assert inst["issue_images"][0]["width"] == 1
    assert inst["issue_images"][0]["height"] == 1
    assert len(inst["issue_images"][0]["sha256"]) == 64
    assert inst["issue_images"][0]["path"].endswith(".png")
    assert (tmp_path / "issue_media" / "manifest.json").exists()

    media_prompt = format_issue_media_for_prompt(inst)
    assert "Issue images/media" in media_prompt
    assert inst["issue_images"][0]["path"] in media_prompt
    assert "verified: yes (PNG, 1x1" in media_prompt

    prompt = build_agent_prompt(inst)
    assert inst["issue_images"][0]["path"] in prompt

    manifest = json.loads((tmp_path / "issue_media" / "manifest.json").read_text())
    assert manifest["demo__repo-1"][0]["bytes"] == len(FakeResponse.data)
    assert manifest["demo__repo-1"][0]["verified"] is True


def test_verify_image_file_rejects_invalid_image(tmp_path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"not actually an image")

    result = verify_image_file(path)

    assert result["verified"] is False
    assert "verify_error" in result
    assert len(result["sha256"]) == 64


def test_verify_png_file_without_pillow(tmp_path, monkeypatch):
    path = tmp_path / "tiny.png"
    path.write_bytes(_tiny_png_bytes())

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("No module named 'PIL'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = verify_image_file(path)

    assert result["verified"] is True
    assert result["format"] == "PNG"
    assert result["width"] == 1
    assert result["height"] == 1

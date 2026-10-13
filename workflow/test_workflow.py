"""Verify input preservation, editorial gates, assets and draft retry behavior."""
from argparse import Namespace
import hashlib
import json
from pathlib import Path
import zipfile

from bs4 import BeautifulSoup
from PIL import Image
import pytest
import yaml

import wechat


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "公众号 测试"
    (root / "workflow").mkdir(parents=True)
    (root / "workflow/preferences.yaml").write_text("theme: professional-clean\n")
    (root / "workflow/preview-template.html").write_text((wechat.ROOT / "workflow/preview-template.html").read_text())
    monkeypatch.setattr(wechat, "ROOT", root)
    return root


def approve(run, final):
    (run / "draft.md").write_text(final)
    (run / "final.md").write_text(final)
    assessment = {"decision": "pass", "pass_number": 1, "reviewed_sha256": wechat.sha(run / "final.md"),
                  "dimensions": {k: 4 for k in ["accuracy", "viewpoint", "usefulness", "voice", "readability"]},
                  "blockers": [], "major_issues": [], "notes": "test fixture"}
    (run / "assessment.yaml").write_text(yaml.safe_dump(assessment))
    Image.new("RGB", (235, 100), "white").save(run / "assets/cover.png")


def topic_run(project):
    wechat.new_run(Namespace(topic="话题", input=None, title=None))
    return next((project / "articles").iterdir())


def test_import_preserves_original_and_copies_relative_images(project, tmp_path):
    inputs = tmp_path / "输入 文稿"
    (inputs / "图 片").mkdir(parents=True)
    image = inputs / "图 片/图.png"
    Image.new("RGB", (20, 20), "white").save(image)
    text = '---\ntitle: 示例文章\nsummary: 简短摘要\n---\n\n正文。\n\n![图](<图 片/图.png>)\n'
    source = inputs / "input.md"
    source.write_text(text)
    original = source.read_bytes()
    wechat.new_run(Namespace(topic=None, input=str(source), title=None))
    run = next((project / "articles").iterdir())
    assert source.read_bytes() == original == (run / "source.md").read_bytes()
    meta = wechat.read_json(run / "meta.json")
    assert meta["title"] == "示例文章"
    assert (run / "assets/input-01.png").read_bytes() == image.read_bytes()
    assert meta["source_sha256"] == hashlib.sha256(original).hexdigest()
    final = (run / "draft.md").read_text()
    assert "assets/input-01.png" in final
    approve(run, final)
    delivery = wechat.render_run(run)
    assert delivery["ready"] is True
    body = (run / "article.html").read_text()
    assert 'src="assets/input-01.png"' in body
    assert "data:image/png;base64," in (run / "preview.html").read_text()
    with zipfile.ZipFile(run / "publish.zip") as archive:
        assert "assets/input-01.png" in archive.namelist()
        assert archive.read("assets/input-01.png") == image.read_bytes()
        assert b"assets/input-01.png" in archive.read("article.md")


def test_image_relinking_preserves_code_and_reference_labels():
    text = '![图](<图片/a (1).png>)\n\n![图][pic]\n\n[pic]: <图片/a (1).png> "标题"\n\n`![图](<图片/a (1).png>)`\n\n```md\n![图](<图片/a (1).png>)\n```\n'
    linked = wechat.map_markdown_images(text, {"图片/a (1).png": "assets/input.png"})
    assert '![图](assets/input.png)' in linked
    assert '[pic]: assets/input.png "标题"' in linked
    assert '`![图](<图片/a (1).png>)`' in linked
    assert '```md\n![图](<图片/a (1).png>)\n```' in linked


def test_code_content_and_heading_are_not_modified():
    code = '# 中文注释API\nprint("中文API")\n'
    text = '# 正确标题\n\n```python\n' + code + '```\n\n`中文API`\n'
    result = wechat.ArticleConverter().convert(text)
    soup = BeautifulSoup(result.html, "html.parser")
    assert result.title == "正确标题"
    assert soup.find("pre").get_text() == code
    assert "中文API" in [n.get_text() for n in soup.find_all("code")]


def test_render_does_not_invent_review(project):
    run = topic_run(project)
    (run / "final.md").write_text("# 示例标题\n\n文章正文。\n")
    Image.new("RGB", (235, 100), "white").save(run / "assets/cover.png")
    assert wechat.render_run(run)["ready"] is False
    assert not (run / "review.json").exists()


def test_changed_final_cannot_reuse_old_review(project):
    run = topic_run(project)
    approve(run, "# 示例标题\n\n原有正文。\n")
    assert wechat.render_run(run)["ready"]
    (run / "final.md").write_text("# 示例标题\n\n更改了事实。\n")
    with pytest.raises(ValueError, match="重新审阅"):
        wechat.render_run(run)
    assert wechat.read_json(run / "delivery.json")["ready"] is False


@pytest.mark.parametrize("fragment", ['<script>alert(1)</script>', '<img src="missing.png">', '<p onclick="alert(1)">内容</p>'])
def test_unsafe_or_missing_assets_fail_before_delivery(project, fragment):
    run = topic_run(project)
    approve(run, f"# 示例标题\n\n{fragment}\n")
    with pytest.raises(ValueError):
        wechat.render_run(run)
    assert wechat.read_json(run / "delivery.json")["ready"] is False


def test_draft_stale_html_fails_before_api_calls(project, monkeypatch):
    run = topic_run(project)
    approve(run, "# 示例标题\n\n正文。\n")
    wechat.render_run(run)
    (run / "article.html").write_text("tampered")
    with pytest.raises(ValueError, match="已变更"):
        wechat.draft_run(run)


def test_unknown_draft_is_not_automatically_retried(project):
    run = topic_run(project)
    approve(run, "# 示例标题\n\n正文。\n")
    wechat.render_run(run)
    wechat.dump(run / "draft-receipt.json", {"status": "unknown"})
    with pytest.raises(ValueError, match="避免重复创建"):
        wechat.draft_run(run)


def test_draft_uploads_media_and_reuses_receipt(project, monkeypatch):
    # Fakes verify integration behavior only; they are not a live WeChat test.
    run = topic_run(project)
    approve(run, "# 示例标题\n\n正文。\n\n![图](assets/body.png)\n")
    Image.new("RGB", (20, 20), "white").save(run / "assets/body.png")
    wechat.render_run(run)
    from wewrite.toolkit import config, publisher, wechat_api
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr(config, "load_config", lambda **kw: {"wechat": {"appid": "test", "secret": "test"}})
    monkeypatch.setattr(wechat_api, "get_access_token", lambda *a: "test-token")
    monkeypatch.setattr(wechat_api, "upload_image", lambda *a: "https://mmbiz.qpic.cn/example.png")
    monkeypatch.setattr(wechat_api, "upload_thumb", lambda *a: "thumb-id")
    def create(token, title, body, digest, thumb, author):
        calls.append(body)
        assert 'src="https://mmbiz.qpic.cn/example.png"' in body
        assert thumb == "thumb-id"
        return SimpleNamespace(media_id="test-draft")
    monkeypatch.setattr(publisher, "create_draft", create)
    first = wechat.draft_run(run)
    second = wechat.draft_run(run)
    assert first == second
    assert len(calls) == 1


def test_failed_draft_request_records_unknown_status(project, monkeypatch):
    run = topic_run(project)
    approve(run, "# 示例标题\n\n正文。\n")
    wechat.render_run(run)
    from wewrite.toolkit import config, publisher, wechat_api
    monkeypatch.setattr(config, "load_config", lambda **kw: {"wechat": {"appid": "test", "secret": "test"}})
    monkeypatch.setattr(wechat_api, "get_access_token", lambda *a: "test-token")
    monkeypatch.setattr(wechat_api, "upload_thumb", lambda *a: "thumb-id")
    def fail(*args):
        raise TimeoutError("request timed out")
    monkeypatch.setattr(publisher, "create_draft", fail)
    with pytest.raises(TimeoutError):
        wechat.draft_run(run)
    assert wechat.read_json(run / "draft-receipt.json")["status"] == "unknown"


def test_square_cover_required_validated_and_packaged(project):
    (project / 'workflow/preferences.yaml').write_text('theme: professional-clean\ncover:\n  square_required: true\n')
    run = topic_run(project)
    approve(run, '# 双封面文章\n\n正文。\n')
    assert wechat.read_json(run / 'meta.json')['square_cover'] == 'assets/cover-square.png'
    assert wechat.render_run(run)['ready'] is False
    square = run / 'assets/cover-square.png'
    Image.new('RGB', (200, 100), 'white').save(square)
    with pytest.raises(ValueError, match='1:1'):
        wechat.render_run(run)
    Image.new('RGB', (200, 200), 'white').save(square)
    delivery = wechat.render_run(run)
    assert delivery['ready'] is True
    assert delivery['square_cover']['sha256'] == wechat.sha(square)
    assert '正方形小封面' in (run / 'preview.html').read_text()
    with zipfile.ZipFile(run / 'publish.zip') as archive:
        assert archive.read('assets/cover-square.png') == square.read_bytes()


def test_render_preserves_authored_disclosure_without_inventing_testing():
    result = wechat.ArticleConverter().convert('# 示例标题\n\n本文未做实测。\n\n正文由 AI 辅助整理。\n')
    text = BeautifulSoup(result.html, 'html.parser').get_text()
    assert '正文由 AI 辅助整理' in text
    assert '作者进行了实测验证' not in text

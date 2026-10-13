"""Deterministic files, diagrams, WeWrite rendering, and optional draft delivery.

Research, writing, Humanizer editing and editorial judgement belong to the current agent.
This module never calls a second writing model or pretends to perform review.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import html
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
from zoneinfo import ZoneInfo

import markdown
import yaml
from bs4 import BeautifulSoup
from PIL import Image
from wewrite.commands.content_eval import build_report
from wewrite.commands.validate_html import validate_html
from wewrite.toolkit.converter import WeChatConverter, make_paste_safe


ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[ \t]*$")
MERMAID = re.compile(r"(?ms)^ {0,3}(`{3,}|~{3,})mermaid[ \t]*\n(.*?)^ {0,3}\1[ \t]*$")


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def split_document(text):
    match = re.match(r"\A\ufeff?---\s*\n(.*?)\n---[ \t]*\n", text, re.S)
    if match:
        metadata = yaml.safe_load(match[1]) or {}
        if not isinstance(metadata, dict):
            raise ValueError("Markdown front matter 必须是对象")
        return metadata, text[match.end():]
    return {}, text.lstrip("\ufeff")


class ArticleConverter(WeChatConverter):
    """Protect code and link targets from upstream heading/spacing rewriting."""
    def _append_aigc_footer(self, html):
        # Do not invent author testing/editing claims. Authored disclosures remain
        # in final.md; platform declarations are configured separately at publish.
        return html

    def _extract_title(self, text):
        return super()._extract_title(FENCE.sub("", text))

    def _strip_h1(self, text):
        protected = []
        def save(match):
            protected.append(match[0])
            return f"WECHATFENCEDBLOCK{len(protected)-1}END"
        text = super()._strip_h1(FENCE.sub(save, text))
        for index, block in enumerate(protected):
            text = text.replace(f"WECHATFENCEDBLOCK{index}END", block)
        return text

    def _fix_cjk_spacing(self, text):
        # The upstream pass spaces all Markdown, including code and URLs.
        # Preserve code and link syntax; normal prose still gets CJK spacing.
        protected = []
        def save(match):
            protected.append(match[0])
            return f"WECHATPROTECTED{len(protected)-1}END"
        text = FENCE.sub(save, text)
        text = re.sub(r"(`+)([^\n]*?)\1|!?\[[^\n]*?\]\([^\n]*?\)|^\[[^\n]+?\]:.*$", save, text, flags=re.M)
        text = super()._fix_cjk_spacing(text)
        for index, fragment in enumerate(protected):
            text = text.replace(f"WECHATPROTECTED{index}END", fragment)
        return text


def local_image(src, base):
    from urllib.parse import unquote, urlsplit
    url = urlsplit(src)
    if url.scheme in {"https", "http"}:
        return None
    if url.scheme or url.netloc:
        raise ValueError(f"不支持的图片地址：{src}")
    return (base / unquote(url.path)).resolve()


def verify_image(path):
    if not path.is_file():
        raise ValueError(f"图片不存在：{path}")
    with Image.open(path) as image:
        if image.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
            raise ValueError(f"图片需转换为 PNG/JPEG/WEBP/GIF：{path}")
        image.verify()


def map_markdown_images(text, mapping):
    """Relink copied images in the derivative Markdown, leaving source/code intact."""
    protected = []
    def save(match):
        protected.append(match[0])
        return f"WECHATIMAGECODE{len(protected)-1}END"
    text = FENCE.sub(save, text)
    text = re.sub(r"(`+)([^\n]*?)\1", save, text)
    def replace(match):
        target = match[2] or match[3]
        replacement = mapping.get(target)
        if not replacement:
            return match[0]
        return match[1] + replacement + match[4]
    text = re.sub(r'(!?\[[^\n]*?\]\()\s*(?:<([^>]+)>|([^\s]+?))(\s+(?:"[^"\n]*"|\'[^\'\n]*\')\s*\)|\))', replace, text)
    def reference(match):
        target = match[2] or match[3]
        return match[1] + mapping.get(target, target) + match[4]
    text = re.sub(r'^(\s*\[[^\n]+?\]:\s*)(?:<([^>]+)>|([^\s]+))(.*)$', reference, text, flags=re.M)
    def raw_image(match):
        soup = BeautifulSoup(match[0], "html.parser")
        node = soup.find("img")
        if node.get("src") in mapping:
            node["src"] = mapping[node["src"]]
            return str(node)
        return match[0]
    text = re.sub(r"<img\b[^>]*>", raw_image, text, flags=re.I)
    for index, code in enumerate(protected):
        text = text.replace(f"WECHATIMAGECODE{index}END", code)
    return text


def new_run(args):
    prefs = yaml.safe_load((ROOT / "workflow/preferences.yaml").read_text())
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d-%H%M%S-%f")
    run = ROOT / "articles" / stamp
    run.mkdir(parents=True)
    (run / "assets/prompts").mkdir(parents=True)
    metadata = {"version": 1, "created_at": now(), "mode": "markdown" if args.input else "topic",
                "topic": args.topic or "", "title": args.title or "", "digest": "",
                "theme": prefs["theme"], "cover": "assets/cover.png", "source_images": {}}
    if prefs.get("cover", {}).get("square_required", False):
        metadata["square_cover"] = "assets/cover-square.png"
    if args.input:
        source = Path(args.input).expanduser().resolve()
        raw = source.read_bytes()
        (run / "source.md").write_bytes(raw)
        front, body = split_document(raw.decode("utf-8"))
        metadata.update({"source_path": str(source), "source_sha256": hashlib.sha256(raw).hexdigest()})
        metadata["title"] = args.title or str(front.get("title") or ArticleConverter()._extract_title(body) or source.stem)
        metadata["digest"] = str(front.get("description") or front.get("summary") or "")
        soup = BeautifulSoup(markdown.markdown(body, extensions=["fenced_code", "tables"]), "html.parser")
        for index, src in enumerate(dict.fromkeys(i.get("src", "") for i in soup.find_all("img")), 1):
            image = local_image(src, source.parent)
            if image is None:
                continue
            verify_image(image)
            target = run / "assets" / f"input-{index:02d}{image.suffix.lower()}"
            shutil.copy2(image, target)
            metadata["source_images"][src] = target.relative_to(run).as_posix()
        body = map_markdown_images(body, metadata["source_images"])
        if not ArticleConverter()._extract_title(body):
            body = f"# {metadata['title']}\n\n" + body
        (run / "draft.md").write_text(body, encoding="utf-8")
    dump(run / "meta.json", metadata)
    print(str(run))


def sanitize_body(soup):
    issues = []
    forbidden = {"script", "style", "iframe", "object", "embed", "form", "input", "button", "svg", "link", "meta", "base"}
    for tag in soup.find_all(True):
        if tag.name in forbidden:
            issues.append(f"正文含不支持的 HTML 标签：{tag.name}")
        for key, value in tag.attrs.items():
            if key.lower().startswith("on") or key.lower() == "srcdoc":
                issues.append(f"正文含不支持的 HTML 属性：{key}")
            if key.lower() in {"src", "href"} and re.match(r"\s*(javascript|vbscript|data):", str(value), re.I):
                issues.append("正文含不支持的地址协议")
    if issues:
        raise ValueError("；".join(dict.fromkeys(issues)))


def render_diagrams(text, run):
    specs = []
    def replace(match):
        digest = hashlib.sha256(match[2].encode()).hexdigest()[:12]
        relative = f"assets/diagram-{len(specs)+1:02d}-{digest}.png"
        specs.append({"code": match[2], "output": str(run / relative)})
        return f"![流程示意图]({relative})"
    result = MERMAID.sub(replace, text)
    if specs:
        manifest = run / "assets/diagrams.json"
        dump(manifest, specs)
        runtime = read_json(ROOT / "workflow/runtime.json")
        subprocess.run([runtime["node"], str(ROOT / "workflow/render_mermaid.mjs"), str(manifest)], check=True, timeout=90)
    return result


def load_run(run):
    run = Path(run).expanduser().resolve()
    return run, read_json(run / "meta.json")


def render_run(run_path):
    run, meta = load_run(run_path)
    # Invalidate an old ready result before attempting any new render.
    dump(run / "delivery.json", {"ready": False, "status": "rendering"})
    final = run / "final.md"
    _, text = split_document(final.read_text(encoding="utf-8"))
    converter = ArticleConverter(theme_name=meta["theme"])
    title = converter._extract_title(text) or meta["title"]
    if not title or len(title.encode("utf-8")) > 64:
        raise ValueError("请提供非空标题；本流程标题控制在 64 UTF-8 字节以内")
    content = map_markdown_images(render_diagrams(text, run), meta.get("source_images", {}))
    result = converter.convert(content)
    soup = BeautifulSoup(result.html, "html.parser")
    sanitize_body(soup)
    images = []
    for node in soup.find_all("img"):
        src = node.get("src", "")
        mapped = meta.get("source_images", {}).get(src, src)
        image = local_image(mapped, run)
        if image is None:
            images.append({"source": src, "remote": True})
            continue
        if not image.is_relative_to(run):
            raise ValueError("正文图片需放入当前文章的 assets/ 目录")
        verify_image(image)
        relative = image.relative_to(run).as_posix()
        node["src"] = relative
        images.append({"source": relative, "remote": False, "sha256": sha(image)})
    if len(images) > 10:
        raise ValueError("本流程默认最多 10 张正文图，请精简图位")
    if any(len(row.find_all(["th", "td"], recursive=False)) > 4 for row in soup.find_all("tr")):
        raise ValueError("手机排版默认最多 4 列，请拆表或转图")
    body = make_paste_safe(str(soup))
    problems = validate_html(body)
    if any(issue["level"] == "ERROR" for issue in problems):
        raise ValueError(json.dumps(problems, ensure_ascii=False))
    (run / "article.html").write_text(body, encoding="utf-8")
    # A separate rendered Markdown resolves imported images and Mermaid blocks.
    # It is an intermediate artifact; final.md remains the authoritative text.
    (run / "rendered.md").write_text(content, encoding="utf-8")
    digest = meta.get("digest") or result.digest
    if len(digest.encode("utf-8")) > 120:
        raise ValueError("摘要超过本流程的 120 UTF-8 字节限制，请缩短")
    cover = run / meta.get("cover", "assets/cover.png")
    if not cover.resolve().is_relative_to(run):
        raise ValueError("封面需放入当前文章目录")
    cover_info = {"path": meta.get("cover"), "present": cover.is_file()}
    if cover.is_file():
        verify_image(cover)
        cover_info["sha256"] = sha(cover)
    square_info = None
    square = None
    if meta.get("square_cover"):
        square = (run / meta["square_cover"]).resolve()
        if not square.is_relative_to(run):
            raise ValueError("正方形封面需放入当前文章目录")
        square_info = {"path": meta["square_cover"], "present": square.is_file()}
        if square.is_file():
            verify_image(square)
            with Image.open(square) as image:
                if image.width != image.height:
                    raise ValueError("小封面必须为 1:1 正方形")
            square_info["sha256"] = sha(square)
    review = None
    if (run / "assessment.yaml").is_file():
        assessment = yaml.safe_load((run / "assessment.yaml").read_text())
        if not isinstance(assessment, dict) or assessment.get("reviewed_sha256") != sha(final):
            raise ValueError("编辑判断未绑定当前终稿，请重新审阅并填写 reviewed_sha256")
        draft = (run / "draft.md").read_text(encoding="utf-8")
        review = build_report(draft, text, assessment)
        review["final_sha256"] = sha(final)
        dump(run / "review.json", review)
    ready = bool(review and review["publishable"] and cover_info["present"] and (square_info is None or square_info["present"]))
    delivery = {"version": 1, "generated_at": now(), "ready": ready,
                "status": "local_complete" if ready else "needs_cover_or_editorial_review",
                "title": title, "digest": digest, "theme": meta["theme"], "author": meta.get("author", ""),
                "final_sha256": sha(final), "html_sha256": sha(run / "article.html"),
                "cover": cover_info, "square_cover": square_info, "images": images, "compatibility": problems,
                "editorial_review": "Agent/editor assessment; not independent fact-checking",
                "wechat_console_verified": False, "device_verified": False}
    dump(run / "delivery.json", delivery)
    preview = BeautifulSoup(body, "html.parser")
    for node in preview.find_all("img"):
        src = node.get("src", "")
        if not src.startswith(("http://", "https://")):
            node["src"] = data_uri(run / src)
    cover_html = f'<img class="cover" alt="文章封面" src="{data_uri(cover)}">' if cover.is_file() else ""
    if square and square.is_file():
        cover_html += (f'<p>正方形小封面（1:1）</p><img class="cover" style="max-width:160px" '
                       f'alt="正方形小封面" src="{data_uri(square)}">'
                       f'<a class="download" href="{html.escape(meta["square_cover"], quote=True)}" download>下载正方形小封面</a>')
    values = {"__TITLE__": html.escape(title), "__DIGEST__": html.escape(digest),
              "__STATUS__": "成稿、封面与本地排版已完成" if ready else "排版已生成，待完成封面或编辑审核",
              "__COVER__": cover_html, "__BODY__": str(preview),
              "__IMAGE_NOTE__": "正文图片粘贴后如未导入，请从文件包的 assets/ 上传到对应图位。" if images else ""}
    template = (ROOT / "workflow/preview-template.html").read_text()
    # One substitution pass prevents user text from being interpreted as template tokens.
    preview_html = re.sub(r"__[A-Z_]+__", lambda m: values[m[0]], template)
    (run / "preview.html").write_text(preview_html, encoding="utf-8")
    note = (f"标题：{title}\n摘要：{digest}\n\n"
            "打开 preview.html，点击「复制排版正文」，粘贴到公众号编辑器。\n"
            "设置标题、摘要和 assets/cover.png 封面。正文图如果未随粘贴导入，上传 assets/ 中的对应图片。\n"
            "article.md 是图片路径已解析、流程图已转成 PNG 的可复用 Markdown；final.md 保留权威终稿。\n"
            "article.html 是内联样式正文，图片地址是文件包内相对路径。\n"
            "本地预览通过不等于公众号后台或手机验收通过；在后台预览后发表。\n"
            "已配置公众号接口且明确要求送草稿箱时，由助手调用草稿接口。\n")
    if square_info:
        note += "正方形小封面：assets/cover-square.png；在后台封面设置或裁切界面选择。无需为同一篇文章新建第二条图文。\n"
    (run / "发表说明.txt").write_text(note, encoding="utf-8")
    with zipfile.ZipFile(run / "publish.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["final.md", "article.html", "preview.html", "delivery.json", "发表说明.txt"]:
            archive.write(run / name, name)
        archive.write(run / "rendered.md", "article.md")
        for image in images:
            if not image["remote"]:
                archive.write(run / image["source"], image["source"])
        if cover.is_file() and cover.relative_to(run).as_posix() not in {i["source"] for i in images}:
            archive.write(cover, cover.relative_to(run).as_posix())
        if square and square.is_file() and square.relative_to(run).as_posix() not in {i["source"] for i in images}:
            archive.write(square, square.relative_to(run).as_posix())
    return delivery


def data_uri(path):
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def draft_run(run_path):
    # Call only after an explicit user instruction to put this article in drafts.
    run, meta = load_run(run_path)
    delivery = read_json(run / "delivery.json")
    if not delivery.get("ready") or sha(run / "final.md") != delivery.get("final_sha256") or sha(run / "article.html") != delivery.get("html_sha256"):
        raise ValueError("成稿未通过审核或已变更，请先重新审稿和排版")
    cover = run / delivery["cover"]["path"]
    if sha(cover) != delivery["cover"]["sha256"]:
        raise ValueError("封面已变更，请重新排版")
    for image in delivery["images"]:
        if not image["remote"] and sha(run / image["source"]) != image["sha256"]:
            raise ValueError("正文图片已变更，请重新排版")
        if image["remote"]:
            from urllib.parse import urlsplit
            host = urlsplit(image["source"]).hostname or ""
            if host != "mmbiz.qpic.cn":
                raise ValueError("外部图片请先保存为当前文章的本地图片，再送草稿箱")
    fingerprint = hashlib.sha256(json.dumps({k: delivery[k] for k in ["title", "digest", "author", "html_sha256", "cover", "images"]}, sort_keys=True).encode()).hexdigest()
    receipt = run / "draft-receipt.json"
    if receipt.exists():
        previous = read_json(receipt)
        if previous.get("status") == "created" and previous.get("fingerprint") == fingerprint:
            return previous
        raise ValueError("已有草稿请求记录，请核对公众号后台后再处理，避免重复创建")
    # Keep credentials out of run artifacts, logs and command-line arguments.
    from wewrite.toolkit.config import load_config
    from wewrite.toolkit.wechat_api import get_access_token, upload_image, upload_thumb
    from wewrite.toolkit.publisher import create_draft
    cfg = load_config(force_reload=True).get("wechat", {})
    appid, secret = cfg.get("appid"), cfg.get("secret")
    if not appid or not secret:
        raise ValueError("尚未配置 WECHAT_APPID / WECHAT_SECRET；本地发表文件包已经可用")
    token = get_access_token(appid, secret)
    soup = BeautifulSoup((run / "article.html").read_text(), "html.parser")
    uploads = {}
    for node in soup.find_all("img"):
        src = node["src"]
        if src.startswith(("http://", "https://")):
            continue
        if src not in uploads:
            uploads[src] = upload_image(token, str(run / src))
        node["src"] = uploads[src]
    thumb = upload_thumb(token, str(cover))
    dump(receipt, {"status": "request_sent", "fingerprint": fingerprint, "time": now()})
    try:
        result = create_draft(token, delivery["title"], str(soup), delivery["digest"], thumb, delivery["author"] or cfg.get("author"))
    except Exception:
        # The backend may have accepted a timed-out request. Never auto-retry it.
        dump(receipt, {"status": "unknown", "fingerprint": fingerprint, "time": now()})
        raise
    receipt_data = {"status": "created", "fingerprint": fingerprint, "media_id": result.media_id, "time": now()}
    dump(receipt, receipt_data)
    return receipt_data


def doctor():
    sources = read_json(ROOT / "projects/SOURCES.json")
    runtime_path = ROOT / "workflow/runtime.json"
    runtime = read_json(runtime_path) if runtime_path.is_file() else {}
    return {"source_projects": sources, "python": sys.version.split()[0],
            "node_ready": Path(runtime.get("node", "")).is_file(), "browser_ready": Path(runtime.get("browser", "")).is_file(),
            "mermaid_ready": (ROOT / "workflow/node_modules/mermaid/dist/mermaid.min.js").is_file(),
            "skill_ready": (ROOT / "workflow/skills/wechat-article-workflow/SKILL.md").is_file(),
            "wechat_credentials_present": bool(os.environ.get("WECHAT_APPID") and os.environ.get("WECHAT_SECRET")),
            "external_draft_tested": False}


def main():
    parser = argparse.ArgumentParser(description="公众号本地制作工具；写作由当前 Agent 完成")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("new")
    group = create.add_mutually_exclusive_group(required=True)
    group.add_argument("--topic")
    group.add_argument("--input")
    create.add_argument("--title")
    for name in ["render", "draft"]:
        command = sub.add_parser(name)
        command.add_argument("run")
    sub.add_parser("doctor")
    args = parser.parse_args()
    os.environ["WEWRITE_HOME"] = str(ROOT / "workflow/state")
    try:
        if args.command == "new":
            new_run(args)
        else:
            result = render_run(args.run) if args.command == "render" else draft_run(args.run) if args.command == "draft" else doctor()
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        # requests errors may contain URL query credentials. Redact before printing.
        message = str(exc)
        for key in ["WECHAT_SECRET", "WECHAT_APPID"]:
            if os.environ.get(key):
                message = message.replace(os.environ[key], "[redacted]")
        message = re.sub(r"(access_token|secret|appid)=([^&\s]+)", r"\1=[redacted]", message)
        print(f"Error: {message}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

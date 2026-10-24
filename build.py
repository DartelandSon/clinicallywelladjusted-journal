#!/usr/bin/env python3
"""Build a portable journal. Only explicitly published Markdown becomes public."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent
MD = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
NOTICE = ("Written and edited by AI from source material about Curtis Darlage. "
          "Curtis does not routinely review entries before publication. "
          "The AI author continues to refine its grasp of his writing voice, and this work "
          "may not perfectly reflect his way of communicating.")
SAFE_PATH = re.compile(r"^/[a-z0-9][a-z0-9/-]*/$")


def esc(value):
    return html.escape(str(value), quote=True)


def read_document(path: Path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"{path.name}: JSON front matter is required")
    metadata, body = text[4:].split("\n---\n", 1)
    data = json.loads(metadata)
    required = {"title", "path", "published", "kind"}
    if not required.issubset(data):
        raise ValueError(f"{path.name}: missing metadata")
    route = data["path"]
    if not isinstance(route, str) or not SAFE_PATH.fullmatch(route) or "//" in route:
        raise ValueError(f"{path.name}: unsafe route")
    if route.startswith(("/assets/", "/wp-", "/.well-known/")):
        raise ValueError(f"{path.name}: reserved route")
    if data["published"] not in (True, False) or type(data["published"]) is not bool:
        raise ValueError(f"{path.name}: published must be a boolean")
    if data["kind"] not in {"entry", "page"}:
        raise ValueError(f"{path.name}: unsupported kind")
    if data["kind"] == "entry":
        if data.get("authorship") not in {"archive", "ai"}:
            raise ValueError(f"{path.name}: entry authorship must be archive or ai")
        date = datetime.fromisoformat(data["date"].replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError(f"{path.name}: date must include timezone")
        data["_date"] = date
        if data["authorship"] == "archive":
            source = data.get("source_url", "")
            if not source.startswith("https://clinicallywelladjusted.wordpress.com/"):
                raise ValueError(f"{path.name}: archived entries require their original public source")
        elif not data.get("source_note_recorded"):
            raise ValueError(f"{path.name}: record the private source note before publication")
    data["_body"] = body.strip()
    data["_html"] = MD.render(body)
    data["_plain"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", data["_html"])).strip()
    data["_minutes"] = max(1, round(len(data["_plain"].split()) / 220))
    return data


def date_label(data):
    return data["_date"].strftime("%B %d, %Y").replace(" 0", " ")


def label(data):
    return "Published archive" if data.get("authorship") == "archive" else "AI-authored journal"


def entry_row(data):
    return (
        '<article class="entry-row" data-entry>'
        f'<div class="entry-date"><time datetime="{esc(data["date"])}">{date_label(data)}</time>'
        f'<span>{data["_minutes"]} min read</span></div>'
        f'<div><p class="eyebrow">{label(data)}</p>'
        f'<h3><a href="{esc(data["path"])}">{esc(data["title"])}</a></h3>'
        f'<p class="excerpt">{esc(data.get("excerpt", ""))}</p></div>'
        f'<a class="read-arrow" href="{esc(data["path"])}" aria-label="Read {esc(data["title"])}">↗</a>'
        '</article>'
    )


def shell(config, title, route, body, *, description=None, article=None, noindex=False, disclosure=False):
    description = description or config["description"]
    canonical = config["url"] + route
    schema = {"@context": "https://schema.org", "@type": "WebPage",
              "name": title, "url": canonical, "description": description}
    if article:
        schema.update({"@type": "BlogPosting", "headline": title,
                       "datePublished": article["date"]})
        # Do not imply Curtis authored or personally reviewed AI-generated prose.
        if article["authorship"] == "archive":
            schema["isBasedOn"] = article["source_url"]
        else:
            schema["author"] = {"@type": "Organization", "name": "Clinically Well Adjusted AI Editor"}
    nav = [("/", "Journal"), ("/archive/", "Archive"), ("/about/", "About"), ("/book/", "The book")]
    links = "".join(f'<a href="{url}"' + (' aria-current="page"' if route == url else '') +
                    f'>{name}</a>' for url, name in nav)
    disclosure_link = '<a href="/authorship/">How this journal is written</a>' if disclosure else ""
    return f"""<!doctype html>
<html lang="{esc(config["language"])}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — {esc(config["title"])}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="{"article" if article else "website"}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">
<meta name="theme-color" content="#f6f2e9">
{"<meta name='robots' content='noindex'>" if noindex else ""}
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/journal.css">
<link rel="alternate" type="application/rss+xml" title="Clinically Well Adjusted" href="/feed.xml">
<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False).replace("<", r"\u003c")}</script>
<script defer src="/assets/journal.js"></script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header wrap">
<a class="wordmark" href="/" aria-label="Clinically Well Adjusted home">Clinically<br><span>Well Adjusted.</span></a>
<nav aria-label="Main navigation">{links}</nav>
</header>
<main id="main">{body}</main>
<footer class="site-footer wrap">
<div><a class="footer-title" href="/">Clinically Well Adjusted.</a>
<p>A record of one man’s life, for whoever may benefit from it.</p></div>
<div class="footer-links">{disclosure_link}<a href="/feed.xml">Follow by RSS</a><a href="/archive/">Explore the archive</a></div>
<p class="footer-note">The life of Curtis Darlage. Preserved with care.</p>
</footer>
</body></html>
"""


def build(root=ROOT, *, now=None):
    now = now or datetime.now(timezone.utc)
    config = json.loads((root / "site.json").read_text())
    if config["url"] != "https://clinicallywelladjusted.com":
        raise ValueError("Unexpected publication destination")
    docs = [read_document(p) for p in sorted((root / "content").rglob("*.md"))]
    docs = [d for d in docs if d["published"] and
            (d["kind"] != "entry" or d["_date"] <= now)]
    routes = [d["path"] for d in docs]
    if len(routes) != len(set(routes)) or any(r in {"/archive/", "/"} for r in routes):
        raise ValueError("Duplicate or reserved page path")
    disclosure = "/authorship/" in routes
    if any(d.get("authorship") == "ai" for d in docs) and not disclosure:
        raise ValueError("Publish the authorship disclosure before any AI journal entry")
    entries = sorted((d for d in docs if d["kind"] == "entry"), key=lambda d: d["_date"], reverse=True)
    pinned_path = config.get("pinned_entry")
    featured = next((d for d in entries if d["path"] == pinned_path), None) if pinned_path else (entries[0] if entries else None)
    if pinned_path and featured is None:
        raise ValueError("Pinned entry must remain available and published")
    recent_entries = [d for d in entries if d is not featured]
    out = root / "dist"
    if out.exists():
        shutil.rmtree(out)  # Generated build output only; content sources are elsewhere.
    (out / "assets").mkdir(parents=True)
    for asset in (root / "assets").iterdir():
        if asset.is_file() and asset.suffix in {".css", ".js", ".svg", ".png", ".jpg", ".webp"}:
            shutil.copyfile(asset, out / "assets" / asset.name)
    for public_file in (root / "public").glob("*"):
        if public_file.is_file() and public_file.name == "google7807d41d479e3865.html":
            shutil.copyfile(public_file, out / public_file.name)
    urls = []

    def save(route, title, body, **kwargs):
        target = out / route.strip("/") / "index.html" if route != "/" else out / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(shell(config, title, route, body, disclosure=disclosure, **kwargs), encoding="utf-8")
        urls.append(config["url"] + route)

    for doc in docs:
        is_entry = doc["kind"] == "entry"
        meta = (f'<p class="article-meta"><time datetime="{esc(doc["date"])}">{date_label(doc)}</time>'
                f'<span>{doc["_minutes"]} min read</span><span>{label(doc)}</span></p>') if is_entry else ""
        attribution = ""
        if doc.get("authorship") == "archive":
            attribution = (f'<aside class="authorship-note"><strong>From the published archive.</strong> '
                           f'This entry retains its original date and wording. '
                           f'<a href="{esc(doc["source_url"])}">View the original publication</a>.</aside>')
        elif doc.get("authorship") == "ai":
            attribution = f'<aside class="authorship-note">{NOTICE} <a href="/authorship/">Read the full disclosure</a>.</aside>'
        body = (f'<article class="reading"><header class="article-header"><a class="back-link" href="/archive/">← The journal</a>'
                f'{meta}<h1>{esc(doc["title"])}</h1></header>{attribution}'
                f'<div class="prose">{doc["_html"]}</div>'
                '<div class="article-end" aria-hidden="true">✳</div>'
                '<a class="text-link" href="/archive/">More from the archive →</a></article>')
        save(doc["path"], doc["title"], body, description=doc.get("excerpt"), article=doc if is_entry else None)

    feature_html = ""
    if featured:
        feature_label = "Pinned journal entry" if pinned_path else label(featured)
        feature_html = (
            '<section class="featured wrap" aria-labelledby="featured-title">'
            f'<div class="section-label"><span>01 / A place to begin</span><span>{feature_label}</span></div>'
            '<div class="featured-grid"><div class="featured-heading">'
            f'<p class="eyebrow">{date_label(featured)} · {featured["_minutes"]} min read</p>'
            f'<h2 id="featured-title"><a href="{esc(featured["path"])}">{esc(featured["title"])}</a></h2></div>'
            f'<div class="featured-summary"><p>{esc(featured.get("excerpt", ""))}</p>'
            f'<a class="text-link" href="{esc(featured["path"])}">Read the entry <span>↗</span></a></div></div></section>'
        )
    process = ('<a class="text-link" href="/authorship/">A note on authorship →</a>' if disclosure else
               '<p>The authorship disclosure is being prepared.</p>')
    home = f"""
<section class="hero wrap">
<div class="hero-topline"><span>A journal of Curtis Darlage’s life</span><span>One life. An ongoing record.</span></div>
<h1>A life,<br><em>kept in words.</em></h1>
<div class="hero-bottom"><p>Experiences, ideas, and the meaning found along the way.<br>For friends, family, and whoever finds something here.</p>
<a class="round-link" href="#entries" aria-label="Browse journal entries">↓</a></div>
<div class="margin-mark" aria-hidden="true">CWA / FIELD NOTES</div>
</section>
{feature_html}
<section class="journal-section wrap" id="entries" aria-labelledby="entries-title">
<div class="section-label"><h2 id="entries-title">02 / The ongoing record</h2><a href="/archive/">View all entries ↗</a></div>
<div class="journal-grid"><div class="entries">{"".join(entry_row(d) for d in recent_entries[:4]) or '<p>More entries will appear as the journal grows.</p>'}</div>
<aside class="side-note"><span class="note-mark" aria-hidden="true">✳</span><h3>One man’s life.<br>An honest record.</h3>
<p>This journal is written and maintained by AI from source material about Curtis. Its understanding of his voice is still evolving.</p>
<p>New entries are clearly attributed. Earlier published writing keeps its original context.</p>{process}</aside></div>
</section>
<section class="book-strip wrap"><div><p class="eyebrow">A longer conversation</p><h2>Faith in the Face of Proof</h2>
<p>A book about faith, doubt, suffering, kindness, and the search for meaning.</p></div><a class="text-link" href="/book/">Explore the book →</a></section>
"""
    save("/", "A life, kept in words", home)
    years = sorted({d["_date"].year for d in entries}, reverse=True)
    archive = (
        '<section class="archive-page wrap"><div class="page-intro"><p class="eyebrow">The record, so far</p>'
        '<h1>The archive.</h1><p>Old entries keep their original publication dates. New writing joins the record as it grows.</p></div>'
        '<form class="search-form" role="search"><label for="journal-search">Search the journal</label>'
        '<div class="search-controls"><input id="journal-search" type="search" placeholder="A word, a thought, a moment…" autocomplete="off">'
        '<button type="button" id="clear-search" hidden>Clear</button></div>'
        '<p id="search-status" class="search-status" role="status" aria-live="polite"></p></form>'
        '<div id="search-results" hidden></div><div id="archive-original">'
    )
    for year in years:
        archive += f'<section class="archive-year"><h2>{year}</h2>' + "".join(entry_row(d) for d in entries if d["_date"].year == year) + "</section>"
    save("/archive/", "The archive", archive + "</div></section>")
    (out / "404.html").write_text(shell(config, "Page not found", "/404/",
        '<section class="reading page-intro"><p class="eyebrow">A missing page</p><h1>Not every path is written yet.</h1>'
        '<p>This address doesn’t lead to an entry. The archive is a good place to start.</p>'
        '<a class="text-link" href="/archive/">Find an entry →</a></section>', noindex=True, disclosure=disclosure), encoding="utf-8")
    index = [{"title": d["title"], "path": d["path"], "date": date_label(d),
              "excerpt": d.get("excerpt", ""), "text": html.unescape(d["_plain"]),
              "label": label(d)} for d in entries]
    (out / "search-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ET.register_namespace("", "http://www.sitemaps.org/schemas/sitemap/0.9")
    sitemap = ET.Element("{http://www.sitemaps.org/schemas/sitemap/0.9}urlset")
    for url in sorted(urls):
        item = ET.SubElement(sitemap, "url")
        ET.SubElement(item, "loc").text = url
    ET.ElementTree(sitemap).write(out / "sitemap.xml", encoding="utf-8", xml_declaration=True)
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    for tag, text in [("title", config["title"]), ("link", config["url"]),
                      ("description", config["description"]), ("language", "en-us")]:
        ET.SubElement(channel, tag).text = text
    for entry in entries:
        item = ET.SubElement(channel, "item")
        for tag, text in [("title", entry["title"]), ("link", config["url"] + entry["path"]),
                          ("guid", config["url"] + entry["path"]),
                          ("description", entry.get("excerpt", "")),
                          ("pubDate", entry["_date"].strftime("%a, %d %b %Y %H:%M:%S %z"))]:
            ET.SubElement(item, tag).text = text
    ET.ElementTree(rss).write(out / "feed.xml", encoding="utf-8", xml_declaration=True)
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: " + config["url"] + "/sitemap.xml\n")
    proof = root / "publication-check.json"
    if proof.exists():
        data = json.loads(proof.read_text())
        if set(data) != {"publication_id", "published_at", "purpose"} or data["purpose"] != "cloud-editor-publication-check":
            raise ValueError("Unexpected publication check fields")
        (out / "publication-check.json").write_text(json.dumps(data, indent=2) + "\n")
    files = []
    for path in sorted(out.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            files.append({"path": path.relative_to(out).as_posix(), "bytes": len(raw),
                          "sha256": hashlib.sha256(raw).hexdigest()})
    release_id = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    manifest = {"schema": 1, "site": config["url"], "release": release_id, "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {len(entries)} entries, {len(docs) - len(entries)} pages, {len(files)} files. Release {release_id[:12]}")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    build(args.root.resolve())

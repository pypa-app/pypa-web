#!/usr/bin/env python3
"""
repo_manager.py
A small repository management CLI for pypa-app/pypa-web.

Features:
- report: scan HTML files, counts, sizes, top largest, save JSON report
- list: list HTML files
- search: search inside HTML files for a string
- preview: run a simple HTTP server to preview files
- create-issue: (optional) create a GitHub issue with the report when GITHUB_TOKEN is set

Usage examples:
  python3 scripts/repo_manager.py report
  python3 scripts/repo_manager.py list
  python3 scripts/repo_manager.py search --query "TODO"
  python3 scripts/repo_manager.py preview --port 8000
  GITHUB_TOKEN=ghp_xxx python3 scripts/repo_manager.py create-issue --repo pypa-app/pypa-web --title "Repo report"

"""

from __future__ import annotations
import argparse
import os
import json
import sys
import http.server
import socketserver
import urllib.request
import urllib.error
from typing import List, Tuple


def find_html_files(root: str) -> List[str]:
    html_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # skip .git and virtualenv folders
        if ".git" in dirpath.split(os.sep):
            continue
        for fn in filenames:
            if fn.lower().endswith(".html"):
                html_files.append(os.path.join(dirpath, fn))
    return html_files


def file_sizes(paths: List[str]) -> List[Tuple[str, int]]:
    out = []
    for p in paths:
        try:
            out.append((p, os.path.getsize(p)))
        except OSError:
            out.append((p, 0))
    return out


def cmd_report(args: argparse.Namespace) -> int:
    root = args.path or os.getcwd()
    htmls = find_html_files(root)
    sizes = file_sizes(htmls)
    total_size = sum(s for _, s in sizes)
    data = {
        "root": os.path.abspath(root),
        "html_count": len(htmls),
        "total_size_bytes": total_size,
        "top_largest": sorted([{"path": p, "size": s} for p, s in sizes], key=lambda x: x["size"], reverse=True)[: args.top],
    }
    os.makedirs(args.outdir, exist_ok=True)
    outpath = os.path.join(args.outdir, args.outfile)
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Report written to: {outpath}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = args.path or os.getcwd()
    htmls = find_html_files(root)
    for p in htmls:
        print(p)
    print(f"Found {len(htmls)} HTML files")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    root = args.path or os.getcwd()
    q = args.query
    if not q:
        print("Please provide --query")
        return 2
    htmls = find_html_files(root)
    matches = []
    for p in htmls:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, start=1):
                    if q in line:
                        matches.append({"path": p, "line": i, "snippet": line.strip()})
        except OSError:
            continue
    for m in matches:
        print(f"{m['path']}:{m['line']}: {m['snippet']}")
    print(f"Matches: {len(matches)}")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    port = args.port
    directory = args.path or os.getcwd()
    os.chdir(directory)
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), Handler) as httpd:
        print(f"Serving {directory} at http://localhost:{port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Stopping server")
    return 0


def create_github_issue(repo: str, title: str, body: str, token: str) -> Tuple[bool, str]:
    url = f"https://api.github.com/repos/{repo}/issues"
    data = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            resp_data = json.load(resp)
            return True, resp_data.get("html_url", "")
    except urllib.error.HTTPError as e:
        try:
            msg = e.read().decode()
        except Exception:
            msg = str(e)
        return False, msg
    except Exception as e:
        return False, str(e)


def cmd_create_issue(args: argparse.Namespace) -> int:
    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("No GitHub token found. Set GITHUB_TOKEN env or pass --token")
        return 2
    repo = args.repo
    if not repo or "/" not in repo:
        print("Please provide --repo owner/name (e.g. pypa-app/pypa-web)")
        return 2
    # reuse report generation to build a body
    root = args.path or os.getcwd()
    htmls = find_html_files(root)
    sizes = file_sizes(htmls)
    total_size = sum(s for _, s in sizes)
    body = f"Repository report for {os.path.abspath(root)}\n\nFound {len(htmls)} HTML files, total size {total_size} bytes. Top files:\n"
    for p, s in sorted(sizes, key=lambda x: x[1], reverse=True)[:args.top]:
        body += f"- {p}: {s} bytes\n"
    ok, res = create_github_issue(repo, args.title or "Repository report", body, token)
    if ok:
        print(f"Issue created: {res}")
        return 0
    else:
        print(f"Failed to create issue: {res}")
        return 1


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="repo_manager.py", description="Small repo management helpers")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("report", help="Scan HTML files and write a JSON report")
    r.add_argument("--path", help="Root path to scan")
    r.add_argument("--outdir", default="reports", help="Directory to write the report")
    r.add_argument("--outfile", default="repo_report.json", help="Report filename")
    r.add_argument("--top", type=int, default=10, help="How many top largest files to include")
    r.set_defaults(func=cmd_report)

    l = sub.add_parser("list", help="List HTML files")
    l.add_argument("--path", help="Root path to scan")
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("search", help="Search inside HTML files")
    s.add_argument("--path", help="Root path to scan")
    s.add_argument("--query", required=True, help="Query string to search for")
    s.set_defaults(func=cmd_search)

    pr = sub.add_parser("preview", help="Start a simple HTTP server to preview files")
    pr.add_argument("--path", help="Root path to serve")
    pr.add_argument("--port", type=int, default=8000, help="Port to serve on")
    pr.set_defaults(func=cmd_preview)

    ci = sub.add_parser("create-issue", help="Create a GitHub issue with repo report")
    ci.add_argument("--path", help="Root path to scan")
    ci.add_argument("--repo", required=True, help="Target repository owner/name (e.g. pypa-app/pypa-web)")
    ci.add_argument("--title", help="Issue title")
    ci.add_argument("--token", help="GitHub token (or set GITHUB_TOKEN env)")
    ci.add_argument("--top", type=int, default=10, help="Top files to include in the issue body")
    ci.set_defaults(func=cmd_create_issue)

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 2
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

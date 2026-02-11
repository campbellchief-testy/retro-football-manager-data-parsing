#!/usr/bin/env python3
"""
review.py — minimal PR code review bot

Env vars expected (GitHub Actions friendly):
  - OPENAI_API_KEY (required)
  - GITHUB_TOKEN (required)
  - GITHUB_REPOSITORY (required)  e.g. "owner/repo"
  - GITHUB_PR_ID (required)       e.g. "123"
Optional:
  - OPENAI_MODEL (default: "gpt-4o-mini")
  - OPENAI_TEMPERATURE (default: "0.2")
  - OPENAI_MAX_TOKENS (default: "1200")
  - MODE (default: "patch")       "patch" or "files"
  - LANGUAGE (default: "en")
  - CUSTOM_PROMPT (default: "")
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from openai import OpenAI


# ----------------------------
# Config / helpers
# ----------------------------

@dataclass(frozen=True)
class Config:
    openai_api_key: str
    github_token: str
    repo: str
    pr_number: int
    model: str
    temperature: float
    max_tokens: int
    mode: str
    language: str
    custom_prompt: str

def getenv_required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

def getenv_default(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default

def clamp_text(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n\n[...truncated...]\n"

def gh_headers(token: str, accept: str = "application/vnd.github+json") -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "review-bot",
    }

def gh_api_url(repo: str, path: str) -> str:
    return f"https://api.github.com/repos/{repo}{path}"

def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# ----------------------------
# GitHub: fetch PR data
# ----------------------------

def fetch_pr_diff(cfg: Config) -> str:
    url = gh_api_url(cfg.repo, f"/pulls/{cfg.pr_number}")
    r = requests.get(url, headers=gh_headers(cfg.github_token, accept="application/vnd.github.v3.diff"), timeout=60)
    if r.status_code >= 300:
        die(f"Failed to fetch PR diff: {r.status_code} {r.text}")
    return r.text

def fetch_pr_files(cfg: Config, max_files: int = 50) -> List[Dict[str, Any]]:
    url = gh_api_url(cfg.repo, f"/pulls/{cfg.pr_number}/files?per_page=100")
    r = requests.get(url, headers=gh_headers(cfg.github_token), timeout=60)
    if r.status_code >= 300:
        die(f"Failed to fetch PR files: {r.status_code} {r.text}")
    files = r.json()
    if not isinstance(files, list):
        die(f"Unexpected files payload: {type(files)}")
    return files[:max_files]

def build_files_input(files: List[Dict[str, Any]], max_total_chars: int = 120_000) -> str:
    """
    Build a compact representation: filename + status + short patch (if present).
    """
    chunks: List[str] = []
    for f in files:
        filename = f.get("filename", "<unknown>")
        status = f.get("status", "<unknown>")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        patch = f.get("patch") or ""
        patch = clamp_text(patch, 6000)  # per-file patch clamp
        chunks.append(
            f"FILE: {filename}\nSTATUS: {status} (+{additions}/-{deletions})\nPATCH:\n{patch}\n"
        )
    joined = "\n---\n".join(chunks)
    return clamp_text(joined, max_total_chars)


# ----------------------------
# OpenAI: generate review
# ----------------------------

def build_instructions(cfg: Config) -> str:
    base = {
        "en": (
            "You are a senior staff software engineer performing a pull request review. "
            "Be precise, pragmatic, and helpful. Focus on correctness, security, performance, maintainability, and tests. "
            "If you suggest code changes, show small targeted diffs/snippets. "
            "If the change looks fine, say so and still point out any small improvements."
        )
    }.get(cfg.language.lower(), None)

    if not base:
        base = (
            "You are a senior staff software engineer performing a pull request review. "
            "Be precise, pragmatic, and helpful."
        )

    if cfg.custom_prompt.strip():
        base += "\n\nExtra reviewer guidance:\n" + cfg.custom_prompt.strip()

    return base

def call_openai_review(cfg: Config, pr_context: str) -> str:
    client = OpenAI(api_key=cfg.openai_api_key)

    # Keep the prompt bounded to avoid gigantic costs / token overflows.
    pr_context = clamp_text(pr_context, 140_000)

    input_text = (
        "Review the following PR diff/context. Return markdown with sections:\n"
        "1) Summary\n2) High-impact issues (if any)\n3) Suggestions / nits\n4) Testing notes\n\n"
        f"PR CONTEXT:\n{pr_context}"
    )

    resp = client.responses.create(
        model=cfg.model,
        instructions=build_instructions(cfg),
        input=input_text,
        temperature=cfg.temperature,
        max_output_tokens=cfg.max_tokens,
    )

    # openai-python exposes output_text convenience.
    out = getattr(resp, "output_text", None)
    if not out:
        # Fallback: best-effort parse for older/odd responses
        try:
            out = json.dumps(resp.model_dump(), indent=2)
        except Exception:
            out = str(resp)

    return out.strip()


# ----------------------------
# GitHub: post comment
# ----------------------------

def post_pr_comment(cfg: Config, body: str) -> None:
    url = gh_api_url(cfg.repo, f"/issues/{cfg.pr_number}/comments")
    payload = {"body": body}
    r = requests.post(url, headers=gh_headers(cfg.github_token), json=payload, timeout=60)
    if r.status_code >= 300:
        die(f"Failed to post PR comment: {r.status_code} {r.text}")

def main() -> None:
    try:
        cfg = Config(
            openai_api_key=getenv_required("OPENAI_API_KEY"),
            github_token=getenv_required("GITHUB_TOKEN"),
            repo=getenv_required("GITHUB_REPOSITORY"),
            pr_number=int(getenv_required("GITHUB_PR_ID")),
            model=getenv_default("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=float(getenv_default("OPENAI_TEMPERATURE", "0.2")),
            max_tokens=int(getenv_default("OPENAI_MAX_TOKENS", "1200")),
            mode=getenv_default("MODE", "patch").lower(),
            language=getenv_default("LANGUAGE", "en"),
            custom_prompt=getenv_default("CUSTOM_PROMPT", ""),
        )
    except Exception as e:
        die(str(e))

    if cfg.mode not in {"patch", "files"}:
        die("MODE must be 'patch' or 'files'")

    if cfg.mode == "patch":
        pr_context = fetch_pr_diff(cfg)
    else:
        files = fetch_pr_files(cfg)
        pr_context = build_files_input(files)

    review_md = call_openai_review(cfg, pr_context)

    header = "## 🤖 Automated PR Review\n"
    footer = "\n\n---\n_If this looks wrong or incomplete, rerun with MODE=files or tighten CUSTOM_PROMPT._"
    body = header + review_md + footer

    # GitHub comment limit is large, but keep bounded anyway.
    body = clamp_text(body, 60_000)

    post_pr_comment(cfg, body)
    print("Posted PR review comment successfully.")

if __name__ == "__main__":
    main()
"""GitHub ingestion.

Every fact pulled from GitHub is returned as a Claim carrying a `GitHubField`
locator, so the provenance viewer can say "this sentence came from the README
of owner/repo" rather than just "from GitHub".

Caching is keyed on the repo's `pushed_at` timestamp, so a repo is only
re-fetched when it has actually changed. This matters: READMEs are the
single largest source of tokens in the pipeline.
"""
from __future__ import annotations

import base64
import json
import hashlib
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.models.claims import Claim, ClaimKind, Evidence, GitHubField

log = logging.getLogger(__name__)

API = "https://api.github.com"
README_CHAR_LIMIT = 6000

# Repos that are almost never worth showing on a portfolio.
BORING_NAMES = {"config", "dotfiles", "test", "demo", "hello-world", "practice",
                "assignments", "leetcode", "hackerrank", "playground"}

class GitHubError(RuntimeError):
    pass

class GitHubClient:
    def __init__(self, token: str | None = None, cache_dir: Path | None = None):
        self.token = (token if token is not None else settings.github_token).strip()
        self.cache_dir = cache_dir or settings.cache_path / "github"
        self.cache_dir.mkdir(parents = True, exist_ok = True)
        self.rate_limit_remaining: int | None = None

    # -- plumbing ----------------------------------------------------------

    @property
    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FolioProof/1.0",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _cache_file(self, key: str) -> Path:
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:20] + ".json")

    def _get(self, client: httpx.Client, path: str, cache_key: str | None = None) -> Any:
        if cache_key:
            cf = self._cache_file(cache_key)
            if cf.exists():
                return json.loads(cf.read_text(encoding = "utf-8"))

        resp = client.get(f"{API}{path}", headers = self._headers, timeout = 20.0)
        self.rate_limit_remaining = int(resp.headers.get("x-ratelimit-remaining", -1))

        if resp.status_code == 404:
            raise GitHubError(f"Not found: {path}")
        if resp.status_code == 403 and self.rate_limit_remaining == 0:
            raise GitHubError(
                "GitHub rate limit exhausted. Add a GITHUB_TOKEN to your .env "
                "(60 req/hour unauthenticated vs 5000 authenticated)."
            )
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub {resp.status_code} on {path}: {resp.text[:200]}")

        data = resp.json()
        if cache_key:
            self._cache_file(cache_key).write_text(
                json.dumps(data, ensure_ascii = False), encoding = "utf-8"
            )
        return data

    # -- fetching ----------------------------------------------------------

    def fetch_profile(self, username: str, max_repos: int = 12) -> dict[str, Any]:
        """Fetch user + their most substantial public repos (with READMEs)."""
        username = username.strip().lstrip("@")
        if not username:
            raise GitHubError("empty GitHub username")

        with httpx.Client(follow_redirects=True) as client:
            user = self._get(client, f"/users/{username}")

            repos: list[dict] = []
            page = 1
            while page <= 3:
                batch = self._get(
                    client, f"/users/{username}/repos?per_page=100&page={page}&sort=pushed"
                )
                if not batch:
                    break
                repos.extend(batch)
                if len(batch) < 100:
                    break
                page += 1

            own = [r for r in repos if not r.get("fork")]
            ranked = sorted(own, key = self._repo_score, reverse = True)[:max_repos]

            for repo in ranked:
                full = repo["full_name"]
                cache_key = f"{full}@{repo.get('pushed_at')}"
                try:
                    repo["_languages"] = self._get(
                        client, f"/repos/{full}/languages", cache_key = f"lang:{cache_key}"
                    )
                except GitHubError:
                    repo["_languages"] = {}
                try:
                    readme = self._get(
                        client, f"/repos/{full}/readme", cache_key=f"readme:{cache_key}"
                    )
                    content = base64.b64decode(readme.get("content", "")).decode(
                        "utf-8", errors = "replace"
                    )
                    repo["_readme"] = content[:README_CHAR_LIMIT]
                except (GitHubError, ValueError):
                    repo["_readme"] = ""

        return {"user": user, "repos": ranked, "all_repo_count": len(own)}

    @staticmethod
    def _repo_score(repo: dict) -> float:
        """Rank repos by how portfolio-worthy they look."""
        name = (repo.get("name") or "").lower()
        owner = ((repo.get("owner") or {}).get("login") or "").lower()
        score = 0.0
        # The `<username>/<username>` repo holds the GitHub profile README.
        # It is scaffolding, never a project.
        if owner and name == owner:
            return -100.0
        score += (repo.get("stargazers_count", 0) or 0) * 4.0
        score += (repo.get("forks_count", 0) or 0) * 2.0
        score += 3.0 if repo.get("description") else 0.0
        score += 2.0 if repo.get("homepage") else 0.0
        score += min((repo.get("size", 0) or 0) / 500.0, 4.0)
        score += 1.5 * len(repo.get("topics") or [])
        if name in BORING_NAMES or any(b in name for b in BORING_NAMES):
            score -= 6.0
        if repo.get("archived"):
            score -= 3.0
        return score

    # -- claim construction ------------------------------------------------

    def to_claims(self, payload: dict[str, Any]) -> list[Claim]:
        """Convert a fetched profile into evidence-bound Claims."""
        user = payload["user"]
        repos = payload["repos"]
        claims: list[Claim] = []
        login = user.get("login", "")

        def ev(field: str, text: str, repo: str | None = None, url: str | None = None) -> Evidence:
            return Evidence(
                source_id = "github",
                locator = GitHubField(repo = repo, field = field, url = url),
                raw_text = text,
            )

        if user.get("bio"):
            claims.append(Claim(
                kind = ClaimKind.SUMMARY,
                value = user["bio"].strip(),
                evidence = [ev("bio", user["bio"].strip(), url = user.get("html_url"))],
                attributes = {"origin": "github_bio"},
            ))

        if user.get("blog"):
            claims.append(Claim(
                kind = ClaimKind.CONTACT,
                value = user["blog"],
                attributes = {"type": "website"},
                evidence = [ev("blog", user["blog"], url = user.get("html_url"))],
            ))

        language_totals: dict[str, int] = {}

        for repo in repos:
            full = repo["full_name"]
            url = repo.get("html_url")
            desc = (repo.get("description") or "").strip()
            readme = (repo.get("_readme") or "").strip()

            # The evidence for a project is its description *and* its README --
            # both are what the rewriter is later allowed to draw from.
            evidence = []
            if desc:
                evidence.append(ev("description", desc, repo=full, url = url))
            if readme:
                evidence.append(ev("readme", readme[:2000], repo = full, url = url))
            if not evidence:
                evidence.append(ev("name", repo["name"], repo = full, url = url))

            langs = repo.get("_languages") or {}
            for lang, count in langs.items():
                language_totals[lang] = language_totals.get(lang, 0) + int(count)

            claims.append(Claim(
                kind = ClaimKind.PROJECT,
                value = repo["name"],
                attributes = {
                    "repo": full,
                    "url": url,
                    "homepage": repo.get("homepage") or None,
                    "description": desc,
                    "readme": readme,
                    "stars": repo.get("stargazers_count", 0),
                    "forks": repo.get("forks_count", 0),
                    "topics": repo.get("topics") or [],
                    "languages": list(langs.keys()),
                    "primary_language": repo.get("language"),
                    "pushed_at": repo.get("pushed_at"),
                },
                evidence = evidence,
            ))

        for lang, total in sorted(language_totals.items(), key = lambda kv: -kv[1]):
            claims.append(Claim(
                kind = ClaimKind.SKILL,
                value = lang,
                attributes = {"bytes": total, "origin": "github_languages"},
                evidence = [ev("language", f"{lang} used across {login}'s repositories")],
            ))

        return claims

    def top_repositories(self, payload: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
        """The N most portfolio-worthy repos, already ranked by `_repo_score`.

        `fetch_profile` sorts by that score, so this is just the head of the
        list reshaped for rendering.
        """
        out: list[dict[str, Any]] = []
        for repo in payload.get("repos", [])[:limit]:
            langs = repo.get("_languages") or {}
            total = sum(langs.values()) or 1
            out.append({
                "name": repo["name"],
                "full_name": repo["full_name"],
                "description": (repo.get("description") or "").strip(),
                "url": repo.get("html_url"),
                "homepage": repo.get("homepage") or None,
                "stars": repo.get("stargazers_count", 0) or 0,
                "forks": repo.get("forks_count", 0) or 0,
                "topics": (repo.get("topics") or [])[:5],
                "primary_language": repo.get("language"),
                "languages": [
                    {"name": k, "percent": round(v * 100 / total, 1)}
                    for k, v in sorted(langs.items(), key=lambda kv: -kv[1])[:3]
                ],
                "updated": (repo.get("pushed_at") or "")[:10],
            })
        return out

    def analytics(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Aggregate numbers for the GitHub Analytics section of the portfolio."""
        user, repos = payload["user"], payload["repos"]
        totals: dict[str, int] = {}
        for repo in repos:
            for lang, count in (repo.get("_languages") or {}).items():
                totals[lang] = totals.get(lang, 0) + int(count)
        grand = sum(totals.values()) or 1

        return {
            "login": user.get("login"),
            "avatar_url": user.get("avatar_url"),
            "profile_url": user.get("html_url"),
            "public_repos": user.get("public_repos", 0),
            "followers": user.get("followers", 0),
            "analysed_repos": len(repos),
            "total_stars": sum(r.get("stargazers_count", 0) or 0 for r in repos),
            "total_forks": sum(r.get("forks_count", 0) or 0 for r in repos),
            "languages": [
                {"name": k, "bytes": v, "percent": round(v * 100 / grand, 1)}
                for k, v in sorted(totals.items(), key=lambda kv: -kv[1])[:8]
            ],
        }
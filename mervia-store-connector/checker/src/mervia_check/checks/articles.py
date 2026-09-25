"""Item 5: the article lifecycle — create hidden, preview, publish, edit, hide, delete.

Everything created carries the tags "mervia" and "mervia-conformance" and a run-unique title and
slug. Whatever happens (a failed step, a timed-out POST, Ctrl-C or SIGTERM), a `finally` sweeps
the conformance tag for this run's article, hides and deletes it, and confirms with a GET that
answers 404; a failed cleanup is a failing result and is printed to stderr.
"""

from __future__ import annotations

from typing import Any

import httpx

from .. import contract
from ..report import Result, check, fail, ok, skip, warn
from . import (
    CONFORMANCE_TAG,
    Context,
    Sitemap,
    body_json,
    describe,
    fetch,
    origin,
    retry,
    seg,
    sid,
    sitemap_urls,
    text_in,
    url_in,
)

ITEM = 5
ARTICLE = contract.component("Article")
LIST_SCHEMA = contract.response_schema("/articles")
MAX_LIST_PAGES = 5


class _Abort(Exception):
    """A step failed that later steps depend on."""


class _Lifecycle:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.results: list[Result] = []
        self.id: str | None = None
        self.deleted = False
        self.create_sent = False
        self.title = f"Mervia conformance check {ctx.run_id}"
        self.slug = f"mervia-conformance-{ctx.run_id}"
        self.marker = f"mervia-conformance-marker-{ctx.run_id}"
        self.body = (
            "<p>Created by mervia-check to test the Mervia articles API; it is removed automatically.</p>"
            f'<p data-mervia-conformance="1">{self.marker}</p>'
        )
        self.url = ""
        self.base = ""
        self.preview_url: str | None = None
        self.hidden_sitemap_index: int | None = None

    def add(self, result: Result) -> Result:
        self.results.append(result)
        return result

    def call(self, name: str, method: str, path: str, json: Any = None, params: dict | None = None) -> httpx.Response:
        try:
            return self.ctx.client.api(method, path, json=json, params=params)
        except httpx.HTTPError as exc:
            self.add(fail(ITEM, name, f"request failed: {exc}", exc))
            raise _Abort from exc

    def article(self, name: str, resp: httpx.Response, statuses: tuple[int, ...] = (200,)) -> dict:
        """The response's Article, or a failing result and abort."""
        if resp.status_code not in statuses:
            self.add(fail(ITEM, name, f"expected {' or '.join(map(str, statuses))}, got {resp.status_code}", resp))
            raise _Abort
        data = body_json(resp)
        errors = contract.validate(data, ARTICLE)
        if errors:
            self.add(fail(ITEM, name, "; ".join(errors), resp))
            raise _Abort
        return data

    def shows_marker(self, source: httpx.Response | httpx.HTTPError) -> bool:
        return (
            isinstance(source, httpx.Response)
            and source.status_code == 200
            and (self.marker in source.text or text_in(source.text, self.title))
        )

    # -- steps ------------------------------------------------------------------------------

    def create(self) -> str:
        payload = {
            "type": "post",
            "title": self.title,
            "slug": self.slug,
            "excerpt": "mervia-check conformance article",
            "body_html": self.body,
            "tags": ["mervia", CONFORMANCE_TAG],
            "status": "hidden",
        }
        self.ctx.announce_writes()
        self.create_sent = True
        resp = self.call("5.articles.create", "POST", "/articles", payload)
        created = body_json(resp)
        if isinstance(created, dict) and created.get("id") is not None:
            self.id = sid(created["id"])  # known before validation, so cleanup can find it
        art = self.article("5.articles.create", resp, (200, 201))
        self.id = sid(art["id"])
        self.add(ok(ITEM, "5.articles.create", f"article {self.id}"))
        problems = [f"status is {art.get('status')!r}"] if art.get("status") != "hidden" else []
        problems += [f"{f} missing" for f in ("url", "preview_url", "content_digest") if not art.get(f)]
        self.add(
            check(
                ITEM,
                "5.articles.create_hidden",
                not problems,
                "a created article must be hidden with url, preview_url and content_digest: " + ", ".join(problems),
                resp,
            )
        )
        self.url = str(art["url"])
        self.preview_url = art.get("preview_url")
        self.base = (self.ctx.opts.public_base_url or origin(self.url)).rstrip("/")
        return str(art["content_digest"])

    def get(self, digest: str) -> None:
        resp = self.call("5.articles.get", "GET", f"/articles/{seg(self.id)}")
        art = self.article("5.articles.get", resp)
        want = (("id", self.id), ("title", self.title), ("status", "hidden"), ("content_digest", digest))
        diffs = [f for f, value in want if sid(art.get(f)) != value]
        self.add(check(ITEM, "5.articles.get", not diffs, f"GET /articles/{{id}} differs on {diffs}", resp))

    def tagged(self) -> tuple[list[dict], httpx.Response | None, str | None]:
        """Every article GET /articles?tag=mervia-conformance&status=all returns (up to 5 pages)."""
        params: dict[str, Any] = {"tag": CONFORMANCE_TAG, "status": "all"}
        found: list[dict] = []
        resp = None
        for _ in range(MAX_LIST_PAGES):
            resp = self.ctx.client.api("GET", "/articles", params=params)
            data = body_json(resp)
            errors = contract.validate(data, LIST_SCHEMA) if resp.status_code == 200 else [f"HTTP {resp.status_code}"]
            if errors:
                return found, resp, "; ".join(errors)
            found += [a for a in data["items"] if isinstance(a, dict)]
            if not data["next_cursor"]:
                break
            params["cursor"] = data["next_cursor"]
        return found, resp, None

    def listed(self) -> None:
        name = "5.articles.list_includes_hidden"
        try:
            found, resp, error = self.tagged()
        except httpx.HTTPError as exc:
            self.add(fail(ITEM, name, f"request failed: {exc}", exc))
            return
        if error:
            self.add(fail(ITEM, name, error, resp))
            return
        self.add(
            check(
                ITEM,
                name,
                any(sid(a.get("id")) == self.id for a in found),
                f"GET /articles?tag={CONFORMANCE_TAG}&status=all does not list the hidden article",
                resp,
            )
        )
        strays = [sid(a.get("id")) for a in found if CONFORMANCE_TAG not in (a.get("tags") or [])]
        self.add(
            check(
                ITEM,
                "5.articles.tag_filter",
                not strays,
                f"tag={CONFORMANCE_TAG} returned articles without that tag: {strays[:10]}. Mervia finds and cleans "
                "up its own posts with this filter, so it must match exactly",
                resp,
            )
        )

    def not_public(self, name: str, *, wait: bool) -> None:
        def attempt() -> httpx.Response | httpx.HTTPError:
            return fetch(self.ctx, self.url)

        source = retry(self.ctx, attempt, lambda r: not self.shows_marker(r)) if wait else attempt()
        self.add(
            check(
                ITEM,
                name,
                not self.shows_marker(source),
                f"{self.url} serves the hidden article to a request without a key",
                source,
                ok_detail=describe(source),
            )
        )

    def sitemap(self, name: str, *, present: bool, wait: bool) -> Result:
        def attempt() -> Sitemap:
            return sitemap_urls(self.ctx, self.base)

        def done(sm: Sitemap) -> bool:
            return sm.urls is not None and url_in(self.url, sm.urls) == present

        sm = retry(self.ctx, attempt, done) if wait else attempt()
        where = f"{self.base}/sitemap.xml"
        partial = f"; {sm.child_failures} child sitemap(s) could not be read" if sm.child_failures else ""
        if sm.urls is None:
            return self.add(warn(ITEM, name, f"no sitemap could be read at {where} ({describe(sm.source)})", sm.source))
        listed = url_in(self.url, sm.urls)
        if listed and not present:
            if wait:
                return self.add(
                    warn(
                        ITEM,
                        name,
                        f"{self.url} is still in the sitemap after {self.ctx.retries} retries; "
                        f"the sitemap may be cached, check it by hand{partial}",
                        sm.source,
                    )
                )
            return self.add(fail(ITEM, name, f"the hidden article {self.url} is listed in the sitemap", sm.source))
        if listed or not present:
            return self.add(warn(ITEM, name, partial.lstrip("; "), sm.source) if partial else ok(ITEM, name))
        return self.add(
            warn(
                ITEM,
                name,
                f"{self.url} is not in the sitemap after {self.ctx.retries} retries; "
                f"the sitemap may be cached, check it by hand{partial}",
                sm.source,
            )
        )

    def preview(self) -> None:
        name = "5.articles.preview"
        if not self.preview_url:
            self.add(fail(ITEM, name, "the article has no preview_url"))
            return
        source = fetch(self.ctx, self.preview_url, auth=True)
        ok_page = isinstance(source, httpx.Response) and source.status_code == 200 and text_in(source.text, self.title)
        self.add(
            check(
                ITEM,
                name,
                ok_page,
                f"preview_url with the API key should render the title ({describe(source)})",
                source,
            )
        )
        keyless = fetch(self.ctx, self.preview_url)
        self.add(
            check(
                ITEM,
                "5.articles.preview_requires_key",
                not self.shows_marker(keyless),
                f"preview_url renders the hidden article without the API key ({describe(keyless)})",
                keyless,
                ok_detail=describe(keyless),
            )
        )

    def patch(self, name: str, changes: dict) -> tuple[dict, httpx.Response]:
        resp = self.call(name, "PATCH", f"/articles/{seg(self.id)}", changes)
        return self.article(name, resp), resp

    def delete(self) -> None:
        resp = self.call("5.articles.delete", "DELETE", f"/articles/{seg(self.id)}")
        ok_status = resp.status_code in (200, 204)
        self.add(check(ITEM, "5.articles.delete", ok_status, f"expected 204 or 200, got {resp.status_code}", resp))
        gone = self.call("5.articles.gone", "GET", f"/articles/{seg(self.id)}")
        self.deleted = gone.status_code == 404  # otherwise the finally-cleanup tries again
        self.add(
            check(
                ITEM,
                "5.articles.gone",
                self.deleted,
                f"a deleted article should answer 404, got {gone.status_code}",
                gone,
            )
        )

    def settle_hidden_sitemap(self, published: Result) -> None:
        """An absent hidden article proves little unless the sitemap was later seen to be fresh."""
        i = self.hidden_sitemap_index
        if i is None or self.results[i].status != "pass" or self.results[i].warning:
            return
        if published.status == "pass" and not published.warning:
            return  # the sitemap listed the article once published, so it is fresh
        self.results[i] = warn(
            ITEM,
            "5.articles.hidden_not_in_sitemap",
            "the hidden article was absent, but the sitemap never listed it once published either, "
            "so it may be stale; check it by hand",
        )

    def run(self) -> None:
        digest = self.create()
        self.get(digest)
        self.listed()
        self.not_public("5.articles.hidden_not_public", wait=False)
        self.sitemap("5.articles.hidden_not_in_sitemap", present=False, wait=False)
        self.hidden_sitemap_index = len(self.results) - 1
        self.preview()

        art, resp = self.patch("5.articles.publish", {"status": "published"})
        live = art.get("status") == "published" and bool(art.get("published_at"))
        self.add(
            check(
                ITEM,
                "5.articles.publish",
                live,
                f"after PATCH status=published: status {art.get('status')!r}, published_at {art.get('published_at')!r}",
                resp,
            )
        )
        self.add(
            check(
                ITEM,
                "5.articles.digest_stable_on_publish",
                art.get("content_digest") == digest,
                f"content_digest changed on publish ({digest!r} -> {art.get('content_digest')!r}) "
                "although body_html did not",
                resp,
            )
        )
        source = retry(self.ctx, lambda: fetch(self.ctx, self.url), self.shows_marker)
        self.add(
            check(
                ITEM,
                "5.articles.published_public",
                self.shows_marker(source),
                f"{self.url} does not serve the published article ({describe(source)})",
                source,
            )
        )
        self.settle_hidden_sitemap(self.sitemap("5.articles.published_in_sitemap", present=True, wait=True))

        art, resp = self.patch("5.articles.digest_changes_on_edit", {"body_html": self.body + "<p>edited</p>"})
        self.add(
            check(
                ITEM,
                "5.articles.digest_changes_on_edit",
                art.get("content_digest") != digest,
                "content_digest did not change when body_html changed",
                resp,
            )
        )

        art, resp = self.patch("5.articles.unpublish", {"status": "hidden"})
        self.add(
            check(
                ITEM,
                "5.articles.unpublish",
                art.get("status") == "hidden",
                f"after PATCH status=hidden: status {art.get('status')!r}",
                resp,
            )
        )
        self.not_public("5.articles.unpublished_not_public", wait=True)
        self.sitemap("5.articles.unpublished_not_in_sitemap", present=False, wait=True)
        self.delete()

    # -- cleanup ----------------------------------------------------------------------------

    def remove(self, article_id: str) -> str | None:
        """Hide, delete, confirm 404. None on success, else what went wrong."""
        problems: list[str] = []
        for method, body in (("PATCH", {"status": "hidden"}), ("DELETE", None)):
            try:
                resp = self.ctx.client.api(method, f"/articles/{seg(article_id)}", json=body)
                if resp.status_code not in (200, 204, 404):
                    problems.append(f"{method} answered {resp.status_code}")
            except httpx.HTTPError as exc:
                problems.append(f"{method} failed: {exc}")
        try:
            if self.ctx.client.api("GET", f"/articles/{seg(article_id)}").status_code == 404:
                return None
        except httpx.HTTPError as exc:
            problems.append(f"GET failed: {exc}")
        return "; ".join(problems) or "DELETE answered success but GET still finds the article"

    def cleanup(self) -> Result | None:
        """Remove this run's article, found by id or, after a lost POST response, by the tag sweep."""
        if not self.create_sent:
            return None
        targets = {self.id} if self.id is not None and not self.deleted else set()
        sweep_error = None
        try:
            found, resp, error = self.tagged()
            sweep_error = error and f"the tag sweep failed: {error}"
        except httpx.HTTPError as exc:
            found, sweep_error = [], f"the tag sweep failed: {exc}"
        targets |= {
            sid(a.get("id"))
            for a in found
            if (a.get("slug") == self.slug or a.get("title") == self.title) and a.get("id") is not None
        }
        if self.deleted:
            targets.discard(self.id)
        problems = [f"article {t}: {p}" for t in sorted(t for t in targets if t) if (p := self.remove(t))]
        if sweep_error and self.id is None:
            problems.append(f"{sweep_error}; the POST may still have created an article titled {self.title!r}")
        if problems:
            self.ctx.say(
                f"CLEANUP FAILED: {'; '.join(problems)}. Look for tag {CONFORMANCE_TAG} and delete it by hand."
            )
            return fail(ITEM, "5.articles.cleanup", "; ".join(problems) + ". Delete it by hand.")
        if not targets:
            return None if self.deleted else ok(ITEM, "5.articles.cleanup", "nothing was left behind")
        return ok(ITEM, "5.articles.cleanup", f"removed {', '.join(sorted(targets))}")


def run(ctx: Context) -> list[Result]:
    life = _Lifecycle(ctx)
    try:
        life.run()
    except _Abort:
        life.add(skip(ITEM, "5.articles.remaining", "remaining lifecycle steps skipped after the failure above"))
    finally:
        cleanup = life.cleanup()
        if cleanup is not None:
            life.add(cleanup)
    return life.results

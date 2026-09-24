"""The `mervia-check` command."""

from __future__ import annotations

import signal
import sys
from pathlib import Path
from types import FrameType

import click

from . import __version__
from .checks import Options
from .listen import parse_listen
from .redact import Redactor, secret_problem
from .report import exit_code, render_json, render_text, summary
from .runner import RunError, run


def _on_sigterm(_signum: int, _frame: FrameType | None) -> None:
    """`docker stop` sends SIGTERM: unwind like Ctrl-C so every cleanup `finally` runs."""
    raise KeyboardInterrupt


def _secret(_ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Reject whitespace and control characters without ever echoing the value."""
    if value is not None and (problem := secret_problem(value)):
        raise click.BadParameter(f"the value {problem}", param_hint=f"--{(param.name or '').replace('_', '-')}")
    return value


def _items(_ctx: click.Context, _param: click.Parameter, value: str | None) -> list[int] | None:
    if not value:
        return None
    try:
        items = sorted({int(v) for v in value.split(",") if v.strip()})
    except ValueError as exc:
        raise click.BadParameter("a comma-separated list of item numbers, e.g. 1,2,7") from exc
    unknown = [i for i in items if not 1 <= i <= 11]
    if unknown:
        raise click.BadParameter(f"unknown item(s) {unknown}; items are numbered 1 to 11")
    return items


def _listen(_ctx: click.Context, _param: click.Parameter, value: str | None) -> str | None:
    if value is not None:
        try:
            parse_listen(value)
        except ValueError as exc:
            raise click.BadParameter(str(exc)) from exc
    return value


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="mervia-check")
@click.option(
    "--base-url", required=True, help="The store's connector base URL, e.g. https://staging.example.com/api/mervia/v1."
)
@click.option(
    "--api-key",
    required=True,
    envvar="MERVIA_CHECK_API_KEY",
    callback=_secret,
    help="The API key the store issued to Mervia (or MERVIA_CHECK_API_KEY). Never printed.",
)
@click.option("--store-id", help="Expected store_id: compared with GET /store, the tag's data-store and webhooks.")
@click.option("--items", callback=_items, help="Comma-separated item numbers to check, e.g. 1,2,7. Default: all.")
@click.option("--public-base-url", help="Public origin of the storefront, e.g. https://staging.example.com.")
@click.option("--product-id", help="Product to use for the page-content checks (default: the first listed).")
@click.option(
    "--webhook-secret",
    envvar="MERVIA_CHECK_WEBHOOK_SECRET",
    callback=_secret,
    help="Shared webhook secret (or MERVIA_CHECK_WEBHOOK_SECRET); enables the arranged webhook checks. Never printed.",
)
@click.option(
    "--webhook-listen",
    default="0.0.0.0:8788",
    show_default=True,
    callback=_listen,
    help="HOST:PORT for the local webhook receiver.",
)
@click.option(
    "--webhook-timeout", default=300.0, show_default=True, type=float, help="Seconds to wait for a webhook delivery."
)
@click.option(
    "--include-stub-listen",
    callback=_listen,
    help="HOST:PORT for the local include stub; only for a store that declares content_pull (pull alternative).",
)
@click.option(
    "--content-mode",
    type=click.Choice(["auto", "pull", "push"]),
    default="auto",
    show_default=True,
    help="Which item 6 delivery to test; auto follows the declared capability (content_push, or content_pull).",
)
@click.option("--report", "report_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option(
    "--output", type=click.Path(dir_okay=False, path_type=Path), help="Write the report here instead of stdout."
)
@click.option("--timeout", default=10.0, show_default=True, type=float, help="Per-request timeout in seconds.")
@click.option("--insecure", is_flag=True, help="Do not verify TLS certificates (self-signed staging only).")
@click.option(
    "--allow-writes",
    is_flag=True,
    help="Run items 5 and 6, which create and delete content on the store. STAGING stores only.",
)
@click.option("--allow-http", is_flag=True, help="Accept an http:// base URL (local test stores only).")
@click.option(
    "--public-auth",
    envvar="MERVIA_CHECK_PUBLIC_AUTH",
    callback=_secret,
    help="USER:PASSWORD for public pages behind HTTP basic auth (or MERVIA_CHECK_PUBLIC_AUTH). Never printed.",
)
@click.pass_context
def main(ctx: click.Context, report_format: str, output: Path | None, **kwargs: object) -> None:
    """Check a staging store's implementation of the Mervia Store Connector contract."""
    opts = Options(**kwargs)  # type: ignore[arg-type]
    redact = Redactor(opts.api_key, opts.webhook_secret, opts.public_auth)
    hooks = ctx.obj or {}  # tests inject a transport and a no-op sleep here
    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except ValueError:
        pass  # not the main thread (embedded use); Ctrl-C handling is unchanged
    try:
        results, meta = run(opts, **hooks)
    except RunError as exc:
        click.echo(redact(f"error: {exc}"), err=True)
        sys.exit(2)
    except KeyboardInterrupt:
        click.echo("interrupted: cleanup was attempted; see the messages above", err=True)
        sys.exit(130)
    text = redact(render_json(results, meta) if report_format == "json" else render_text(results, meta))
    if output:
        output.write_text(text, encoding="utf-8")
        s = summary(results)
        click.echo(f"report written to {output}: {s['pass']} passed, {s['fail']} failed, {s['skip']} skipped", err=True)
    else:
        click.echo(text, nl=False)
    sys.exit(exit_code(results))

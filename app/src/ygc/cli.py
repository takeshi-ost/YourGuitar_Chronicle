from __future__ import annotations

import html
import json
import logging
import re

import typer
from rich.console import Console
from rich.table import Table

from ygc import config
from ygc.collectors.reverb import (
    ReverbAPICollector,
)
from ygc.db.repository import Repository
from ygc.db.crawl_archive import archive_unregistered_crawl
from ygc.platform_boundaries import CrawlStep, LocalCrawlRunner, local_repository
from ygc.extractors.serial import (
    extract_serial_candidates,
)
from ygc.reverb_adapter import (
    classify_vintage_listing,
    to_listing_claim_data,
    to_provenance_observation,
)


app = typer.Typer(
    help=(
        "Your Guitar Chronicle "
        "- Phase 1"
    )
)

console = Console()


def repo() -> Repository:
    return local_repository(config.DB_PATH)


def setup_logging() -> None:
    config.LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s "
            "%(message)s"
        ),
        handlers=[
            logging.FileHandler(
                config.LOG_DIR
                / "ygc.log",
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
    )


def _strip_html(
    value: str | None,
) -> str:
    if not value:
        return ""

    text = html.unescape(
        str(value)
    )

    text = re.sub(
        r"<br\s*/?>",
        "\n",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"</p\s*>",
        "\n",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = text.replace(
        "\xa0",
        " ",
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n\s*\n+",
        "\n",
        text,
    )

    return text.strip()


def _serial_source_text(
    item: dict,
) -> str:
    title = str(
        item.get(
            "title"
        )
        or ""
    )

    description = _strip_html(
        item.get(
            "description"
        )
    )

    return "\n".join(
        value
        for value in (
            title,
            description,
        )
        if value
    )


def _short_context(
    value: str,
    length: int = 180,
) -> str:
    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    if len(value) <= length:
        return value

    return (
        value[: length - 3]
        + "..."
    )


@app.command(
    "init-db"
)
def init_db():
    repository = repo()

    repository.init_db()

    console.print(
        "[green]"
        "Initialized"
        "[/green] "
        f"{config.DB_PATH}"
    )


@app.command("crawl-step")
def crawl_step(category: str = typer.Option(..., help="all, electric or acoustic"),
               year_min: int = typer.Option(...),
               year_max: int = typer.Option(...)) -> None:
    """One synchronous, resumable crawl step; suitable as a future Run Job entrypoint."""
    step = CrawlStep(category, year_min, year_max)
    if not config.REVERB_API_TOKEN:
        raise typer.BadParameter("REVERB_API_TOKEN must be set for a crawl job")
    repository = repo()
    repository.init_db()
    if not repository.claim_architecture_status()["ready"]:
        raise typer.BadParameter("Run Claim migration before crawling")
    with ReverbAPICollector(token=config.REVERB_API_TOKEN,
                            api_base=config.REVERB_API_BASE,
                            timeout=config.REQUEST_TIMEOUT, delay=0.5,
                            max_workers=1) as collector:
        result = LocalCrawlRunner().run(step, repository, collector)
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command(
    "claim-status"
)
def claim_status():
    repository = repo()
    repository.init_db()
    status = repository.claim_architecture_status()
    console.print_json(
        json.dumps(
            status,
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command(
    "migrate-claims"
)
def migrate_claims():
    repository = repo()
    repository.init_db()
    before = repository.claim_architecture_status()
    result = repository.migrate_legacy_observations_to_claims()
    after = repository.claim_architecture_status()
    console.print_json(
        json.dumps(
            {
                "before": before,
                "migration": result,
                "after": after,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("migrate-claim-evidence")
def migrate_claim_evidence() -> None:
    """Copy linked legacy marketplace observations to Claim Evidence."""
    repository = repo()
    repository.init_db()
    result = {
        'marketplace': repository.backfill_claim_source_evidence(),
        'acquisition_dates': repository.backfill_acquisition_date_evidence(),
    }
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command("audit-observation-migration")
def audit_observation_migration(
    sample_limit: int = typer.Option(20, min=0, max=100),
) -> None:
    """Read-only audit of Observation parity and missing Claim Evidence."""
    repository = repo()
    try:
        result = repository.audit_observation_migration(sample_limit=sample_limit)
    except FileNotFoundError as exc:
        raise typer.BadParameter(f'Database does not exist: {exc}') from exc
    console.print_json(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("archive-unregistered-crawl")
def archive_unregistered_crawl_command() -> None:
    """Preserve complete unregistered crawl rows without deleting originals."""
    try:
        result = archive_unregistered_crawl(repo().db_path)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print_json(json.dumps(result, ensure_ascii=False))


@app.command(
    "reverb-probe"
)
def reverb_probe(
    query: str = typer.Option(
        "Fender Stratocaster",
        help="Reverb search query",
    ),
):
    setup_logging()

    with ReverbAPICollector(
        token=(
            config.REVERB_API_TOKEN
        ),
        api_base=(
            config.REVERB_API_BASE
        ),
        timeout=(
            config.REQUEST_TIMEOUT
        ),
        delay=0.15,
        max_workers=6,
    ) as collector:
        payload = (
            collector.probe(
                query
            )
        )

    listings = (
        payload.get(
            "listings"
        )
        or payload.get(
            "_embedded",
            {},
        ).get(
            "listings",
            [],
        )
        or []
    )

    summary = {
        "keys": sorted(
            payload.keys()
        ),
        "listing_count_in_page": (
            len(listings)
        ),
        "links": payload.get(
            "_links",
            {},
        ),
    }

    console.print_json(
        json.dumps(
            summary,
            ensure_ascii=False,
            default=str,
        )
    )


@app.command(
    "reverb-sample"
)
def reverb_sample(
    query: str = typer.Option(
        "Fender Stratocaster",
        help="Reverb search query",
    ),
):
    setup_logging()

    with ReverbAPICollector(
        token=(
            config.REVERB_API_TOKEN
        ),
        api_base=(
            config.REVERB_API_BASE
        ),
        timeout=(
            config.REQUEST_TIMEOUT
        ),
        delay=0.15,
        max_workers=6,
    ) as collector:
        summaries = list(
            collector
            .iter_listing_summaries(
                query=query,
                limit=1,
            )
        )

        if not summaries:
            console.print(
                "[yellow]"
                "No listings returned."
                "[/yellow]"
            )
            return

        detail = (
            collector
            .fetch_listing_detail(
                summaries[0]
            )
        )

        console.print_json(
            json.dumps(
                detail,
                ensure_ascii=False,
                default=str,
                indent=2,
            )
        )


@app.command(
    "crawl"
)
def crawl(
    query: str = typer.Option(
        "Fender Stratocaster",
        help="Reverb search query",
    ),
    limit: int = typer.Option(
        100,
        min=1,
        max=5000,
        help=(
            "Maximum number of "
            "listing summaries"
        ),
    ),
    workers: int = typer.Option(
        6,
        min=1,
        max=12,
        help=(
            "Parallel detail requests"
        ),
    ),
):
    """
    Reverb crawl。

    一覧段階で
    vintage / modern /
    unknown / non_target
    を分類する。

    vintage と unknown だけ
    詳細APIへ送る。
    """

    setup_logging()

    repository = repo()
    repository.init_db()

    architecture = (
        repository
        .claim_architecture_status()
    )
    if not architecture["ready"]:
        console.print(
            "[red]"
            "Database is not ready for "
            "Claim-centered crawling. "
            "Run ygc migrate-claims and "
            "check ygc claim-status."
            "[/red]"
        )
        raise typer.Exit(
            code=2
        )

    with ReverbAPICollector(
        token=config.REVERB_API_TOKEN,
        api_base=config.REVERB_API_BASE,
        timeout=config.REQUEST_TIMEOUT,
        delay=0.15,
        max_workers=workers,
    ) as collector:
        result = crawl_query(repository, collector, query, limit)

    table = Table("Metric", "Value")
    for key, value in result.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command(
    "vintage-audit"
)
def vintage_audit(
    query: str = typer.Option(
        "Fender Stratocaster",
        help="Reverb search query",
    ),
    limit: int = typer.Option(
        50,
        min=1,
        max=500,
        help=(
            "Number of listing "
            "summaries to classify"
        ),
    ),
):
    """
    Vintage分類結果を目視確認する。

    descriptionの年号には依存せず、
    一覧データ上の判定を表示する。
    """

    setup_logging()

    table = Table(
        "ID",
        "Status",
        "Year",
        "Reason",
        "Title",
    )

    counts = {
        "vintage": 0,
        "modern": 0,
        "unknown": 0,
        "non_target": 0,
    }

    with ReverbAPICollector(
        token=(
            config.REVERB_API_TOKEN
        ),
        api_base=(
            config.REVERB_API_BASE
        ),
        timeout=(
            config.REQUEST_TIMEOUT
        ),
        delay=0.15,
        max_workers=6,
    ) as collector:

        summaries = list(
            collector
            .iter_listing_summaries(
                query=query,
                limit=limit,
            )
        )

        for item in summaries:
            result = (
                classify_vintage_listing(
                    item
                )
            )

            status = (
                result[
                    "status"
                ]
            )

            counts[
                status
            ] = (
                counts.get(
                    status,
                    0,
                )
                + 1
            )

            if status == "vintage":
                status_text = (
                    "[green]"
                    "vintage"
                    "[/green]"
                )
            elif status == "modern":
                status_text = (
                    "[red]"
                    "modern"
                    "[/red]"
                )
            elif (
                status
                == "non_target"
            ):
                status_text = (
                    "[magenta]"
                    "non_target"
                    "[/magenta]"
                )
            else:
                status_text = (
                    "[yellow]"
                    "unknown"
                    "[/yellow]"
                )

            table.add_row(
                str(
                    item.get("id")
                    or ""
                ),
                status_text,
                str(
                    result[
                        "estimated_year"
                    ]
                    or ""
                ),
                str(
                    result[
                        "reason"
                    ]
                ),
                _short_context(
                    str(
                        item.get(
                            "title"
                        )
                        or ""
                    ),
                    100,
                ),
            )

    console.print(
        table
    )

    console.print()

    summary = Table(
        "Classification",
        "Count",
    )

    for key in (
        "vintage",
        "modern",
        "unknown",
        "non_target",
    ):
        summary.add_row(
            key,
            str(
                counts.get(
                    key,
                    0,
                )
            ),
        )

    console.print(
        summary
    )


@app.command(
    "serial-audit"
)
def serial_audit(
    limit: int = typer.Option(
        50,
        min=1,
        max=500,
        help=(
            "Maximum number of "
            "serial observations "
            "to inspect"
        ),
    ),
):
    setup_logging()

    repository = repo()

    with repository.connect() as con:
        rows = con.execute(
            """
            SELECT
                id,
                source_listing_id,
                source_url,
                manufacturer,
                model,
                title,
                serial_number
            FROM observations
            WHERE source_site = ?
              AND serial_number IS NOT NULL
              AND TRIM(serial_number) <> ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                "reverb",
                limit,
            ),
        ).fetchall()

    if not rows:
        console.print(
            "[yellow]"
            "No serial-number observations "
            "found."
            "[/yellow]"
        )
        return

    table = Table(
        "Obs",
        "Maker / Model",
        "DB Serial",
        "Extracted",
        "Conf.",
        "Result",
        "Context",
    )

    match_count = 0
    mismatch_count = 0
    fetch_error_count = 0

    with ReverbAPICollector(
        token=(
            config.REVERB_API_TOKEN
        ),
        api_base=(
            config.REVERB_API_BASE
        ),
        timeout=(
            config.REQUEST_TIMEOUT
        ),
        delay=0.15,
        max_workers=4,
    ) as collector:

        for row in rows:
            observation_id = (
                row["id"]
            )

            listing_id = str(
                row[
                    "source_listing_id"
                ]
                or ""
            )

            stored_serial = str(
                row[
                    "serial_number"
                ]
                or ""
            ).upper()

            maker_model = (
                f"{row['manufacturer'] or ''} "
                f"{row['model'] or ''}"
            ).strip()

            if not listing_id:
                fetch_error_count += 1

                table.add_row(
                    str(
                        observation_id
                    ),
                    maker_model,
                    stored_serial,
                    "",
                    "",
                    "[yellow]"
                    "NO ID"
                    "[/yellow]",
                    "",
                )

                continue

            detail_url = (
                f"{config.REVERB_API_BASE.rstrip('/')}"
                f"/listings/{listing_id}"
            )

            synthetic_item = {
                "id": listing_id,
                "_links": {
                    "self": {
                        "href": (
                            detail_url
                        )
                    }
                },
            }

            try:
                detail = (
                    collector
                    .fetch_listing_detail(
                        synthetic_item
                    )
                )

                text = (
                    _serial_source_text(
                        detail
                    )
                )

                candidates = (
                    extract_serial_candidates(
                        text
                    )
                )

                candidates = [
                    candidate
                    for candidate
                    in candidates
                    if (
                        candidate.confidence
                        >= config
                        .SERIAL_CONFIDENCE_THRESHOLD
                    )
                ]

                if candidates:
                    best = (
                        candidates[0]
                    )

                    extracted = (
                        best.value
                    )

                    confidence = (
                        f"{best.confidence:.2f}"
                    )

                    context = (
                        _short_context(
                            best.context
                        )
                    )

                    reason = (
                        best.reason
                    )

                else:
                    extracted = ""
                    confidence = ""
                    context = (
                        "No serial candidate "
                        "found on re-check"
                    )
                    reason = ""

                if (
                    extracted.upper()
                    == stored_serial
                ):
                    result = (
                        "[green]"
                        "MATCH"
                        "[/green]"
                    )
                    match_count += 1

                else:
                    result = (
                        "[red]"
                        "CHECK"
                        "[/red]"
                    )
                    mismatch_count += 1

                if reason:
                    context = (
                        f"[{reason}] "
                        f"{context}"
                    )

                table.add_row(
                    str(
                        observation_id
                    ),
                    maker_model,
                    stored_serial,
                    extracted,
                    confidence,
                    result,
                    context,
                )

            except Exception as exc:
                fetch_error_count += 1

                table.add_row(
                    str(
                        observation_id
                    ),
                    maker_model,
                    stored_serial,
                    "",
                    "",
                    "[yellow]"
                    "FETCH ERROR"
                    "[/yellow]",
                    _short_context(
                        str(exc)
                    ),
                )

    console.print(
        table
    )

    console.print()

    summary = Table(
        "Audit Metric",
        "Value",
    )

    summary.add_row(
        "checked",
        str(len(rows)),
    )

    summary.add_row(
        "matches",
        str(match_count),
    )

    summary.add_row(
        "needs_review",
        str(
            mismatch_count
        ),
    )

    summary.add_row(
        "fetch_errors",
        str(
            fetch_error_count
        ),
    )

    console.print(
        summary
    )


@app.command(
    "individuals"
)
def individuals():
    repository = repo()

    rows = (
        repository
        .list_individuals()
    )

    table = Table(
        "ID",
        "Maker",
        "Model",
        "Serial",
        "Observations",
    )

    for row in rows:
        table.add_row(
            str(
                row["id"]
            ),
            row[
                "manufacturer"
            ]
            or "",
            row[
                "model"
            ]
            or "",
            row[
                "serial_number"
            ]
            or "",
            str(
                row[
                    "observation_count"
                ]
            ),
        )

    console.print(
        table
    )


@app.command(
    "show"
)
def show(
    individual_id: int,
):
    repository = repo()

    (
        individual,
        observations,
    ) = (
        repository
        .get_individual(
            individual_id, include_legacy_observations=False,
        )
    )

    if not individual:
        raise typer.BadParameter(
            f"Individual "
            f"{individual_id} "
            f"not found"
        )

    console.print(
        "[bold]"
        f"Individual "
        f"#{individual['id']}"
        "[/bold]"
    )

    name = (
        f"{individual['manufacturer']} "
        f"{individual['model'] or ''}"
    ).strip()

    console.print(
        name
    )

    console.print(
        "Serial: "
        f"{individual['serial_number']}"
        "\n"
    )

    table = Table("When", "Claim", "Details", "Source")
    for claim in repository.list_claims(individual_id):
        if claim['effective_status'] != 'active':
            continue
        kind = claim['ownership_kind'] or claim['specification_kind'] or claim['claim_type']
        table.add_row(
            str(claim['occurred_at'] or claim['created_at']),
            f"#{claim['id']} {kind}",
            str(claim['listing_title'] or claim['body'] or claim['value_text'] or ''),
            str(claim['source_url'] or ''),
        )
    console.print(table)


@app.command(
    "stats"
)
def stats():
    data = (
        repo().stats()
    )

    table = Table(
        "Metric",
        "Value",
    )

    for (
        key,
        value,
    ) in data.items():
        if key == 'serial_observations':
            continue  # Alias used by the current Web UI.
        if isinstance(
            value,
            float,
        ):
            display = (
                f"{value:.1f}"
            )
        else:
            display = str(
                value
            )

        table.add_row(
            key,
            display,
        )

    console.print(
        table
    )


if __name__ == "__main__":
    app()

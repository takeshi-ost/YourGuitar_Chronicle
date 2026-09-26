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
    return Repository(
        config.DB_PATH
    )


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


def existing_listing_ids(
    repository: Repository,
    listing_ids: list[str],
) -> set[str]:
    ids = [
        value
        for value in listing_ids
        if value
    ]

    if not ids:
        return set()

    result: set[str] = set()

    chunk_size = 500

    with repository.connect() as con:
        for start in range(
            0,
            len(ids),
            chunk_size,
        ):
            chunk = ids[
                start:
                start + chunk_size
            ]

            placeholders = (
                ",".join(
                    "?"
                    for _ in chunk
                )
            )

            sql = (
                "SELECT "
                "source_listing_id "
                "FROM observations "
                "WHERE source_site = ? "
                "AND source_listing_id "
                f"IN ({placeholders})"
            )

            rows = con.execute(
                sql,
                [
                    "reverb",
                    *chunk,
                ],
            )

            for row in rows:
                result.add(
                    str(
                        row[
                            "source_listing_id"
                        ]
                    )
                )

    return result


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

    run_id = (
        repository.start_run(
            "reverb"
        )
    )

    fetched = 0
    candidate_count = 0
    detailed = 0
    created = 0

    skipped_modern = 0
    skipped_non_target = 0
    skipped_unknown = 0
    skipped_existing = 0

    try:
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
            max_workers=workers,
        ) as collector:

            console.print(
                "[cyan]"
                "Fetching listing "
                "summaries..."
                "[/cyan]"
            )

            summaries = list(
                collector
                .iter_listing_summaries(
                    query=query,
                    limit=limit,
                )
            )

            fetched = len(
                summaries
            )

            listing_ids = [
                collector.listing_id(
                    item
                )
                for item in summaries
            ]

            existing_ids = (
                existing_listing_ids(
                    repository,
                    [
                        value
                        for value
                        in listing_ids
                        if value
                    ],
                )
            )

            candidates: list[
                dict
            ] = []

            for item in summaries:
                listing_id = (
                    collector
                    .listing_id(
                        item
                    )
                )

                if (
                    listing_id
                    and listing_id
                    in existing_ids
                ):
                    skipped_existing += 1
                    continue

                classification = (
                    classify_vintage_listing(
                        item
                    )
                )

                status = (
                    classification[
                        "status"
                    ]
                )

                if status in (
                    "vintage",
                    "unknown",
                ):
                    candidates.append(
                        item
                    )
                    continue

                if status == "modern":
                    skipped_modern += 1
                    continue

                skipped_non_target += 1

            candidate_count = len(
                candidates
            )

            console.print(
                "[cyan]"
                f"Summaries={fetched}, "
                f"detail_candidates="
                f"{candidate_count}, "
                f"modern="
                f"{skipped_modern}, "
                f"non_target="
                f"{skipped_non_target}, "
                f"existing="
                f"{skipped_existing}"
                "[/cyan]"
            )

            if candidates:
                console.print(
                    "[cyan]"
                    "Fetching candidate "
                    f"details with "
                    f"{workers} workers..."
                    "[/cyan]"
                )

            for item in (
                collector
                .fetch_listing_details(
                    candidates
                )
            ):
                detailed += 1

                claim_data = (
                    to_listing_claim_data(
                        item,
                        config
                        .SERIAL_CONFIDENCE_THRESHOLD,
                    )
                )

                status = str(
                    claim_data.get(
                        "vintage_status",
                        "unknown",
                    )
                )

                if status == "modern":
                    skipped_modern += 1
                    continue

                if (
                    status
                    == "non_target"
                ):
                    skipped_non_target += 1
                    continue

                if status != "vintage":
                    skipped_unknown += 1
                    continue

                provenance = (
                    to_provenance_observation(
                        item,
                        config
                        .SERIAL_CONFIDENCE_THRESHOLD,
                    )
                )

                result = (
                    repository
                    .persist_reverb_listing_claim(
                        claim_data,
                        provenance,
                    )
                )

                if result["created"]:
                    created += 1

        repository.finish_run(
            run_id,
            pages_discovered=(
                fetched
            ),
            pages_fetched=(
                detailed
            ),
            observations_created=(
                created
            ),
            status="ok",
        )

        console.print()

        table = Table(
            "Metric",
            "Value",
        )

        table.add_row(
            "summaries_fetched",
            str(fetched),
        )

        table.add_row(
            "detail_candidates",
            str(candidate_count),
        )

        table.add_row(
            "details_fetched",
            str(detailed),
        )

        table.add_row(
            "skipped_modern",
            str(skipped_modern),
        )

        table.add_row(
            "skipped_non_target",
            str(
                skipped_non_target
            ),
        )

        table.add_row(
            "skipped_unknown",
            str(
                skipped_unknown
            ),
        )

        table.add_row(
            "skipped_existing",
            str(
                skipped_existing
            ),
        )

        table.add_row(
            "new_observations",
            str(created),
        )

        console.print(
            table
        )

    except Exception as exc:
        repository.finish_run(
            run_id,
            pages_discovered=(
                fetched
            ),
            pages_fetched=(
                detailed
            ),
            observations_created=(
                created
            ),
            status="error",
            error_message=str(
                exc
            ),
        )

        raise


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
            individual_id
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

    table = Table(
        "When",
        "Seller",
        "Title",
        "Source",
    )

    for obs in observations:
        table.add_row(
            obs[
                "listing_date"
            ]
            or obs[
                "observed_at"
            ],
            obs[
                "seller"
            ]
            or "",
            obs[
                "title"
            ]
            or "",
            obs[
                "source_url"
            ]
            or "",
        )

    console.print(
        table
    )


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
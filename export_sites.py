#!/usr/bin/env python3
"""Read-only full export of all sites from the GoGetLinks /mySites page."""

from __future__ import annotations

import argparse
import csv
import html
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import gogetlinks_parser as ggl

EXPORT_FIELDS = [
    "site",
    "site_id",
    "status",
    "status_reason",
    "status_details",
    "sqi",
    "tf_cf_average",
    "trust_flow",
    "citation_flow",
    "pr_cy",
    "traffic",
    "traffic_max",
    "traffic_source",
    "indexation",
    "indexation_percent",
    "indexation_details",
    "referencing",
    "referencing_percent",
    "referencing_links_placed",
    "pages_in_index",
    "speed",
    "speed_days",
    "trust",
    "application_limit",
    "links_pending",
    "links_placed",
    "earnings_rub",
    "settings_url",
    "status_url",
    "pending_links_url",
    "placed_links_url",
    "earnings_url",
    "source_page",
    "source_row",
    "captured_at_utc",
]


EXTRACT_ROWS_SCRIPT = r"""
const tables = Array.from(document.querySelectorAll('table'));
const dataTable = tables.find((table) =>
    Array.from(table.querySelectorAll('thead th')).some((th) =>
        (th.innerText || '').trim() === 'Сайт'
    )
);
if (!dataTable) {
    return {headers: [], rows: []};
}

const attrs = (element) => Object.fromEntries(
    Array.from(element.attributes || []).map((attr) => [attr.name, attr.value])
);
const headers = Array.from(dataTable.querySelectorAll('thead th')).map(
    (cell) => (cell.innerText || '').trim()
);
const rows = Array.from(dataTable.querySelectorAll('tbody tr'))
    .filter((row) => row.querySelectorAll('td').length >= headers.length)
    .map((row) => ({
        text: (row.innerText || '').trim(),
        html: row.outerHTML,
        attributes: attrs(row),
        cells: Array.from(row.querySelectorAll(':scope > td')).map((cell) => {
            const descendants = [cell, ...Array.from(cell.querySelectorAll('*'))];
            return {
                text: (cell.innerText || '').trim(),
                html: cell.innerHTML,
                attributes: attrs(cell),
                links: Array.from(cell.querySelectorAll('a')).map((link) => ({
                    text: (link.innerText || '').trim(),
                    href: link.href || '',
                    attributes: attrs(link),
                })),
                inputs: Array.from(cell.querySelectorAll('input')).map((input) => ({
                    value: input.value || '',
                    attributes: attrs(input),
                })),
                tooltips: descendants
                    .filter((element) => Array.from(element.attributes || []).some(
                        (attr) => attr.name.startsWith('data-tooltip')
                    ))
                    .map((element) => ({
                        tag: element.tagName.toLowerCase(),
                        text: (element.innerText || '').trim(),
                        attributes: attrs(element),
                    })),
            };
        }),
    }));
return {headers, rows};
"""


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Export every GoGetLinks /mySites row to CSV and JSON."
    )
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--cookie-file", default=ggl.COOKIE_FILE)
    parser.add_argument("--proxy", default=ggl.DEFAULT_FALLBACK_PROXY)
    parser.add_argument("--output-dir", default="outputs/sites-export")
    parser.add_argument(
        "--basename",
        default=None,
        help=(
            "Output basename without extension "
            "(default: gogetlinks-sites-YYYY-MM-DD)."
        ),
    )
    return parser.parse_args()


def first_int(value: str) -> Optional[int]:
    """Return the first integer from a human-formatted value."""
    match = re.search(r"\d[\d\s\u00a0]*", value or "")
    if not match:
        return None
    return int(re.sub(r"\D", "", match.group(0)))


def tooltip_text(cell: dict[str, Any]) -> str:
    """Return all tooltip attributes as readable text."""
    parts: list[str] = []
    for tooltip in cell.get("tooltips", []):
        attributes = tooltip.get("attributes", {})
        for name in ("data-tooltip-head", "data-tooltip-body", "data-tooltip-content"):
            value = attributes.get(name)
            if value:
                parts.append(str(value))
    cleaned = html.unescape(" ".join(parts))
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def html_to_text(value: str) -> str:
    """Convert a small modal HTML fragment to compact readable text."""
    without_scripts = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL
    )
    with_breaks = re.sub(
        r"</?(?:p|li|div|h[1-6]|br)\b[^>]*>", "\n", without_scripts, flags=re.IGNORECASE
    )
    plain = re.sub(r"<[^>]+>", " ", with_breaks)
    lines = [
        re.sub(r"\s+", " ", line).strip() for line in html.unescape(plain).splitlines()
    ]
    return "\n".join(line for line in lines if line)


def extract_status_reason(value: str) -> Optional[str]:
    """Extract explicit rejection reasons from a GoGetLinks status modal."""
    block_match = re.search(
        r'class=["\'][^"\']*block-note__content[^"\']*["\'][^>]*>(.*?)</div>',
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if block_match:
        reasons = [
            html_to_text(item)
            for item in re.findall(
                r"<li\b[^>]*>(.*?)</li>",
                block_match.group(1),
                flags=re.IGNORECASE | re.DOTALL,
            )
        ]
        reasons = [reason for reason in reasons if reason]
        if reasons:
            return "; ".join(reasons)

    content_match = re.search(
        r'class=["\'][^"\']*modal-content[^"\']*["\'][^>]*>(.*?)</div>',
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if content_match:
        return html_to_text(content_match.group(1)) or None
    return None


def link_by_class(cell: dict[str, Any], class_name: str) -> Optional[str]:
    """Find an href for a link containing the requested CSS class."""
    for link in cell.get("links", []):
        classes = str(link.get("attributes", {}).get("class", "")).split()
        if class_name in classes:
            return link.get("href") or None
    return None


def first_link(cell: dict[str, Any]) -> Optional[str]:
    """Return the first absolute link in a cell."""
    links = cell.get("links", [])
    return links[0].get("href") if links else None


def regex_int(text: str, pattern: str) -> Optional[int]:
    """Extract a grouped integer using a localized regex pattern."""
    match = re.search(pattern, text, re.IGNORECASE)
    return first_int(match.group(1)) if match else None


def first_float(value: str) -> Optional[float]:
    """Return the first decimal number from a human-formatted value."""
    match = re.search(r"\d+(?:[.,]\d+)?", value or "")
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def normalize_row(
    raw_row: dict[str, Any],
    page_number: int,
    row_number: int,
    captured_at: str,
) -> dict[str, Any]:
    """Convert one raw 13-cell row into filter-friendly fields."""
    cells = raw_row["cells"]
    if len(cells) < 13:
        raise ValueError(f"Expected at least 13 cells, got {len(cells)}")

    site_id = None
    for input_data in cells[0].get("inputs", []):
        classes = str(input_data.get("attributes", {}).get("class", "")).split()
        if "site-id" in classes:
            site_id = first_int(str(input_data.get("value", "")))
            break

    site_text = cells[0].get("text", "")
    site = site_text.splitlines()[0].strip().lower() if site_text else ""
    tf_cf_details = tooltip_text(cells[3])
    indexation_details = tooltip_text(cells[6])
    referencing_details = tooltip_text(cells[7])

    traffic_source = None
    for tooltip in cells[5].get("tooltips", []):
        head = tooltip.get("attributes", {}).get("data-tooltip-head")
        if head and head not in {"Предоставить данные счетчика"}:
            traffic_source = html.unescape(str(head)).strip()
            break

    link_counts = [
        first_int(str(link.get("text", ""))) for link in cells[11].get("links", [])
    ]
    links_pending = link_counts[0] if len(link_counts) >= 1 else None
    links_placed = link_counts[1] if len(link_counts) >= 2 else None

    return {
        "site": site,
        "site_id": site_id,
        "status": cells[1].get("text", "").strip(),
        "status_reason": None,
        "status_details": None,
        "sqi": first_int(cells[2].get("text", "")),
        "tf_cf_average": first_int(cells[3].get("text", "")),
        "trust_flow": regex_int(tf_cf_details, r"Trust Flow\s*[-–—:]\s*([\d\s]+)"),
        "citation_flow": regex_int(
            tf_cf_details, r"[,;]\s*Citation Flow\s*[-–—:]\s*([\d\s]+)"
        ),
        "pr_cy": first_int(cells[4].get("text", "")),
        "traffic": cells[5].get("text", "").strip(),
        "traffic_max": first_int(cells[5].get("text", "")),
        "traffic_source": traffic_source,
        "indexation": cells[6].get("text", "").strip(),
        "indexation_percent": first_int(cells[6].get("text", "")),
        "indexation_details": indexation_details or None,
        "referencing": cells[7].get("text", "").strip(),
        "referencing_percent": regex_int(
            referencing_details, r"Текущая ссылочность\s*[-–—:].*?\(([\d\s]+)%\)"
        ),
        "referencing_links_placed": regex_int(
            referencing_details, r"Ссылок размещено\s*[-–—:]\s*([\d\s]+)"
        ),
        "pages_in_index": regex_int(
            referencing_details, r"Страниц в индексе\s*[-–—:]\s*([\d\s]+)"
        ),
        "speed": cells[8].get("text", "").strip(),
        "speed_days": first_float(cells[8].get("text", "")),
        "trust": first_int(cells[9].get("text", "")),
        "application_limit": first_int(cells[10].get("text", "")),
        "links_pending": links_pending,
        "links_placed": links_placed,
        "earnings_rub": first_int(cells[12].get("text", "")),
        "settings_url": first_link(cells[0]),
        "status_url": first_link(cells[1]),
        "pending_links_url": link_by_class(cells[11], "mySites__link-new"),
        "placed_links_url": link_by_class(cells[11], "mySites__link-done"),
        "earnings_url": first_link(cells[12]),
        "source_page": page_number,
        "source_row": row_number,
        "captured_at_utc": captured_at,
    }


def authenticate_driver(
    cookie_file: Path,
    proxy: Optional[str],
    config_path: Path,
    logger: logging.Logger,
) -> Any:
    """Create an authenticated driver without connecting to the database."""
    driver = ggl.initialize_driver(logger, proxy_server=proxy or None)
    ggl.COOKIE_FILE = str(cookie_file)
    if ggl.load_cookies(driver, logger):
        return driver

    config = ggl.load_config(str(config_path))
    ggl.validate_config(config)
    if not ggl.authenticate(
        driver,
        credentials=config["gogetlinks"],
        anticaptcha_config=config["anticaptcha"],
        logger=logger,
    ):
        driver.quit()
        raise RuntimeError("GoGetLinks authentication failed")
    ggl.save_cookies(driver, logger)
    return driver


def collect_status_details(
    driver: Any,
    normalized_rows: list[dict[str, Any]],
    raw_by_key: dict[str, dict[str, Any]],
    proxy: Optional[str],
    logger: logging.Logger,
) -> None:
    """Fetch read-only modal details for rejected and temporarily rejected sites."""
    session = ggl.get_selenium_cookies_session(driver, logger, proxy_server=proxy)
    session.headers["Referer"] = ggl.MY_SITES_URL
    target_statuses = {"Отклонен, подробнее...", "Временно отклонен"}
    targets = [
        row
        for row in normalized_rows
        if row["status"] in target_statuses and row.get("status_url")
    ]

    for index, row in enumerate(targets, start=1):
        key = str(row.get("site_id") or row["site"])
        detail: dict[str, Any] = {"url": row["status_url"]}
        try:
            response = session.get(row["status_url"], timeout=30)
            response.raise_for_status()
            encoding = response.encoding or "windows-1251"
            if encoding.lower() in {"iso-8859-1", "latin-1"}:
                encoding = "windows-1251"
            modal_html = response.content.decode(encoding, errors="replace")
            status_details = html_to_text(modal_html)
            status_reason = extract_status_reason(modal_html)
            row["status_details"] = status_details or None
            row["status_reason"] = status_reason
            detail.update(
                {
                    "http_status": response.status_code,
                    "content_type": response.headers.get("Content-Type"),
                    "text": status_details,
                    "reason": status_reason,
                    "html": modal_html,
                }
            )
        except Exception as error:
            detail["error"] = f"{type(error).__name__}: {error}"
            logger.warning("Status details failed for %s: %s", row["site"], error)
        raw_by_key[key]["status_detail"] = detail
        if index % 20 == 0 or index == len(targets):
            logger.info("Status details: %s/%s", index, len(targets))


def collect_sites(
    driver: Any,
    logger: logging.Logger,
    proxy: Optional[str] = None,
) -> dict[str, Any]:
    """Collect all pages from /mySites, preserving raw row HTML and attributes."""
    driver.get(ggl.MY_SITES_URL)
    ggl.set_my_sites_count_in_page(driver, logger)
    driver.get(ggl.MY_SITES_URL)

    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    normalized_by_key: dict[str, dict[str, Any]] = {}
    raw_by_key: dict[str, dict[str, Any]] = {}
    headers: list[str] = []
    page_number = 1

    while True:
        page_data = driver.execute_script(EXTRACT_ROWS_SCRIPT)
        page_headers = page_data.get("headers", [])
        raw_rows = page_data.get("rows", [])
        if not headers:
            headers = page_headers
        if len(headers) < 13 or not raw_rows:
            raise RuntimeError(
                f"Unexpected /mySites page {page_number}: "
                f"headers={len(headers)}, rows={len(raw_rows)}"
            )

        for row_number, raw_row in enumerate(raw_rows, start=1):
            normalized = normalize_row(
                raw_row,
                page_number=page_number,
                row_number=row_number,
                captured_at=captured_at,
            )
            key = str(normalized.get("site_id") or normalized["site"])
            normalized_by_key[key] = normalized
            raw_by_key[key] = {
                "site": normalized["site"],
                "site_id": normalized["site_id"],
                "source_page": page_number,
                "source_row": row_number,
                **raw_row,
            }

        logger.info(
            "Export page %s: rows=%s, accumulated=%s",
            page_number,
            len(raw_rows),
            len(normalized_by_key),
        )
        if not ggl.go_to_next_my_sites_page(driver, logger):
            break
        page_number += 1

    normalized_rows = sorted(
        normalized_by_key.values(), key=lambda row: (row["site"], row["site_id"] or 0)
    )
    collect_status_details(driver, normalized_rows, raw_by_key, proxy, logger)
    raw_rows = [
        raw_by_key[str(row.get("site_id") or row["site"])] for row in normalized_rows
    ]
    return {
        "metadata": {
            "source_url": ggl.MY_SITES_URL,
            "captured_at_utc": captured_at,
            "site_count": len(normalized_rows),
            "page_count": page_number,
            "headers": headers,
        },
        "sites": normalized_rows,
        "raw_rows": raw_rows,
    }


def write_export(
    export: dict[str, Any], output_dir: Path, basename: str
) -> tuple[Path, Path]:
    """Write normalized CSV and lossless JSON files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{basename}.csv"
    json_path = output_dir / f"{basename}.json"

    with csv_path.open("w", encoding="utf-8-sig", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle, fieldnames=EXPORT_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(export["sites"])

    with json_path.open("w", encoding="utf-8") as file_handle:
        json.dump(export, file_handle, ensure_ascii=False, indent=2)
        file_handle.write("\n")

    return csv_path, json_path


def main() -> int:
    """Run a complete read-only site export."""
    args = parse_args()
    logger = logging.getLogger("gogetlinks_sites_export")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())

    output_dir = Path(args.output_dir)
    basename = args.basename or f"gogetlinks-sites-{datetime.now():%Y-%m-%d}"
    driver = authenticate_driver(
        cookie_file=Path(args.cookie_file),
        proxy=args.proxy,
        config_path=Path(args.config),
        logger=logger,
    )
    try:
        export = collect_sites(driver, logger, proxy=args.proxy or None)
    finally:
        driver.quit()

    csv_path, json_path = write_export(export, output_dir, basename)
    logger.info(
        "Export complete: sites=%s, pages=%s, csv=%s, json=%s",
        export["metadata"]["site_count"],
        export["metadata"]["page_count"],
        csv_path,
        json_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

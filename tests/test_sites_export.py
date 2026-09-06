"""Tests for the full /mySites exporter."""

from export_sites import (
    extract_status_reason,
    first_float,
    first_int,
    html_to_text,
    normalize_row,
    tooltip_text,
)


def make_cell(text="", links=None, inputs=None, tooltips=None):
    """Build a minimal raw cell fixture."""
    return {
        "text": text,
        "html": "",
        "attributes": {},
        "links": links or [],
        "inputs": inputs or [],
        "tooltips": tooltips or [],
    }


def test_first_int_handles_grouped_numbers_and_na():
    assert first_int("29 013 Р") == 29013
    assert first_int("до 50") == 50
    assert first_int("N/A") is None


def test_first_float_handles_localized_decimal_and_na():
    assert first_float("0.7 дней.") == 0.7
    assert first_float("1,5 дня") == 1.5
    assert first_float("N/A") is None


def test_tooltip_text_strips_markup_and_decodes_entities():
    cell = make_cell(
        tooltips=[
            {
                "attributes": {
                    "data-tooltip-head": "Показатели",
                    "data-tooltip-body": "&lt;p&gt;Trust Flow - 9&lt;/p&gt;",
                }
            }
        ]
    )
    assert tooltip_text(cell) == "Показатели Trust Flow - 9"


def test_extract_status_reason_from_rejection_modal():
    modal = """
    <div class="modal-content">
      <div class="block-note__content"><ul>
        <li>Права на сайт не подтверждены</li>
        <li>Недостаточно метрик</li>
      </ul></div>
    </div>
    """
    assert extract_status_reason(modal) == (
        "Права на сайт не подтверждены; Недостаточно метрик"
    )


def test_extract_status_reason_from_temporary_status_modal():
    modal = """
    <div class="modal-content">
      <p>Показатель ссылочности сайта превысил 90%.</p>
      Необходимо увеличить количество страниц в индексе.
    </div>
    """
    assert extract_status_reason(modal) == (
        "Показатель ссылочности сайта превысил 90%.\n"
        "Необходимо увеличить количество страниц в индексе."
    )
    assert html_to_text("<p>Тест&nbsp;текста</p>") == "Тест текста"


def test_normalize_row_extracts_hidden_metrics_and_links():
    cells = [make_cell() for _ in range(13)]
    cells[0] = make_cell(
        "wordscience.org\nНастроить",
        links=[
            {
                "text": "Настроить",
                "href": "https://gogetlinks.net/edit/91895",
                "attributes": {},
            }
        ],
        inputs=[
            {
                "value": "91895",
                "attributes": {"class": "site-id", "type": "hidden"},
            }
        ],
    )
    cells[1] = make_cell("Отклонен, подробнее...")
    cells[2] = make_cell("120")
    cells[3] = make_cell(
        "23",
        tooltips=[
            {
                "attributes": {
                    "data-tooltip-body": "<p>Trust Flow - 9, Citation Flow - 37</p>"
                }
            }
        ],
    )
    cells[5] = make_cell(
        "до 50",
        tooltips=[{"attributes": {"data-tooltip-head": "SimilarWeb"}}],
    )
    cells[6] = make_cell("N/A")
    cells[7] = make_cell(
        "Оптимальная",
        tooltips=[
            {
                "attributes": {
                    "data-tooltip-body": (
                        "Текущая ссылочность - Оптимальная (16%); "
                        "Ссылок размещено - 91; Страниц в индексе - 3601"
                    )
                }
            }
        ],
    )
    cells[9] = make_cell("31")
    cells[8] = make_cell("0.7 дней.")
    cells[10] = make_cell("275")
    cells[11] = make_cell(
        "0\n91",
        links=[
            {
                "text": "0",
                "href": "https://gogetlinks.net/pending",
                "attributes": {"class": "mySites__link-new"},
            },
            {
                "text": "91",
                "href": "https://gogetlinks.net/placed",
                "attributes": {"class": "mySites__link-done"},
            },
        ],
    )
    cells[12] = make_cell("29 013 Р")

    normalized = normalize_row(
        {"cells": cells},
        page_number=2,
        row_number=3,
        captured_at="2026-09-03T10:00:00+00:00",
    )

    assert normalized["site"] == "wordscience.org"
    assert normalized["site_id"] == 91895
    assert normalized["trust_flow"] == 9
    assert normalized["citation_flow"] == 37
    assert normalized["traffic_max"] == 50
    assert normalized["traffic_source"] == "SimilarWeb"
    assert normalized["referencing_percent"] == 16
    assert normalized["referencing_links_placed"] == 91
    assert normalized["pages_in_index"] == 3601
    assert normalized["speed_days"] == 0.7
    assert normalized["links_pending"] == 0
    assert normalized["links_placed"] == 91
    assert normalized["earnings_rub"] == 29013
    assert normalized["source_page"] == 2

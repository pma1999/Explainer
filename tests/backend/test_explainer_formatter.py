from types import SimpleNamespace

from backend.agents import explainer


def test_preserves_verbatim_content_accepts_markdown_only_changes():
    original = "Primera idea importante.\nSegunda idea importante."
    formatted = "- Primera idea importante.\n- Segunda idea importante."
    assert explainer._preserves_verbatim_content(original, formatted) is True


def test_preserves_verbatim_content_detects_content_changes():
    original = "Primera idea importante.\nSegunda idea importante."
    formatted = "- Primera idea importante.\n- Otra idea diferente."
    assert explainer._preserves_verbatim_content(original, formatted) is False


def test_post_format_explainer_markdown_formats_all_subsections_and_preserves_order(monkeypatch):
    calls = []

    def _fake_formatter(api_key: str, text: str):
        calls.append((api_key, text))
        return f"- {text}", SimpleNamespace(total_token_count=1)

    monkeypatch.setattr(explainer, "_format_subsection_markdown", _fake_formatter)

    payload = {
        "introduccion": "x",
        "desarrollo": [
            {
                "titulo_seccion": "S1",
                "subsecciones": [
                    {"titulo_subseccion": "1.1", "explicacion_detallada": "Texto A"},
                    {"titulo_subseccion": "1.2", "explicacion_detallada": "Texto B"},
                ],
            },
            {
                "titulo_seccion": "S2",
                "subsecciones": [
                    {"titulo_subseccion": "2.1", "explicacion_detallada": "Texto C"},
                ],
            },
        ],
        "conclusion": "y",
    }

    formatted, usage_items = explainer._post_format_explainer_markdown("k", payload)

    assert len(calls) == 3
    assert [s["explicacion_detallada"] for s in formatted["desarrollo"][0]["subsecciones"]] == ["- Texto A", "- Texto B"]
    assert formatted["desarrollo"][1]["subsecciones"][0]["explicacion_detallada"] == "- Texto C"
    assert len(usage_items) == 3


def test_combine_usage_metadata_sums_counts():
    merged = explainer._combine_usage_metadata(
        [
            SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=3, total_token_count=18),
            SimpleNamespace(prompt_token_count=7, candidates_token_count=9, thoughts_token_count=1, total_token_count=17),
        ]
    )

    assert merged.prompt_token_count == 17
    assert merged.candidates_token_count == 14
    assert merged.thoughts_token_count == 4
    assert merged.total_token_count == 35

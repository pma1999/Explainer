from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.agents import completeness_validator as module


def _usage() -> SimpleNamespace:
    return SimpleNamespace(prompt_token_count=11, candidates_token_count=7, total_token_count=18)


def _explanation(text: str = "La burocracia profesionaliza el oficio publico.") -> dict:
    return {
        "desarrollo": [
            {
                "titulo_seccion": "Burocracia y oficiales",
                "explicacion_introductoria": "La seccion explica la reforma administrativa.",
                "subsecciones": [
                    {
                        "titulo_subseccion": "Oficiales reales",
                        "explicacion_detallada": text,
                    }
                ],
            }
        ]
    }


def _scope_context():
    return module.ExplainerValidationContext(
        scope_kind="subpart",
        current=module.ExplainerScopeItem(
            kind="subpart",
            number="2/3",
            title="Cambios estructurales",
            content="Reforma administrativa y oficiales reales.",
            identification="NUCLEO: paginas 19-22. Empieza en cambios estructurales y termina antes de Consejos.",
            anchors=("Las monarquias modernas reforzaron", "oficio publico cada vez mas tecnico"),
            page_start=19,
            page_end=22,
        ),
        parent=module.ExplainerScopeItem(
            kind="part",
            number="2/5",
            title="El Estado Moderno",
            content="Instituciones del Estado Moderno.",
        ),
        previous_neighbor=module.ExplainerScopeItem(
            kind="subpart",
            number="1/3",
            title="Precursores",
            content="Teorizacion politica previa.",
        ),
        next_neighbor=module.ExplainerScopeItem(
            kind="subpart",
            number="3/3",
            title="Consejos",
            content="Regimen polisinodial.",
        ),
    )


def _fake_response(report: dict) -> SimpleNamespace:
    return SimpleNamespace(text=json.dumps(report), usage_metadata=_usage())


def test_serializer_includes_desarrollo_titles_and_bodies():
    text = module._serialize_for_validation(_explanation())

    assert "Burocracia y oficiales" in text
    assert "Oficiales reales" in text
    assert "La burocracia profesionaliza" in text


def test_check_explainer_validation_accepts_complete_in_scope(monkeypatch):
    captured: dict = {}

    def _fake_generate(**kwargs):
        captured.update(kwargs)
        return _fake_response(
            {
                "is_complete": True,
                "scope_status": "ok",
                "reason": "Completa y dentro del alcance.",
                "offending_fragments": [],
                "retry_instructions": "",
            }
        )

    monkeypatch.setattr(module.genai, "Client", lambda api_key: object())
    monkeypatch.setattr(module, "generate_content_with_retry", _fake_generate)

    report, usage = module.check_explainer_validation(
        _explanation(),
        gemini_api_key="AIzaFakeKey",
        validation_context=_scope_context(),
    )

    assert usage.total_token_count == 18
    assert report.is_valid is True
    user_text = captured["contents"][0].parts[0].text
    assert "Cambios estructurales" in user_text
    assert "Consejos" in user_text


def test_check_explainer_validation_accepts_minor_bridge_context(monkeypatch):
    monkeypatch.setattr(module.genai, "Client", lambda api_key: object())
    monkeypatch.setattr(
        module,
        "generate_content_with_retry",
        lambda **kwargs: _fake_response(
            {
                "is_complete": True,
                "scope_status": "minor_context_only",
                "reason": "Solo hay una mencion puente breve a la subparte vecina.",
                "offending_fragments": [],
                "retry_instructions": "",
            }
        ),
    )

    report, _ = module.check_explainer_validation(
        _explanation("La burocracia se entiende mejor si se contrasta brevemente con los Consejos."),
        gemini_api_key="AIzaFakeKey",
        validation_context=_scope_context(),
    )

    assert report.is_valid is True
    assert report.scope_status == "minor_context_only"


def test_format_retry_context_for_scope_violation_is_specific_not_truncation_generic():
    report = module.ExplainerValidationReport(
        is_complete=True,
        scope_status="violation",
        reason="Desarrolla de forma sustantiva el Regimen polisinodial.",
        offending_fragments=("Regimen polisinodial",),
        retry_instructions="Retira el desarrollo de Consejos y conserva Burocracia.",
    )

    retry_context = module.format_explainer_retry_context(
        _explanation("La burocracia se desarrolla, pero luego explica el Regimen polisinodial."),
        report,
        validation_context=_scope_context(),
    )

    assert "Desarrolla de forma sustantiva" in retry_context
    assert "Regimen polisinodial" in retry_context
    assert "Retira el desarrollo de Consejos" in retry_context
    assert "Cambios estructurales" in retry_context
    assert "Burocracia" in retry_context
    assert "quedo TRUNCADA" not in retry_context


def test_run_with_explainer_validation_retries_violation_then_accepts(monkeypatch):
    reports = [
        module.ExplainerValidationReport(
            is_complete=True,
            scope_status="violation",
            reason="Invade Consejos.",
            offending_fragments=("Consejos",),
            retry_instructions="Eliminar Consejos.",
        ),
        module.ExplainerValidationReport(
            is_complete=True,
            scope_status="ok",
            reason="Corregida.",
            offending_fragments=(),
            retry_instructions="",
        ),
    ]
    retry_reports: list[module.ExplainerValidationReport] = []

    def _fake_check(*args, **kwargs):
        return reports.pop(0), _usage()

    def _retry(previous_result, report):
        retry_reports.append(report)
        return _explanation("Ahora solo desarrolla Burocracia."), _usage()

    monkeypatch.setattr(module, "check_explainer_validation", _fake_check)

    result, usage, validator_usages = module.run_with_explainer_validation(
        initial_call=lambda: (_explanation("Invade Consejos."), _usage()),
        retry_call=_retry,
        gemini_api_key="AIzaFakeKey",
        label="test",
        validation_context=_scope_context(),
    )

    assert result["desarrollo"][0]["subsecciones"][0]["explicacion_detallada"] == "Ahora solo desarrolla Burocracia."
    assert usage.total_token_count == 18
    assert len(validator_usages) == 2
    assert retry_reports[0].reason == "Invade Consejos."


def test_run_with_explainer_validation_raises_after_persistent_confirmed_failure(monkeypatch):
    report = module.ExplainerValidationReport(
        is_complete=True,
        scope_status="violation",
        reason="Sigue desarrollando Consejos.",
        offending_fragments=("Consejos",),
        retry_instructions="Eliminar Consejos.",
    )
    monkeypatch.setattr(module, "check_explainer_validation", lambda *a, **k: (report, _usage()))

    with pytest.raises(module.ExplainerValidationError) as exc_info:
        module.run_with_explainer_validation(
            initial_call=lambda: (_explanation("Consejos."), _usage()),
            retry_call=lambda previous, validation_report: (_explanation("Consejos otra vez."), _usage()),
            gemini_api_key="AIzaFakeKey",
            label="test",
            validation_context=_scope_context(),
        )

    assert exc_info.value.report.scope_status == "violation"
    assert "Sigue desarrollando Consejos" in str(exc_info.value)


def test_run_with_explainer_validation_combines_truncation_and_scope_retry(monkeypatch):
    report = module.ExplainerValidationReport(
        is_complete=False,
        scope_status="violation",
        reason="Termina abruptamente e invade Consejos.",
        offending_fragments=("Consejos",),
        retry_instructions="Cerrar la ultima frase y retirar Consejos.",
    )

    retry_context = module.format_explainer_retry_context(
        _explanation("La burocracia y"),
        report,
        validation_context=_scope_context(),
    )

    assert "trunc" in retry_context.lower()
    assert "alcance" in retry_context.lower()
    assert "Consejos" in retry_context


def test_check_explainer_validation_fails_open_when_reviewer_errors(monkeypatch):
    monkeypatch.setattr(module.genai, "Client", lambda api_key: object())

    def _raise(**kwargs):
        raise RuntimeError("reviewer unavailable")

    monkeypatch.setattr(module, "generate_content_with_retry", _raise)

    report, usage = module.check_explainer_validation(
        _explanation(),
        gemini_api_key="AIzaFakeKey",
        validation_context=_scope_context(),
    )

    assert usage is None
    assert report.is_valid is True
    assert "aceptado" in report.reason


def test_gemini_validated_signature_defaults_validation_context_none(monkeypatch):
    from backend.agents import explainer as explainer_module

    captured: dict = {}

    def _fake_run_with(**kwargs):
        captured.update(kwargs)
        return _explanation(), _usage(), []

    monkeypatch.setattr(explainer_module, "run_with_explainer_validation", _fake_run_with)

    result, usage, validator_usages = explainer_module.run_subpart_explainer_validated(
        "AIzaFakeKey",
        "uploaded://file",
        "Prompt de prueba",
    )

    assert result["desarrollo"]
    assert usage.total_token_count == 18
    assert validator_usages == []
    assert captured["validation_context"] is None

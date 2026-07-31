"""Resource-map URL tests (A6): sanitization helper + prompt contract includes url."""

from __future__ import annotations

import main
from backend.agents import resources as resources_agent


class TestSanitizeResourcesUrls:
    def _sample_data(self):
        return {
            "titulo_mapa": "Mapa",
            "ejes_tematicos": [
                {
                    "nombre_eje": "Eje 1",
                    "recursos": [
                        {"titulo": "Bueno", "url": "https://example.com/recurso"},
                        {"titulo": "Malo texto", "url": "notaurl"},
                        {"titulo": "Malo js", "url": "javascript:alert(1)"},
                        {"titulo": "Sin url"},
                    ],
                }
            ],
        }

    def test_keeps_valid_https_url(self):
        data = self._sample_data()
        main._sanitize_resources_urls(data)
        recursos = data["ejes_tematicos"][0]["recursos"]
        assert recursos[0]["url"] == "https://example.com/recurso"

    def test_discards_non_http_urls(self):
        data = self._sample_data()
        main._sanitize_resources_urls(data)
        recursos = data["ejes_tematicos"][0]["recursos"]
        assert recursos[1]["url"] == ""
        assert recursos[2]["url"] == ""

    def test_leaves_resources_without_url_key_untouched(self):
        data = self._sample_data()
        main._sanitize_resources_urls(data)
        recursos = data["ejes_tematicos"][0]["recursos"]
        assert "url" not in recursos[3]

    def test_returns_same_dict_and_handles_non_dict_input(self):
        data = self._sample_data()
        assert main._sanitize_resources_urls(data) is data
        assert main._sanitize_resources_urls({"ok": True}) == {"ok": True}
        assert main._sanitize_resources_urls({"ejes_tematicos": "no-list"}) == {"ejes_tematicos": "no-list"}


class TestResourcesPromptContractIncludesUrl:
    def test_openrouter_contract_mentions_url(self):
        assert '"url"' in resources_agent.OPENROUTER_CONTRACT_SUFFIX
        assert "Nunca inventes URLs" in resources_agent.OPENROUTER_CONTRACT_SUFFIX

    def test_deepseek_contract_mentions_url(self):
        assert '"url"' in resources_agent.DEEPSEEK_CONTRACT_SUFFIX
        assert "Nunca inventes URLs" in resources_agent.DEEPSEEK_CONTRACT_SUFFIX

    def test_gemini_response_schema_has_url_property_not_required(self):
        schema = resources_agent.RESPONSE_SCHEMA
        recurso_schema = schema.properties["ejes_tematicos"].items.properties["recursos"].items
        assert "url" in recurso_schema.properties
        assert recurso_schema.properties["url"].type.name == "STRING"
        assert "url" not in recurso_schema.required

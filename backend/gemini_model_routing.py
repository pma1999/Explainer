"""Canonical Gemini model IDs for the Explainer pipeline."""

MODEL_SEGMENTADOR = "gemini-3.1-flash-lite-preview"  # Gemini 3.1 Flash Lite — segmentation
MODEL_EXPLAINER   = "gemini-3.1-flash-lite-preview"  # Gemini 3.1 Flash Lite — explainer agent
MODEL_AGENTS      = "gemini-3.1-flash-lite-preview"  # Gemini 3.1 Flash Lite — recorrido & resources
MODEL_CLASSIFIER  = "gemini-3.1-flash-lite-preview"  # Gemini 3.1 Flash Lite — content-page classifier
# Structured JSON outputs: lower temperature reduces run-to-run variance and borderline flips.
# Classifier ≈ extraction; segmentador keeps slight flexibility for pedagogical judgment.
TEMPERATURE_PAGE_CLASSIFIER = 0.25
TEMPERATURE_SEGMENTADOR = 0.5
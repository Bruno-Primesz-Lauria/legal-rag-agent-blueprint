"""Roteador de intenções: decide o caminho ANTES de qualquer busca.

Regras determinísticas primeiro; o LLM só desempata (teto de poucos tokens).
Fail-safe fatiado:
  * dúvida entre conversa e legislação  -> `legal` (melhor buscar do que errar)
  * dúvida entre fora da política e fora do tema -> rota SEM busca
"""
from __future__ import annotations

import json
import re
from typing import Optional

INTENTS = ("legal", "expand", "reformulate", "smalltalk", "out_of_domain", "adversarial")
NO_RETRIEVAL_INTENTS = ("reformulate", "smalltalk", "out_of_domain", "adversarial")

_LEGAL_RE = re.compile(
    r"\b(?:lei|decreto|portaria|resolu[cç][aã]o|norma|ne-?\d+|artigo|art\.|item|"
    r"legisla[cç][aã]o|conformidade|escopo|obrigat[oó]ri[oa]|exig[eê]ncia)\b",
    re.IGNORECASE,
)
_ADVERSARIAL_RE = re.compile(
    r"(?:ignore|esque[cç]a|desconsidere)\s+(?:suas|as|todas)\s+(?:regras|instru[cç][oõ]es)|"
    r"system\s+prompt|jailbreak|finja\s+que|revele\s+(?:seu|o)\s+prompt|"
    r"sou\s+(?:o\s+)?administrador",
    re.IGNORECASE,
)
_OOD_RE = re.compile(
    r"\b(?:previs[aã]o\s+do\s+tempo|futebol|receita\s+de|piada|filme|hor[oó]scopo|"
    r"cota[cç][aã]o\s+do\s+d[oó]lar)\b",
    re.IGNORECASE,
)
_EXPAND_RE = re.compile(r"\b(?:detalh\w*|aprofund\w*|explique\s+melhor\s+o|mais\s+sobre)\b", re.IGNORECASE)
_REFORMULATE_RE = re.compile(
    r"\b(?:mais\s+simples|resuma|em\s+t[oó]picos|reformule|explique\s+de\s+outra\s+forma)\b",
    re.IGNORECASE,
)
_SMALLTALK_RE = re.compile(
    r"^\s*(?:oi|ol[aá]|bom\s+dia|boa\s+tarde|boa\s+noite|obrigad[oa]|valeu|tudo\s+bem)\b",
    re.IGNORECASE,
)


def classify_intent_rules(text: str, has_history: bool = False) -> Optional[str]:
    """Classifica por regras. `None` = ambíguo (o LLM desempata)."""
    text = (text or "").strip()
    if not text:
        return "smalltalk"
    if _ADVERSARIAL_RE.search(text):
        return "adversarial"
    legal = bool(_LEGAL_RE.search(text))
    if _EXPAND_RE.search(text) and (legal or has_history):
        return "expand"
    if _REFORMULATE_RE.search(text) and has_history:
        return "reformulate"
    if legal:
        return "legal"
    if _OOD_RE.search(text):
        return "out_of_domain"
    if _SMALLTALK_RE.match(text) and len(text) < 40:
        return "smalltalk"
    return None


def parse_intent_label(raw: str) -> Optional[str]:
    """Aceita `legal`, `"legal"` ou `{"intent": "legal"}` vindo do LLM."""
    text = (raw or "").strip()
    try:
        obj = json.loads(text)
        text = str(obj.get("intent", "")) if isinstance(obj, dict) else str(obj)
    except (json.JSONDecodeError, TypeError):
        pass
    lowered = text.lower()
    for intent in INTENTS:
        if re.search(rf"\b{intent}\b", lowered):
            return intent
    return None


def apply_sliced_fail_safe(intent: Optional[str], text: str) -> str:
    if _ADVERSARIAL_RE.search(text or ""):
        return "adversarial"
    if intent == "adversarial":  # o LLM sinalizou pedido fora da política: resposta sem busca
        return "out_of_domain"
    if intent in INTENTS:
        return intent
    return "legal"  # ambíguo e dentro da política: segue para a busca

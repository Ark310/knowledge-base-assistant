import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.classifier import (
    classify, QueryClass, ISSUE_ERROR, ISSUE_HOWTO, ISSUE_CONFIG, ISSUE_INCIDENT, ISSUE_GENERAL,
)


def test_error_question():
    c = classify("GetWebDeal returns a null buy amount error")
    assert c.is_error is True
    assert c.issue_type == ISSUE_ERROR

def test_howto_question():
    c = classify("How do I book a spot deal in TradeDesk?")
    assert c.issue_type == ISSUE_HOWTO
    assert c.products == ["tradedesk"]

def test_incident_takes_precedence_over_error():
    c = classify("incident: bank holiday booking failed")
    assert c.issue_type == ISSUE_INCIDENT
    assert c.is_error is True   # still error-ish for the widened rerank window

def test_ticket_ids_extracted():
    assert classify("ticket 75919").ticket_ids == ["75919"]
    assert classify("see bug #54000 and incident 41045").ticket_ids == ["54000", "41045"]

def test_two_products_detected():
    c = classify("FormFlow vs SalesHub differences")
    assert set(c.products) == {"formflow", "saleshub"}

def test_general_fallback():
    c = classify("tell me about dealing")
    assert c.issue_type == ISSUE_GENERAL
    assert c.is_error is False

def test_returns_queryclass():
    assert isinstance(classify("anything"), QueryClass)

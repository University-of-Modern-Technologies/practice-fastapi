"""Topic vocabulary: what is accepted, and what permission it demands."""

from __future__ import annotations

import pytest

from app.realtime.topics import (
    MAX_TOPIC_LENGTH,
    collection_topic_for_entity,
    deal_topic,
    deals_topic,
    entity_topic,
    is_realtime_topic,
    order_topic,
    orders_topic,
    parse_realtime_topic,
    topic_permission_requirement,
)


def test_collection_topics_are_parsed() -> None:
    parsed = parse_realtime_topic(deals_topic())

    assert parsed is not None
    assert parsed.kind == "collection"
    assert parsed.topic == "deals"
    assert parsed.entity_type is None


def test_entity_topic_round_trips() -> None:
    parsed = parse_realtime_topic(deal_topic("clx123"))

    assert parsed is not None
    assert parsed.kind == "entity"
    assert parsed.topic == "entity:deal:clx123"
    assert parsed.entity_type == "deal"
    assert parsed.entity_id == "clx123"


def test_builders_match_the_vocabulary() -> None:
    assert orders_topic() == "orders"
    assert order_topic("o-1") == "entity:order:o-1"
    assert entity_topic("contact", "c_1") == "entity:contact:c_1"


@pytest.mark.parametrize(
    "topic",
    [
        "",
        "contacts",
        "users",
        "deal",
        "entity:deal",
        "entity:deal:clx:extra",
        "entity:invoice:1",
        "entity:deal:",
        "entity:deal:bad id",
        "entity:deal:bad/id",
        "ENTITY:deal:1",
    ],
)
def test_unknown_topics_are_rejected(topic: str) -> None:
    assert parse_realtime_topic(topic) is None
    assert is_realtime_topic(topic) is False


def test_topic_length_is_bounded() -> None:
    too_long = "entity:deal:" + "a" * 65

    assert parse_realtime_topic(too_long) is None
    assert len("entity:deal:" + "a" * 64) <= MAX_TOPIC_LENGTH


def test_entity_ids_are_bounded_to_64_characters() -> None:
    assert parse_realtime_topic("entity:deal:" + "a" * 64) is not None
    assert parse_realtime_topic("entity:deal:" + "a" * 65) is None


def test_collection_topic_for_entity_only_exists_for_deals_and_orders() -> None:
    assert collection_topic_for_entity("deal") == "deals"
    assert collection_topic_for_entity("order") == "orders"
    # Contacts and users are broadcast per entity only: nobody follows the
    # whole table.
    assert collection_topic_for_entity("contact") is None
    assert collection_topic_for_entity("user") is None
    assert collection_topic_for_entity("invoice") is None


@pytest.mark.parametrize(
    ("topic", "resource"),
    [
        ("deals", "deals"),
        ("orders", "orders"),
        ("entity:deal:1", "deals"),
        ("entity:order:1", "orders"),
        ("entity:contact:1", "contacts"),
        ("entity:user:1", "users"),
    ],
)
def test_topic_permission_requirement_maps_onto_rbac(topic: str, resource: str) -> None:
    requirement = topic_permission_requirement(topic)

    assert requirement is not None
    assert requirement.resource == resource
    assert requirement.action == "read"


def test_topic_permission_requirement_is_none_for_unknown_topics() -> None:
    assert topic_permission_requirement("entity:invoice:1") is None

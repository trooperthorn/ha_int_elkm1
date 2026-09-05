"""Unit tests for the base contract every ELK-M1 element type relies on:
`helpers/elk/notify.py`'s `Notifier` and `helpers/elk/elements.py`'s
`Element`/`Elements`. Closes a gap left by the 2026-09-05 elkm1-lib removal
(see docs/decisions.md) - these classes were previously only exercised
indirectly through platform tests that construct a handful of real Zone
objects, not through dedicated tests of the shared base classes themselves.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.helpers.elk.const import TextDescriptions
from custom_components.elkm1.helpers.elk.elements import Element, Elements
from custom_components.elkm1.helpers.elk.notify import Notifier

# --------------------------------------------------------------------------
# Notifier
# --------------------------------------------------------------------------


def test_notify_calls_every_attached_handler_with_the_payload_as_kwargs():
    notifier = Notifier()
    calls = []
    notifier.attach("AS", lambda **kwargs: calls.append(kwargs))

    notifier.notify("AS", {"armed_statuses": [1, 2]})

    assert calls == [{"armed_statuses": [1, 2]}]


def test_notify_is_a_no_op_for_an_unregistered_type():
    notifier = Notifier()
    notifier.notify("XYZ", {})  # must not raise


def test_attach_does_not_register_the_same_handler_twice():
    notifier = Notifier()
    calls = []
    handler = lambda **_: calls.append(1)  # noqa: E731
    notifier.attach("AS", handler)
    notifier.attach("AS", handler)

    notifier.notify("AS", {})

    assert calls == [1]


def test_detach_removes_a_handler():
    notifier = Notifier()
    calls = []
    handler = lambda **_: calls.append(1)  # noqa: E731
    notifier.attach("AS", handler)
    notifier.detach("AS", handler)

    notifier.notify("AS", {})

    assert calls == []


def test_detach_of_an_unregistered_handler_is_a_no_op():
    notifier = Notifier()
    notifier.detach("AS", lambda **_: None)  # must not raise


def test_notify_swallows_one_handlers_exception_and_still_calls_the_rest():
    """A bad handler must not break dispatch to the others (see notify.py's
    own comment) - critical since a bug in one entity's callback must not
    silently stop every other entity from updating."""
    notifier = Notifier()
    calls = []

    def _bad(**_kwargs) -> None:
        raise RuntimeError("boom")

    notifier.attach("AS", _bad)
    notifier.attach("AS", lambda **_: calls.append("second"))

    notifier.notify("AS", {})

    assert calls == ["second"]


def test_notify_tolerates_a_handler_that_detaches_itself_during_dispatch():
    """The handler list is copied before iterating, so a handler removing
    itself (a common one-shot pattern, e.g. `Elk._sync_complete`) must not
    skip or crash on the remaining handlers."""
    notifier = Notifier()
    calls = []

    def _self_removing(**_kwargs) -> None:
        notifier.detach("UA", _self_removing)
        calls.append("first")

    notifier.attach("UA", _self_removing)
    notifier.attach("UA", lambda **_: calls.append("second"))

    notifier.notify("UA", {})

    assert calls == ["first", "second"]
    assert notifier._observers["UA"] == [notifier._observers["UA"][0]]


# --------------------------------------------------------------------------
# Element
# --------------------------------------------------------------------------


def _element(index: int = 0) -> Element:
    return Element(index, MagicMock(), MagicMock())


def test_default_name_uses_the_subclass_name_and_one_based_index():
    element = _element(4)
    assert element.default_name() == "Element-005"


def test_is_default_name_true_before_any_real_name_arrives():
    element = _element()
    assert element.is_default_name() is True


def test_is_default_name_false_after_a_real_name_is_set():
    element = _element()
    element.setattr("name", "Front Door")
    assert element.is_default_name() is False


def test_configured_defaults_false_and_reflects_the_private_flag():
    element = _element()
    assert element.configured is False
    element._configured = True
    assert element.configured is True


def test_setattr_only_fires_callbacks_when_the_value_actually_changes():
    element = _element()
    calls = []
    element.add_callback(lambda el, changeset: calls.append(dict(changeset)))

    element.setattr("status", 5)
    element.setattr("status", 5)  # unchanged - must not fire again
    element.setattr("status", 6)

    assert calls == [{"status": 5}, {"status": 6}]


def test_setattr_batches_multiple_attrs_before_firing_with_close_the_changeset_false():
    element = _element()
    calls = []
    element.add_callback(lambda el, changeset: calls.append(dict(changeset)))

    element.setattr("a", 1, close_the_changeset=False)
    element.setattr("b", 2, close_the_changeset=False)
    assert calls == []  # nothing fired yet
    element.setattr("c", 3)  # closes the batch

    assert calls == [{"a": 1, "b": 2, "c": 3}]


def test_remove_callback_stops_further_notifications():
    element = _element()
    calls = []
    callback = lambda el, changeset: calls.append(1)  # noqa: E731
    element.add_callback(callback)
    element.remove_callback(callback)

    element.setattr("status", 5)

    assert calls == []


def test_as_dict_excludes_private_attributes():
    element = _element()
    element.setattr("status", 1)
    as_dict = element.as_dict()
    assert "status" in as_dict
    assert "name" in as_dict
    assert not any(key.startswith("_") for key in as_dict)


def test_str_includes_index_and_name_but_not_the_name_key_twice():
    element = _element(2)
    element.setattr("status", 7)
    text = str(element)
    assert text.startswith("2 'Element-003'")
    assert "status:7" in text


# --------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------


class _ConcreteElements(Elements[Element]):
    """Minimal concrete subclass - `Elements.sync` is abstract."""

    def sync(self) -> None:
        pass


def _make_elements(max_elements: int = 4) -> tuple[_ConcreteElements, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    collection = _ConcreteElements(connection, notifier, Element, max_elements)
    return collection, connection, notifier


def test_elements_constructs_max_elements_instances():
    collection, _connection, _notifier = _make_elements(4)
    assert len(collection) == 4
    assert all(isinstance(e, Element) for e in collection)
    assert [e.index for e in collection] == [0, 1, 2, 3]


def test_elements_getitem_and_iteration():
    collection, _connection, _notifier = _make_elements(3)
    assert collection[1] is collection.elements[1]
    assert list(collection) == collection.elements


def test_get_descriptions_sends_sd_for_unit_zero():
    collection, connection, _notifier = _make_elements(2)
    text_desc = TextDescriptions.ZONE.value

    collection.get_descriptions(text_desc)

    connection.send.assert_called_once()
    sent = connection.send.call_args[0][0]
    assert sent.message[2:4] == "sd"


def test_sd_handler_ignores_a_different_desc_type():
    collection, connection, notifier = _make_elements(2)
    collection.get_descriptions(TextDescriptions.ZONE.value)
    connection.reset_mock()

    other_desc_type = TextDescriptions.ZONE.value.desc_type + 1
    notifier.notify(
        "SD", {"desc_type": other_desc_type, "unit": 0, "desc": "Ignored", "show_on_keypad": False}
    )

    assert collection[0].name == collection[0].default_name()
    connection.send.assert_not_called()


def test_sd_handler_sets_name_and_requests_the_next_unit():
    collection, connection, notifier = _make_elements(2)
    text_desc = TextDescriptions.ZONE.value
    collection.get_descriptions(text_desc)
    connection.reset_mock()

    notifier.notify(
        "SD",
        {"desc_type": text_desc.desc_type, "unit": 0, "desc": "Front Door", "show_on_keypad": False},
    )

    assert collection[0].name == "Front Door"
    assert collection[0].configured is True
    connection.send.assert_called_once()
    _args, kwargs = connection.send.call_args
    assert kwargs == {"priority_send": True}


def test_sd_handler_stops_the_sync_once_unit_is_out_of_range():
    collection, connection, notifier = _make_elements(2)
    text_desc = TextDescriptions.ZONE.value
    collection.get_descriptions(text_desc)
    connection.reset_mock()

    notifier.notify(
        "SD",
        {
            "desc_type": text_desc.desc_type,
            "unit": text_desc.number_descriptions,
            "desc": "Past the end",
            "show_on_keypad": False,
        },
    )

    connection.send.assert_not_called()
    # A later, unrelated SD for this desc_type must now be ignored too.
    notifier.notify(
        "SD",
        {"desc_type": text_desc.desc_type, "unit": 0, "desc": "Too late", "show_on_keypad": False},
    )
    assert collection[0].name == collection[0].default_name()


def test_sd_handler_skips_naming_an_auto_generated_user_placeholder():
    """USER descriptions matching the panel's own "USER 001"-style
    placeholder pattern are not treated as a real name (see `_sd_handler`'s
    own `re.match` check) - the sync still continues to the next unit."""
    collection, connection, notifier = _make_elements(2)
    text_desc = TextDescriptions.USER.value
    collection.get_descriptions(text_desc)
    connection.reset_mock()

    notifier.notify(
        "SD",
        {"desc_type": text_desc.desc_type, "unit": 0, "desc": "USER 001", "show_on_keypad": False},
    )

    assert collection[0].name == collection[0].default_name()
    assert collection[0].configured is False
    connection.send.assert_called_once()  # still requests the next unit


def test_sd_handler_does_name_a_real_user_description():
    collection, connection, notifier = _make_elements(2)
    text_desc = TextDescriptions.USER.value
    collection.get_descriptions(text_desc)
    connection.reset_mock()

    notifier.notify(
        "SD",
        {"desc_type": text_desc.desc_type, "unit": 0, "desc": "Sean", "show_on_keypad": False},
    )

    assert collection[0].name == "Sean"
    assert collection[0].configured is True

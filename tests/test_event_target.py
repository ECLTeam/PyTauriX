from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pytaurix import BindingError, EventTarget
from pytaurix.ffi import EventTarget as FfiEventTarget


def test_event_target_imports_and_immutable_labels() -> None:
    assert FfiEventTarget is EventTarget
    target = EventTarget.WebviewWindow("迁移🌟")
    assert target.label == "迁移🌟"
    with pytest.raises(FrozenInstanceError):
        target.label = "replacement"  # type: ignore[misc]
    assert EventTarget.Window("same") != EventTarget.Webview("same")


@pytest.mark.parametrize(
    "variant", [EventTarget.AnyLabel, EventTarget.Window, EventTarget.Webview, EventTarget.WebviewWindow]
)
@pytest.mark.parametrize("label", [None, 3, "nul\0label"])
def test_invalid_target_label_is_rejected(variant: type, label: object) -> None:
    with pytest.raises(BindingError, match="invalid_target"):
        variant(label)

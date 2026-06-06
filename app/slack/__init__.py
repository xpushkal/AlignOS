"""Slack integration layer for AlignOS.

`cards` builds Block Kit payloads (pure, testable). `handlers.register` wires a
Slack Bolt AsyncApp to the agent flows. The Bolt app is created lazily so the
package imports without Slack credentials present.
"""
from . import cards

__all__ = ["cards"]

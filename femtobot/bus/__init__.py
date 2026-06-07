"""Message bus module for decoupled channel-agent communication."""

from femtobot.bus.events import InboundMessage, OutboundMessage
from femtobot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]

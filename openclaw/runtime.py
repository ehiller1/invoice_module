"""Phase 12: OpenClaw Cabinet Runtime Orchestrator.

Manages cabinet member processes, subscribes to perturbation channels,
and coordinates cabinet-agent interaction.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass

from backend.membrane.transport.base import MessageTransport

logger = logging.getLogger(__name__)


@dataclass
class CabinetMember:
    """Cabinet member definition."""
    principal_id: str  # e.g., "queue-guardian", "decision-deputy"
    role: str  # e.g., "sentinel", "drafter", "monitor", "screener"
    channels: list[str]  # Channels this member subscribes to
    runner: Optional[Callable] = None  # Async runner function


class CabinetRuntime:
    """OpenClaw Cabinet Runtime — orchestrates autonomous cabinet members.

    Manages:
    - Subscription to perturbation channels
    - Async runner tasks for each cabinet member
    - Signal routing and event dispatch
    - Lifecycle management (start, stop, health)
    """

    def __init__(self, transport: MessageTransport):
        self.transport = transport
        self.members: Dict[str, CabinetMember] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.running = False

    def register_member(
        self,
        principal_id: str,
        role: str,
        channels: list[str],
        runner: Callable,
    ) -> None:
        """Register a cabinet member.

        Args:
            principal_id: Unique ID (e.g., "queue-guardian")
            role: Member role (sentinel, drafter, monitor, screener)
            channels: List of channels to subscribe to
            runner: Async callable that runs the member
        """
        self.members[principal_id] = CabinetMember(
            principal_id=principal_id,
            role=role,
            channels=channels,
            runner=runner,
        )
        logger.info(
            f"Registered cabinet member {principal_id} (role: {role}) "
            f"subscribing to {len(channels)} channel(s)"
        )

    async def start(self) -> None:
        """Start all cabinet member runners."""
        if self.running:
            logger.warning("Cabinet runtime already running")
            return

        self.running = True
        logger.info(f"Starting cabinet runtime with {len(self.members)} members")

        for principal_id, member in self.members.items():
            if member.runner:
                # Create task for this member
                task = asyncio.create_task(
                    self._run_member_with_restart(principal_id, member)
                )
                self.tasks[principal_id] = task
                logger.info(f"Started task for {principal_id}")

        # Wait for all tasks
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def _run_member_with_restart(
        self, principal_id: str, member: CabinetMember
    ) -> None:
        """Run a cabinet member with auto-restart on crash."""
        if member.runner is None:
            logger.error(f"{principal_id} has no runner, cannot start")
            return

        restart_count = 0
        max_restarts = 5

        while self.running and restart_count < max_restarts:
            try:
                logger.info(f"Running {principal_id}")
                await member.runner(self.transport, member.channels)
            except Exception as e:
                restart_count += 1
                logger.error(
                    f"{principal_id} crashed: {e}. Restart {restart_count}/{max_restarts}"
                )
                if restart_count < max_restarts:
                    # Exponential backoff
                    backoff = 2 ** min(restart_count, 4)
                    await asyncio.sleep(backoff)
                    logger.info(f"Restarting {principal_id}")

        if restart_count >= max_restarts:
            logger.error(f"{principal_id} exceeded max restarts, giving up")

    def stop(self) -> None:
        """Stop all cabinet member runners."""
        logger.info("Stopping cabinet runtime")
        self.running = False
        for task in self.tasks.values():
            task.cancel()

    async def health(self) -> Dict[str, Any]:
        """Health check for cabinet runtime.

        Returns:
            Dict with runtime status and member statuses
        """
        member_statuses = {}
        for principal_id, task in self.tasks.items():
            member_statuses[principal_id] = {
                "running": not task.done(),
                "cancelled": task.cancelled(),
            }

        return {
            "running": self.running,
            "members": len(self.members),
            "active_tasks": len([t for t in self.tasks.values() if not t.done()]),
            "member_statuses": member_statuses,
        }


# Global runtime singleton
_runtime: Optional[CabinetRuntime] = None


def get_cabinet_runtime() -> CabinetRuntime:
    """Get or create cabinet runtime singleton."""
    global _runtime
    if _runtime is None:
        from backend.membrane.transport import get_transport
        _runtime = CabinetRuntime(get_transport())
    return _runtime


def init_cabinet_runtime(runtime: CabinetRuntime) -> None:
    """Initialize cabinet runtime singleton."""
    global _runtime
    _runtime = runtime

"""foreshadow-pipeline — an agent film studio that turns near-miss incident
reports into budget-optimal, provenance-signed cinematic safety films.

Public toolkit surface (COMPLEXITY.md section 4):
    Screenwriter, LineProducer(budget), RenderOrchestrator, QCCritic,
    ProvenanceLedger, Manifest (with .load / .verify), FakeQwen / LiveQwen.
"""

from .agents.line_producer import LineProducer
from .agents.qc import QCCritic
from .agents.screenwriter import Screenwriter
from .provenance import KillSwitchTripped, ProvenanceLedger, VerifyReport, verify_manifest
from .qwen import FakeQwen, LiveQwen, QwenTransport
from .render.orchestrator import RenderOrchestrator
from .schemas import (
    Allocation,
    BudgetDecision,
    Manifest,
    ManifestLeaf,
    QCVerdict,
    RegretRow,
    Screenplay,
    Shot,
    ShotPlan,
)

__version__ = "1.2.0"

__all__ = [
    "__version__",
    "Screenwriter",
    "LineProducer",
    "RenderOrchestrator",
    "QCCritic",
    "ProvenanceLedger",
    "KillSwitchTripped",
    "VerifyReport",
    "verify_manifest",
    "Manifest",
    "ManifestLeaf",
    "Screenplay",
    "ShotPlan",
    "Shot",
    "Allocation",
    "BudgetDecision",
    "RegretRow",
    "QCVerdict",
    "QwenTransport",
    "FakeQwen",
    "LiveQwen",
]

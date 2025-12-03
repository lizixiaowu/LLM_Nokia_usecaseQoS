from pydantic import BaseModel, Field
from typing import Dict, Any, Literal

# --- Core A2A/Agent Card Models ---

class CapabilityParameter(BaseModel):
    # Parameter for capability description
    type: Literal["string", "number", "object"] = "string"
    description: str = ""

class Capability(BaseModel):
    # Description of an agent's capability
    description: str
    parameters: Dict[str, CapabilityParameter] = Field(default_factory=dict)
    returns: Dict[str, CapabilityParameter] = Field(default_factory=dict)

class AgentCard(BaseModel):
    # Agent Card structure (metadata for discovery)
    version: str = "1.0"
    name: str
    description: str
    endpoint: str  # e.g., http://localhost:8001/a2a
    authentication: Dict[str, Any] = Field(default_factory=lambda: {"type": "none"})
    capabilities: Dict[str, Capability]

class A2AMessage(BaseModel):
    # A2A protocol message structure
    sender_id: str
    receiver_id: str
    content_type: str = "application/json"
    payload: Dict[str, Any]

# --- Business Data Models ---

class AlarmData(BaseModel):
    # Output of QoS Monitoring Agent
    alarm_id: str
    metric: str
    value: float
    threshold: float
    timestamp: str
    root_cause_hint: str = "High traffic causing latency."

class RemediationPlan(BaseModel):
    # Output of QoS Remediation Agent
    plan_id: str
    device_id: str
    priority: int
    actions: Dict[str, Any]

class CLIConfig(BaseModel):
    # Output of Config Generation Agent
    cli_text: str
    device_type: str = "Cisco"

class ValidationResult(BaseModel):
    # Output of Config Validation Agent
    is_valid: bool
    report: str

class ExecutionStatus(BaseModel):
    # Output of Config Execution Agent
    status: Literal["Success", "Failure", "Rollback"]
    log: str
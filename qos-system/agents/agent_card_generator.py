from models.a2a_models import AgentCard, Capability, CapabilityParameter
from typing import Dict

AGENT_CONFIGS: Dict[str, Dict] = {
    # ----------------------------------------------------
    # 1. QoS Monitor Agent (ADK) - Port: 8001
    # ----------------------------------------------------
    "QoS Monitor Agent": {
        "port": 8001,
        "description": "触发器：持续监控时序DB，QoS劣化时发送结构化告警。",
        "capability": "monitor_and_alarm",
        "params": {},
        "returns": {"alarm_data": CapabilityParameter(description="结构化告警数据")}
    },
    # ----------------------------------------------------
    # 2. QoS Remediation Agent (LangGraph) - Port: 8002
    # ----------------------------------------------------
    "QoS Remediation Agent": {
        "port": 8002,
        "description": "决策者：根据告警和网络拓扑，制定高层 JSON 修复方案。",
        "capability": "generate_remediation_plan",
        "params": {
            "alarm_data": CapabilityParameter(description="结构化告警数据"),
            "topology": CapabilityParameter(description="网络拓扑信息")
        },
        "returns": {"remediation_plan": CapabilityParameter(description="高层 JSON 修复方案")}
    },
    # ----------------------------------------------------
    # 3. Config Generation Agent (ADK) - Port: 8003
    # ----------------------------------------------------
    "Config Generation Agent": {
        "port": 8003,
        "description": "转换器：将 JSON 修复方案转换为目标设备 CLI 配置文本。",
        "capability": "generate_cli_config",
        "params": {"remediation_plan": CapabilityParameter(description="高层 JSON 修复方案")},
        "returns": {"cli_config": CapabilityParameter(description="目标设备 CLI 配置文本")}
    },
    # ----------------------------------------------------
    # 4. Config Validation Agent (ADK) - Port: 8004
    # ----------------------------------------------------
    "Config Validation Agent": {
        "port": 8004,
        "description": "质量控制：检查配置的语法和合规性。",
        "capability": "validate_config",
        "params": {"cli_config": CapabilityParameter(description="CLI 配置文本")},
        "returns": {"validation_result": CapabilityParameter(description="验证结果和报告")}
    },
    # ----------------------------------------------------
    # 5. Config Execution Agent (ADK) - Port: 8005
    # ----------------------------------------------------
    "Config Execution Agent": {
        "port": 8005,
        "description": "实施者：通过 MCP 接口部署配置。",
        "capability": "execute_config",
        "params": {"cli_config": CapabilityParameter(description="CLI 配置文本")},
        "returns": {"execution_status": CapabilityParameter(description="配置部署状态")}
    },
    # ----------------------------------------------------
    # 6. Orchestration Agent (ADK Orchestration) - Port: 8006
    # ----------------------------------------------------
    "Orchestration Agent": {
        "port": 8006,
        "description": "编排者：使用 ADK 的编排功能，实现一个“Chain”来顺序调用其他智能体。",
        "capability": "start_qos_chain",
        "params": {"initial_trigger": CapabilityParameter(description="启动信号，可为空")},
        "returns": {"final_report": CapabilityParameter(description="流程最终报告")}
    },
}

def generate_agent_card(name: str, port: int, description: str, capability_name: str, params: Dict, returns: Dict) -> AgentCard:
    """Generates the Agent Card object."""
    return AgentCard(
        name=name,
        description=description,
        endpoint=f"http://localhost:{port}/a2a",
        capabilities={
            capability_name: Capability(
                description=description,
                parameters={k: CapabilityParameter(**v.dict()) for k, v in params.items()},
                returns={k: CapabilityParameter(**v.dict()) for k, v in returns.items()}
            )
        }
    )
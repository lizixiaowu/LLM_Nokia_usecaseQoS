import uvicorn
import json
import os
from .adk_base_agent import OrchestratorBaseAgent
from .agent_card_generator import AGENT_CONFIGS, generate_agent_card
from models.a2a_models import AlarmData, RemediationPlan, CLIConfig, ValidationResult, ExecutionStatus
from typing import Dict, Any, Union
import time
import requests.exceptions

AGENT_NAME = "Orchestration Agent"
CONFIG = AGENT_CONFIGS[AGENT_NAME]
# External Agent Card URLs (Ports 8001-8005)
AGENT_URLS = {
    "QoS Monitor Agent": "http://localhost:8001/.well-known/agent.json",
    "QoS Remediation Agent": "http://localhost:8002/.well-known/agent.json",
    "Config Generation Agent": "http://localhost:8003/.well-known/agent.json",
    "Config Validation Agent": "http://localhost:8004/.well-known/agent.json",
    "Config Execution Agent": "http://localhost:8005/.well-known/agent.json",
}

class OrchestrationAgent(OrchestratorBaseAgent):
    """ADK Dedicated Class for QoS System Orchestration (Chain)"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 修正：如果加载拓扑失败，会抛出异常并中止启动
        self.topology = self._load_topology()
        
        # Start Agent Discovery with Retries
        print(f"[{self.agent_name}] Starting Agent Discovery...")
        
        # <<< 关键修正区域：用 try-except 包裹整个循环 >>>
        for name, url in AGENT_URLS.items():
            try:
                self.discover_agent(url)
            except ConnectionError as e:
                print(f"[{self.agent_name}] Discovery FAILED for {name}. Error: {e}")
                # 即使发现失败，__init__ 也不应抛出异常，确保服务器启动。

        print(f"[{self.agent_name}] Agent Discovery Complete. Found: {list(self.known_agents.keys())}")

    def _load_topology(self) -> Dict[str, Any]:
        """
        Loads mock network topology data. If loading fails, raises an exception
        to prevent the Orchestrator from starting with critical missing data.
        """
        try:
            with open('topology.json', 'r') as f:
                return json.load(f)
        except Exception as e:
            # 修正后的逻辑：无法加载拓扑文件是致命错误，应该立即抛出。
            error_msg = f"FATAL ERROR: Failed to load critical topology.json file: {e}"
            print(error_msg)
            # 抛出异常，阻止 Orchestrator 正常实例化
            raise FileNotFoundError(error_msg) 

    def process_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the QoS repair Chain by calling other agents sequentially."""
        
        # 1. Trigger QoS Monitor Agent
        print("\n--- Step 1: Triggering QoS Monitor Agent ---")
        
        # 检查是否所有依赖都已发现 (Pre-Check 1)
        if "QoS Monitor Agent" not in self.known_agents:
             return self._handle_chain_failure("QoS Monitor Agent is offline (not discovered)", "Pre-Check")

        try:
            # FIX: Use model_dump() when calling
            monitor_result = self.call_agent_capability("QoS Monitor Agent", "monitor_and_alarm", **payload.get('params', {}))
            alarm_data = AlarmData(**monitor_result["alarm_data"])
            print(f"Alarm received: {alarm_data.alarm_id} ({alarm_data.metric})")
        except (ConnectionError, requests.exceptions.HTTPError, KeyError) as e:
            return self._handle_chain_failure(e, "QoS Monitor Agent")

        # 2. Call QoS Remediation Agent (LangGraph)
        print("\n--- Step 2: Calling QoS Remediation Agent (Decision Maker) ---")
        if "QoS Remediation Agent" not in self.known_agents:
             return self._handle_chain_failure("QoS Remediation Agent is offline (not discovered)", "Pre-Check")
             
        try:
            # FIX: Use model_dump() for structured input
            remediation_result = self.call_agent_capability(
                "QoS Remediation Agent", 
                "generate_remediation_plan", 
                alarm_data=alarm_data.model_dump(), 
                topology=self.topology
            )
            remediation_plan = RemediationPlan(**remediation_result["remediation_plan"])
            print(f"Remediation Plan generated: {remediation_plan.plan_id}")
        except (ConnectionError, requests.exceptions.HTTPError, KeyError) as e:
            return self._handle_chain_failure(e, "QoS Remediation Agent")

        # 3. Call Config Generation Agent (Transformer)
        print("\n--- Step 3: Calling Config Generation Agent (Transformer) ---")
        if "Config Generation Agent" not in self.known_agents:
             return self._handle_chain_failure("Config Generation Agent is offline (not discovered)", "Pre-Check")

        try:
            # FIX: Use model_dump() for structured input
            generator_result = self.call_agent_capability(
                "Config Generation Agent",
                "generate_cli_config",
                remediation_plan=remediation_plan.model_dump()
            )
            cli_config = CLIConfig(**generator_result["cli_config"])
            print(f"CLI Config generated: {cli_config.cli_text.strip().splitlines()[0]}...")
        except (ConnectionError, requests.exceptions.HTTPError, KeyError) as e:
            return self._handle_chain_failure(e, "Config Generation Agent")

        # 4. Call Config Validation Agent (Quality Control)
        print("\n--- Step 4: Calling Config Validation Agent (Quality Control) ---")
        if "Config Validation Agent" not in self.known_agents:
             return self._handle_chain_failure("Config Validation Agent is offline (not discovered)", "Pre-Check")

        try:
            # FIX: Use model_dump() for structured input
            validation_result = self.call_agent_capability(
                "Config Validation Agent",
                "validate_config",
                cli_config=cli_config.model_dump()
            )
            validation = ValidationResult(**validation_result["validation_result"])
            print(f"Config Validation Result: {validation.is_valid}")
            
            if not validation.is_valid:
                return self._handle_chain_failure(f"Validation Failed: {validation.report}", "Config Validation Agent")

        except (ConnectionError, requests.exceptions.HTTPError, KeyError) as e:
            return self._handle_chain_failure(e, "Config Validation Agent")

        # 5. Call Config Execution Agent (Executor)
        print("\n--- Step 5: Calling Config Execution Agent (Executor) ---")
        if "Config Execution Agent" not in self.known_agents:
             return self._handle_chain_failure("Config Execution Agent is offline (not discovered)", "Pre-Check")

        try:
            # FIX: Use model_dump() for structured input
            executor_result = self.call_agent_capability(
                "Config Execution Agent",
                "execute_config",
                cli_config=cli_config.model_dump()
            )
            execution_status = ExecutionStatus(**executor_result["execution_status"])
            print(f"Config Execution Status: {execution_status.status}")

        except (ConnectionError, requests.exceptions.HTTPError, KeyError) as e:
            return self._handle_chain_failure(e, "Config Execution Agent")
        
        # 6. Reporting (Aggregated by Orchestrator)
        final_report = {
            "status": "QoS_FIX_SUCCESS",
            "message": f"QoS repair chain completed successfully. Execution status: {execution_status.status}.",
            "details": {
                "alarm_id": alarm_data.alarm_id,
                "plan_id": remediation_plan.plan_id,
                "deployed_config": cli_config.cli_text
            }
        }
        print("\n--- Step 6: Final Report Generated ---")
        print(json.dumps(final_report, indent=2))
        return {"final_report": final_report}

    def _handle_chain_failure(self, error: Any, failed_agent: str) -> Dict[str, Any]:
        """Handles chain failure, aborts subsequent steps, and returns a failure report."""
        print(f"\n--- CHAIN ABORTED ---")
        print(f"Failure at {failed_agent}: {error}")
        
        failure_report = {
            "status": "QoS_FIX_FAILURE",
            "message": f"QoS repair chain failed at {failed_agent}. Error: {str(error)}",
            "failed_step": failed_agent
        }
        return {"final_report": failure_report}


card = generate_agent_card(AGENT_NAME, CONFIG["port"], CONFIG["description"], CONFIG["capability"], CONFIG["params"], CONFIG["returns"])
agent = OrchestrationAgent(AGENT_NAME, "localhost", CONFIG["port"], card)

if __name__ == "__main__":
    print(f"Starting {AGENT_NAME} on port {CONFIG['port']}...")
    uvicorn.run(agent.app, host=agent.host, port=agent.port)
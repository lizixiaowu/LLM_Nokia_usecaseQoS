import uvicorn
from .adk_base_agent import ADKA2ABaseAgent
from .agent_card_generator import AGENT_CONFIGS, generate_agent_card
from models.a2a_models import CLIConfig, ExecutionStatus
from typing import Dict, Any
import time

AGENT_NAME = "Config Execution Agent"
CONFIG = AGENT_CONFIGS[AGENT_NAME]

class ConfigExecutionAgent(ADKA2ABaseAgent):
    """ADK Dedicated Class for Configuration Execution (Executor)"""

    def process_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        params = payload.get("params", {})
        cli_config_dict = params.get("cli_config")
        if not cli_config_dict:
            raise ValueError("Missing cli_config in payload.")
            
        cli_config = CLIConfig(**cli_config_dict)
        
        print(f"[{self.agent_name}] Executing configuration on device {cli_config.device_type} via MCP API...")
        time.sleep(2) # Simulate deployment delay
        
        # Simulate execution result
        if "write memory" in cli_config.cli_text:
            status = "Success"
            log = f"Successfully deployed and saved config to device."
        else:
            status = "Failure"
            log = "Deployment failed: Configuration persistence command missing."
        
        execution_status = ExecutionStatus(
            status=status,
            log=log
        )
        
        return {"execution_status": execution_status.dict()}

card = generate_agent_card(AGENT_NAME, CONFIG["port"], CONFIG["description"], CONFIG["capability"], CONFIG["params"], CONFIG["returns"])
agent = ConfigExecutionAgent(AGENT_NAME, "localhost", CONFIG["port"], card)

if __name__ == "__main__":
    print(f"Starting {AGENT_NAME} on port {CONFIG['port']}...")
    uvicorn.run(agent.app, host=agent.host, port=agent.port)
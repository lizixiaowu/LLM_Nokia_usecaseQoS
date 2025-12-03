import uvicorn
from .adk_base_agent import ADKA2ABaseAgent
from .agent_card_generator import AGENT_CONFIGS, generate_agent_card
from models.a2a_models import AlarmData
from typing import Dict, Any

AGENT_NAME = "QoS Monitor Agent"
CONFIG = AGENT_CONFIGS[AGENT_NAME]

class QoSMonitorAgent(ADKA2ABaseAgent):
    """ADK Dedicated Class for QoS Monitoring (Trigger)"""

    def process_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Ignores input, this Agent simulates an external trigger and generates an alarm.
        print(f"[{self.agent_name}] Simulating QoS degradation and generating alarm.")
        
        # Simulate structured alarm data generation
        alarm = AlarmData(
            alarm_id="ALM-12345",
            metric="Latency",
            value=350.5,
            threshold=150.0,
            timestamp="2025-12-02T10:00:00Z"
        )
        
        # FIX: Use model_dump() for Pydantic V2 compatibility
        return {"alarm_data": alarm.model_dump()}

card = generate_agent_card(AGENT_NAME, CONFIG["port"], CONFIG["description"], CONFIG["capability"], CONFIG["params"], CONFIG["returns"])
agent = QoSMonitorAgent(AGENT_NAME, "localhost", CONFIG["port"], card)

if __name__ == "__main__":
    print(f"Starting {AGENT_NAME} on port {CONFIG['port']}...")
    uvicorn.run(agent.app, host=agent.host, port=agent.port)
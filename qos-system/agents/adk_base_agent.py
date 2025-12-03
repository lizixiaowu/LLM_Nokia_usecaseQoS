from abc import ABC, abstractmethod
from fastapi import FastAPI
from models.a2a_models import AgentCard, A2AMessage
from typing import Dict, Any
import requests
import json
import time

class ADKA2ABaseAgent(ABC):
    """
    Simulates the core functionalities of an ADK Dedicated Class and A2A server.
    All ADK agents (1, 3, 4, 5, 6) inherit from this.
    """
    
    def __init__(self, agent_name: str, host: str, port: int, card: AgentCard):
        self.agent_name = agent_name
        self.host = host
        self.port = port
        self.card = card
        self.app = FastAPI(title=f"{agent_name} A2A Server")
        
        # Setup A2A endpoint
        self.app.add_api_route("/a2a", self.handle_a2a_message, methods=["POST"])
        # Setup Agent Card endpoint
        self.app.add_api_route("/.well-known/agent.json", self.get_agent_card, methods=["GET"])
        
        print(f"[{agent_name}] Initialized at {self.card.endpoint}")

    def get_agent_card(self) -> AgentCard:
        """Exposes the Agent Card for discovery"""
        return self.card

    @abstractmethod
    def process_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Core business logic for the agent, must be implemented by subclasses."""
        pass

    def handle_a2a_message(self, message: A2AMessage) -> Dict[str, Any]:
        """Handles incoming A2A messages from the network."""
        capability_name = message.payload.get('capability', 'default')
        print(f"[{self.agent_name}] Received message from {message.sender_id} to execute {capability_name}")
        try:
            result = self.process_message(message.payload)
            return {"status": "success", "result": result}
        except Exception as e:
            print(f"[{self.agent_name}] Error processing message: {e}")
            return {"status": "failure", "error": str(e)}

    def send_a2a_message(self, receiver_card: AgentCard, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sends an A2A message to another Agent."""
        message = A2AMessage(
            sender_id=self.agent_name,
            receiver_id=receiver_card.name,
            payload=payload
        )
        print(f"[{self.agent_name}] Sending message to {receiver_card.name} at {receiver_card.endpoint}")
        try:
            response = requests.post(receiver_card.endpoint, json=message.dict(), timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Propagate communication failure up the chain
            print(f"[{self.agent_name}] Failed to send A2A message to {receiver_card.name}: {e}")
            raise ConnectionError(f"A2A communication failed with {receiver_card.name}: {e}")

# Orchestrator's specific base class
class OrchestratorBaseAgent(ADKA2ABaseAgent):
    """
    Simulates ADK Orchestration Class with robust discovery.
    Note: call_agent_capability is implemented here, accessible to the OrchestrationAgent subclass.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.known_agents: Dict[str, AgentCard] = {}
    
    def discover_agent(self, agent_card_url: str, max_retries: int = 7, delay: float = 1.5) -> AgentCard:
        """
        Attempts to discover an Agent Card with retry logic to handle
        concurrent startup ConnectionRefused errors.
        """
        for attempt in range(max_retries):
            try:
                print(f"[Orchestrator] Discovering Agent Card at {agent_card_url} (Attempt {attempt + 1}/{max_retries})")
                response = requests.get(agent_card_url, timeout=3)
                response.raise_for_status()
                
                card = AgentCard(**response.json())
                self.known_agents[card.name] = card
                print(f"[Orchestrator] Successfully discovered {card.name}")
                return card
            
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    time.sleep(delay)
                else:
                    raise ConnectionError(f"Failed to discover agent at {agent_card_url} after {max_retries} attempts. Error: {e}")

    def call_agent_capability(self, agent_name: str, capability_name: str, **kwargs) -> Dict[str, Any]:
        """
        Calls a specific capability on a discovered agent.
        This is the method used by the Orchestrator's Chain logic.
        """
        if agent_name not in self.known_agents:
            raise ValueError(f"Agent {agent_name} not discovered. Cannot call capability.")
        
        target_card = self.known_agents[agent_name]
        
        # Payload structure for A2A capability call
        payload = {
            "capability": capability_name,
            "params": kwargs
        }
        
        # This calls the inherited send_a2a_message
        response = self.send_a2a_message(target_card, payload)
        
        if response.get("status") == "success":
            return response.get("result", {})
        else:
            # Raise an HTTPError if the remote agent failed internally
            raise requests.exceptions.HTTPError(
                f"Remote agent {agent_name} failed execution: {response.get('error', 'Unknown remote error')}",
                response=requests.Response() # Use a placeholder response object
            )
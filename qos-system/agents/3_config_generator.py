import uvicorn
import json
from .adk_base_agent import ADKA2ABaseAgent
from .agent_card_generator import AGENT_CONFIGS, generate_agent_card
from models.a2a_models import RemediationPlan, CLIConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import Dict, Any
import os

AGENT_NAME = "Config Generation Agent"
CONFIG = AGENT_CONFIGS[AGENT_NAME]

class ConfigGenerationAgent(ADKA2ABaseAgent):
    """ADK Dedicated Class for Configuration Generation (Transformer)"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 初始化 Gemini
        self.llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY"))

    def process_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        params = payload.get("params", {})
        remediation_plan_dict = params.get("remediation_plan")
        if not remediation_plan_dict:
            raise ValueError("Missing remediation_plan in payload.")
            
        # 这里的转换主要是为了校验格式，实际发给 Prompt 可以直接用 dict
        remediation_plan = RemediationPlan(**remediation_plan_dict)
        
        print(f"[{self.agent_name}] Converting plan {remediation_plan.plan_id} to CLI text using Gemini.")
        
        # === NEW CODE START: 使用 Gemini 生成 ===
        prompt = f"""
        You are a Senior Network Engineer expert in Cisco IOS.
        
        [Input Data: Remediation Plan]
        {json.dumps(remediation_plan_dict, indent=2)}

        [Task]
        Convert the above Remediation Plan into specific Cisco IOS CLI commands.
        
        [Requirements]
        1. Target Device Type: Cisco
        2. Interface: Use the exact interface specified in the 'actions' section.
        3. QoS Policy: Apply the policy name specified in 'new_qos_level' to the interface (outbound direction).
        4. Syntax: Ensure commands are valid (e.g., 'configure terminal', 'interface ...', 'end', 'write memory').
        5. Output: You MUST return a valid JSON object matching the CLIConfig schema.
        """

        try:
            # 绑定输出结构，强制 LLM 返回 CLIConfig 对象
            structured_llm = self.llm.with_structured_output(CLIConfig)
            
            print(f"[{self.agent_name}] Invoking Gemini API... (Translating JSON to CLI)")
            generated_config = structured_llm.invoke(prompt)

            if not generated_config:
                raise ValueError("Gemini returned empty response.")

            # 调试打印，验证是不是真的生成了
            print(f"DEBUG: Gemini Generated CLI:\n{generated_config.cli_text}")

            # 使用 model_dump 替代 dict()
            return {"cli_config": generated_config.model_dump()}

        except Exception as e:
            print(f"[{self.agent_name}] Error generating config with Gemini: {e}")
            raise e
        # === NEW CODE END ===

card = generate_agent_card(AGENT_NAME, CONFIG["port"], CONFIG["description"], CONFIG["capability"], CONFIG["params"], CONFIG["returns"])
agent = ConfigGenerationAgent(AGENT_NAME, "localhost", CONFIG["port"], card)

if __name__ == "__main__":
    print(f"Starting {AGENT_NAME} on port {CONFIG['port']}...")
    uvicorn.run(agent.app, host=agent.host, port=agent.port)
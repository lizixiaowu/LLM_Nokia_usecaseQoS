import uvicorn
import json
from .adk_base_agent import ADKA2ABaseAgent
from .agent_card_generator import AGENT_CONFIGS, generate_agent_card
from models.a2a_models import CLIConfig, ValidationResult
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import Dict, Any
import os

AGENT_NAME = "Config Validation Agent"
CONFIG = AGENT_CONFIGS[AGENT_NAME]

class ConfigValidationAgent(ADKA2ABaseAgent):
    """ADK Dedicated Class for Configuration Validation (Quality Control)"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 初始化 Gemini
        self.llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY"))

    def process_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        params = payload.get("params", {})
        cli_config_dict = params.get("cli_config")
        if not cli_config_dict:
            raise ValueError("Missing cli_config in payload.")
            
        cli_config = CLIConfig(**cli_config_dict)
        
        print(f"[{self.agent_name}] Validating CLI config using Gemini.")
        
        # === 1. 构建 Prompt：让 Gemini 扮演代码审计员 ===
        prompt = f"""
        You are a Network Automation QA (Quality Assurance) Auditor.
        Your job is to validate the following generated network configuration before it is sent to a real device.

        [Input Configuration]
        Device Type: {cli_config.device_type}
        CLI Commands:
        '''
        {cli_config.cli_text}
        '''

        [Validation Criteria]
        1. **Syntax Check**: Are the commands valid for the specified device type (Cisco IOS)?
        2. **Safety Check**: Does the config contain dangerous commands (e.g., 'reload', 'shutdown' on critical links) without justification?
        3. **Completeness**: Does it enter configuration mode ('conf t') and exit properly ('end')?
        4. **Idempotency**: Does it save the config ('write memory' or 'copy run start')?

        [Output Requirement]
        Analyze the config and return a JSON object matching the ValidationResult schema:
        - is_valid: boolean (true if safe to deploy, false otherwise)
        - report: string (A brief summary of what is good or what is wrong)
        """

        try:
            # === 2. 真正调用 Gemini ===
            # 强制要求返回 ValidationResult (包含 is_valid 和 report)
            structured_llm = self.llm.with_structured_output(ValidationResult)
            
            print(f"[{self.agent_name}] Invoking Gemini API... (Auditing Config)")
            validation_result = structured_llm.invoke(prompt)

            if not validation_result:
                raise ValueError("Gemini returned empty response.")

            # === 3. 调试打印：看看 Gemini 对代码的评价 ===
            print(f"DEBUG: Gemini Validation Report: [{validation_result.is_valid}] {validation_result.report}")

            # === 4. 返回结果 ===
            # 使用 model_dump() 替代 dict()
            return {"validation_result": validation_result.model_dump()}

        except Exception as e:
            print(f"[{self.agent_name}] Error validating with Gemini: {e}")
            # 如果 LLM 调用失败，为了安全起见，应该默认为 False (不通过)
            fallback_result = ValidationResult(is_valid=False, report=f"Validation Process Failed: {str(e)}")
            return {"validation_result": fallback_result.model_dump()}

card = generate_agent_card(AGENT_NAME, CONFIG["port"], CONFIG["description"], CONFIG["capability"], CONFIG["params"], CONFIG["returns"])
agent = ConfigValidationAgent(AGENT_NAME, "localhost", CONFIG["port"], card)

if __name__ == "__main__":
    print(f"Starting {AGENT_NAME} on port {CONFIG['port']}...")
    uvicorn.run(agent.app, host=agent.host, port=agent.port)
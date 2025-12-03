import uvicorn
import json
from fastapi import FastAPI
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from typing import Dict, Any
import os
from models.a2a_models import A2AMessage, RemediationPlan
from .agent_card_generator import AGENT_CONFIGS, generate_agent_card
import time

# --- State Model for LangGraph ---
class GraphState(BaseModel):
    alarm_data: Dict[str, Any] = Field(default_factory=dict)
    topology: Dict[str, Any] = Field(default_factory=dict)
    plan: RemediationPlan = None
    error: str = None
    step: str = "START"

# --- LangGraph Node (using Gemini) ---
AGENT_NAME = "QoS Remediation Agent"
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY"))

# === 【新增】定义严格的临时模型，强制 Gemini 填空 ===
class ActionDetails(BaseModel):
    interface: str = Field(description="The specific interface name from topology, e.g., GigabitEthernet1/0/1")
    new_qos_level: str = Field(description="The target QoS policy name, e.g., priority_high_policy")
    reason: str = Field(description="A concise technical reason for this action")

class StrictRemediationPlan(BaseModel):
    plan_id: str = Field(description="Unique ID, e.g., PLAN-ALM-12345")
    device_id: str = Field(description="Target device hostname")
    priority: int = Field(description="Execution priority (1-5)")
    actions: ActionDetails  # <--- 注意这里：不再是 Dict，而是具体的类！
    
def analyze_and_plan(state: GraphState) -> GraphState:
    print(f"[{AGENT_NAME}] Step 1: Analyzing alarm and topology with Gemini.")
    alarm = state.alarm_data
    topology = state.topology

    # Prompt 可以稍微简化，因为 StrictRemediationPlan 会承担主要的约束工作
    prompt = f"""
    You are a network expert agent. 
    Analyze the following network Alarm and Topology to create a Remediation Plan.

    [Alarm Data]
    {json.dumps(alarm, indent=2)}

    [Network Topology]
    {json.dumps(topology, indent=2)}

    [Task]
    The goal is to fix the issue (e.g., reduce latency) by adjusting QoS settings.
    Identify the affected interface and suggest a QoS fix.
    """
    
    try:
        # === 【关键修改 1】使用严格模型调用 Gemini ===
        # 这告诉 Gemini：actions 字段必须包含 interface, new_qos_level, reason
        structured_llm = llm.with_structured_output(StrictRemediationPlan)
        
        print(f"[{AGENT_NAME}] Invoking Gemini API... (waiting for response)")
        
        # 这里拿到的 result 是 StrictRemediationPlan 的实例
        strict_result = structured_llm.invoke(prompt)
        
        # 调试：打印出来看看，这次 actions 应该有内容了
        print(f"DEBUG: Full Gemini Output: {strict_result.model_dump()}")
        
        if not strict_result:
            raise ValueError("Gemini returned an empty response.")

        # === 【关键修改 2】数据格式转换 ===
        # StrictRemediationPlan -> Python Dict -> 标准 RemediationPlan
        # 这样下游的 Config Generator 才能正常处理它
        plan_dict = strict_result.model_dump()
        
        # 重新封装成系统通用的对象
        final_plan = RemediationPlan(**plan_dict)

        # 打印决策理由 (现在是从严格模型里来的，肯定有值)
        # 注意：在 StrictRemediationPlan 中 actions 是对象，但在 model_dump 后变成了字典
        print(f"[{AGENT_NAME}] Gemini decision: {strict_result.actions.reason}")
        
        # 赋值给 state
        state.plan = final_plan
        state.step = "PLAN_GENERATED"

    except Exception as e:
        print(f"[{AGENT_NAME}] Error calling Gemini: {e}")
        import traceback
        traceback.print_exc()
        
        state.error = str(e)
        state.step = "ERROR"
        
    return state

# --- LangGraph Definition ---
workflow = StateGraph(GraphState)
workflow.add_node("analyze_plan", analyze_and_plan)
workflow.set_entry_point("analyze_plan")
workflow.add_edge("analyze_plan", END) 
app_graph = workflow.compile()

# --- FastAPI Wrapper (A2A Server) ---
CONFIG = AGENT_CONFIGS[AGENT_NAME]

app = FastAPI(title=f"{AGENT_NAME} A2A Server")

# 1. Agent Card Endpoint (Manually created for LangGraph)
card = generate_agent_card(AGENT_NAME, CONFIG["port"], CONFIG["description"], CONFIG["capability"], CONFIG["params"], CONFIG["returns"])
@app.get("/.well-known/agent.json")
async def get_agent_card():
    return card

# 2. A2A Message Handler
@app.post("/a2a")
async def handle_a2a_message(message: A2AMessage):
    if message.payload.get('capability') == CONFIG["capability"]:
        params = message.payload.get('params', {})
        
        # Start LangGraph process
        initial_state = GraphState(
            alarm_data=params.get("alarm_data", {}),
            topology=params.get("topology", {})
        )
        
        final_state_dict = app_graph.invoke(initial_state) # LangGraph returns a dictionary
        
        # FIX: Access the dictionary directly instead of treating it as a Pydantic object
        if final_state_dict.get('error'):
            return {"status": "failure", "error": final_state_dict['error']}
        
        # FIX: Use model_dump() for Pydantic V2 compatibility
        return {"status": "success", "result": {"remediation_plan": final_state_dict['plan'].model_dump()}}
    
    return {"status": "failure", "error": "Invalid capability."}

if __name__ == "__main__":
    print(f"Starting {AGENT_NAME} (LangGraph) on port {CONFIG['port']}...")
    uvicorn.run(app, host="localhost", port=CONFIG["port"])
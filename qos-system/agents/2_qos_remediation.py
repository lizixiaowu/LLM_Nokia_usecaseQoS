import uvicorn
import json
import os
import sys
from fastapi import FastAPI
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from typing import Dict, Any, List
from models.a2a_models import A2AMessage, RemediationPlan
from .agent_card_generator import AGENT_CONFIGS, generate_agent_card

# === 新增 MCP 相关的库 ===
from langchain_mcp_adapters.tools import load_mcp_tools

# --- 配置 ---
AGENT_NAME = "QoS Remediation Agent"

# 必须加载 .env 以获取 GEMINI_API_KEY
from dotenv import load_dotenv
load_dotenv() 

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY"))

# === 移除：旧的 Neo4j 硬编码配置 ===
# NEO4J_URI = ... (删除)
# NEO4J_USER = ... (删除)
# NEO4J_PASSWORD = ... (删除)

# === 新增：加载 MCP 工具 ===
# 假设你的 mcp server 文件名为 'neo4j_mcp_server.py' 并且在同一目录或已知路径
MCP_SERVER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "neo4j_mcp_server.py"))

print(f"[{AGENT_NAME}] Loading MCP Tools from {MCP_SERVER_PATH}...")

# 配置 MCP 客户端参数
server_params = {
    "command": "python",
    "args": [MCP_SERVER_PATH], 
    "env": os.environ.copy() # 传递环境变量给子进程
}

# 建立连接并获取工具列表
try:
    mcp_tools_list = load_mcp_tools(server_params)
    # 找到我们在 server 里定义的那个工具 "query_knowledge_graph"
    # 如果找不到，说明 server 没启动成功或者名字不对
    neo4j_tool = next((t for t in mcp_tools_list if t.name == "query_knowledge_graph"), None)
    
    if not neo4j_tool:
        raise ValueError("Tool 'query_knowledge_graph' not found in MCP Server!")
        
    print(f"[{AGENT_NAME}] MCP Tool loaded successfully: {neo4j_tool.name}")
except Exception as e:
    print(f"[{AGENT_NAME}] Failed to load MCP tools: {e}")
    neo4j_tool = None # 标记为不可用

# --- State Model (保持不变) ---
class GraphState(BaseModel):
    alarm_data: Dict[str, Any] = Field(default_factory=dict)
    topology: Dict[str, Any] = Field(default_factory=dict)
    plan: RemediationPlan = None
    error: str = None
    step: str = "START"

# === 模型定义 (保持不变) ===
class PathFindingRequest(BaseModel):
    cypher_query: str = Field(description="The exact Cypher query to find an alternative path.")
    reasoning: str = Field(description="Why you chose this query logic.")

class ActionDetails(BaseModel):
    interface: str = Field(description="The specific interface name to configure")
    new_qos_level: str = Field(description="The policy name")
    reason: str = Field(description="Technical reason")

class StrictRemediationPlan(BaseModel):
    plan_id: str = Field(description="Unique ID")
    device_id: str = Field(description="Target device hostname")
    priority: int = Field(description="Execution priority")
    actions: ActionDetails

# === 移除：旧的 run_cypher_query 函数 ===
# def run_cypher_query(query): ... (删除)

# === 核心逻辑 Node ===
def analyze_and_plan(state: GraphState) -> GraphState:
    print(f"[{AGENT_NAME}] Step 1: Analyzing Congestion & Consulting Neo4j via MCP...")
    
    source_node = state.alarm_data.get("source", "Router-A") 
    dest_node = state.alarm_data.get("destination", "Router-B")
    
    # --- Phase 1: 让 Gemini 写查询语句 (保持不变) ---
    prompt_cypher = f"""
    You are a Network Traffic Engineer.
    [Situation]
    The direct link from '{source_node}' to '{dest_node}' is congested.
    We need to find an ALTERNATIVE path in the graph database.
    
    [Task]
    Write a Cypher query to find paths from node {{id: '{source_node}'}} to node {{id: '{dest_node}'}}.
    IMPORTANT: The relationships (:CONNECTED_TO) must have available capacity.
    Filter condition: r.capacity - r.load > 5.0 (We need 5Mbps).
    
    Return the path or the next hop interface.
    """
    
    try:
        llm_query = llm.with_structured_output(PathFindingRequest)
        query_req = llm_query.invoke(prompt_cypher)
        print(f"[{AGENT_NAME}] Generated Cypher: {query_req.cypher_query}")
        
        # --- Phase 2: 执行查询 (改为调用 MCP 工具) ---
        print(f"[{AGENT_NAME}] Executing Cypher via MCP Tool...")
        
        if neo4j_tool:
            # === 这里是改动的核心 ===
            # 直接调用 tool.invoke，传入 MCP 定义的参数名 (cypher_query)
            tool_output = neo4j_tool.invoke({"cypher_query": query_req.cypher_query})
            
            # MCP 返回的通常是字符串形式的结果，我们需要解析或直接给 LLM
            # 假设 Server 返回的是 "str(results)"，这里我们直接给 LLM 读
            db_result = tool_output
        else:
            db_result = "Error: MCP Tool is not available."

        print(f"[{AGENT_NAME}] MCP Result: {db_result}")
        
        # --- Phase 3: 生成修复计划 (保持不变) ---
        prompt_plan = f"""
        Context: Congestion on {source_node} -> {dest_node}.
        Neo4j Path Search Result: {db_result}
        
        Task: Create a Remediation Plan.
        1. If a path was found, identify the OUTGOING INTERFACE on {source_node}.
        2. Set 'new_qos_level' to 'PBR_Redirect'.
        3. Explain the reroute path in 'reason'.
        
        If result is empty or indicates error, explain that no path exists.
        """
        
        llm_plan = llm.with_structured_output(StrictRemediationPlan)
        strict_plan = llm_plan.invoke(prompt_plan)
        
        print(f"[{AGENT_NAME}] Gemini Decision: {strict_plan.actions.reason}")

        state.plan = RemediationPlan(**strict_plan.model_dump())
        state.step = "PLAN_GENERATED"

    except Exception as e:
        print(f"[{AGENT_NAME}] Critical Error: {e}")
        import traceback
        traceback.print_exc()
        state.error = str(e)
        state.step = "ERROR"
        
    return state

# --- LangGraph Definition (保持不变) ---
workflow = StateGraph(GraphState)
workflow.add_node("analyze_plan", analyze_and_plan)
workflow.set_entry_point("analyze_plan")
workflow.add_edge("analyze_plan", END) 
app_graph = workflow.compile()

# --- FastAPI Wrapper (保持不变) ---
CONFIG = AGENT_CONFIGS[AGENT_NAME]
app = FastAPI(title=f"{AGENT_NAME} A2A Server")
card = generate_agent_card(AGENT_NAME, CONFIG["port"], CONFIG["description"], CONFIG["capability"], CONFIG["params"], CONFIG["returns"])

@app.get("/.well-known/agent.json")
async def get_agent_card():
    return card

@app.post("/a2a")
async def handle_a2a_message(message: A2AMessage):
    if message.payload.get('capability') == CONFIG["capability"]:
        params = message.payload.get('params', {})
        initial_state = GraphState(
            alarm_data=params.get("alarm_data", {}),
            topology=params.get("topology", {})
        )
        final_state_dict = app_graph.invoke(initial_state)
        
        if final_state_dict.get('error'):
            return {"status": "failure", "error": final_state_dict['error']}
        
        return {"status": "success", "result": {"remediation_plan": final_state_dict['plan'].model_dump()}}
    return {"status": "failure", "error": "Invalid capability."}

if __name__ == "__main__":
    print(f"Starting {AGENT_NAME} (LangGraph + MCP) on port {CONFIG['port']}...")
    uvicorn.run(app, host="localhost", port=CONFIG["port"])
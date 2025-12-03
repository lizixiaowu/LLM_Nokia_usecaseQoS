import uvicorn
import json
from fastapi import FastAPI
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from typing import Dict, Any, List
import os
from models.a2a_models import A2AMessage, RemediationPlan
from .agent_card_generator import AGENT_CONFIGS, generate_agent_card
import time
from neo4j import GraphDatabase

# --- 配置 ---
AGENT_NAME = "QoS Remediation Agent"
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY"))

# === Neo4j 配置 (请填入您的真实信息) ===
NEO4J_URI = "neo4j+s://df5afad6.databases.neo4j.io" 
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "QHb1EYdl7ZcG6iTfXnwZTdUQLa631WBL1ZIvEUkSkqg"

# --- State Model ---
class GraphState(BaseModel):
    alarm_data: Dict[str, Any] = Field(default_factory=dict)
    topology: Dict[str, Any] = Field(default_factory=dict)
    plan: RemediationPlan = None
    error: str = None
    step: str = "START"

# === 模型定义 ===
# 1. 中间模型：用于接收 Cypher 语句
class PathFindingRequest(BaseModel):
    cypher_query: str = Field(description="The exact Cypher query to find an alternative path.")
    reasoning: str = Field(description="Why you chose this query logic.")

# 2. 严格模型：用于生成最终计划 (复用之前的)
class ActionDetails(BaseModel):
    interface: str = Field(description="The specific interface name to configure (e.g., the new next-hop interface)")
    new_qos_level: str = Field(description="The policy name (e.g., 'route_map_divert')")
    reason: str = Field(description="Technical reason (e.g., 'Rerouting via Router-C due to congestion')")

class StrictRemediationPlan(BaseModel):
    plan_id: str = Field(description="Unique ID, e.g., PLAN-ALM-12345")
    device_id: str = Field(description="Target device hostname")
    priority: int = Field(description="Execution priority (1-5)")
    actions: ActionDetails

# === Helper: Neo4j 查询 ===
def run_cypher_query(query: str):
    """连接 Neo4j 执行 Cypher"""
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            result = session.run(query)
            return [record.data() for record in result]
    except Exception as e:
        return [f"Database Connection Error: {str(e)}"]
    finally:
        if 'driver' in locals():
            driver.close()

# === 核心逻辑 Node ===
def analyze_and_plan(state: GraphState) -> GraphState:
    print(f"[{AGENT_NAME}] Step 1: Analyzing Congestion & Consulting Neo4j for Paths...")
    
    # 从上游 Monitor Agent 获取源和目的
    # 如果上游没传，这里默认用 Router-A/Router-B 做演示
    source_node = state.alarm_data.get("source", "Router-A") 
    dest_node = state.alarm_data.get("destination", "Router-B")
    
    # --- Phase 1: 让 Gemini 写查询语句 ---
    prompt_cypher = f"""
    You are a Network Traffic Engineer.
    [Situation]
    The direct link from '{source_node}' to '{dest_node}' is congested.
    We need to find an ALTERNATIVE path in the graph database.
    
    [Task]
    Write a Cypher query to find paths from node {{id: '{source_node}'}} to node {{id: '{dest_node}'}}.
    IMPORTANT: The relationships (:CONNECTED_TO) must have available capacity.
    Filter condition: r.capacity - r.load > 5.0 (We need 5Mbps).
    
    [Schema Reference]
    (Router {{id: '...'}})-[r:CONNECTED_TO {{capacity: 100.0, load: 10.0, interface: 'Gi1/0/2'}}]->(Router)
    
    Return the path or the next hop interface.
    """
    
    try:
        llm_query = llm.with_structured_output(PathFindingRequest)
        query_req = llm_query.invoke(prompt_cypher)
        print(f"[{AGENT_NAME}] Generated Cypher: {query_req.cypher_query}")
        
        # --- Phase 2: 执行查询 ---
        print(f"[{AGENT_NAME}] Executing Cypher against Neo4j...")
        db_result = run_cypher_query(query_req.cypher_query)
        print(f"[{AGENT_NAME}] Neo4j Result: {db_result}")
        
        # --- Phase 3: 生成修复计划 ---
        prompt_plan = f"""
        Context: Congestion on {source_node} -> {dest_node}.
        Neo4j Path Search Result: {json.dumps(db_result)}
        
        Task: Create a Remediation Plan.
        1. If a path was found (e.g., via Router-C), identify the OUTGOING INTERFACE on {source_node}.
           (Look for 'interface' property in the relationship from Source).
        2. Set 'new_qos_level' to 'PBR_Redirect'.
        3. Explain the reroute path in 'reason'.
        
        If result is empty, explain that no path exists.
        """
        
        llm_plan = llm.with_structured_output(StrictRemediationPlan)
        strict_plan = llm_plan.invoke(prompt_plan)
        
        print(f"[{AGENT_NAME}] Gemini Decision: {strict_plan.actions.reason}")

        # 转换并保存
        state.plan = RemediationPlan(**strict_plan.model_dump())
        state.step = "PLAN_GENERATED"

    except Exception as e:
        print(f"[{AGENT_NAME}] Critical Error: {e}")
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

# --- FastAPI Wrapper ---
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
    print(f"Starting {AGENT_NAME} (LangGraph + Neo4j) on port {CONFIG['port']}...")
    uvicorn.run(app, host="localhost", port=CONFIG["port"])
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
        # === NEW LOGIC START: M/M/1 Simulation ===
        print(f"[{self.agent_name}] Simulation: Reading Telemetry & Calculating M/M/1 Latency...")

        # 1. 定义场景数据 (模拟 Router-A 到 Router-B 的直连链路)
        # 这里的数值对应我们在 Neo4j 里创建的 "拥塞路径"
        link_capacity = 10.0  # Mbps (Service Rate)
        current_load = 9.6    # Mbps (Arrival Rate) - 96% 负载
        
        max_latency_threshold = 20.0 # ms (SLA要求)

        # 2. M/M/1 排队论计算
        # Utilization (rho) = lambda / mu
        utilization = current_load / link_capacity
        
        # 防止除以零
        if utilization >= 0.99:
            estimated_latency = 1000.0 
        else:
            # 公式: T = 1 / (mu - lambda)
            # 我们乘以 10 作为演示用的 scaling factor，让结果看起来像毫秒
            estimated_latency = (1.0 / (link_capacity - current_load)) * 10.0

        print(f"[{self.agent_name}] Link Status: Load={current_load}/{link_capacity} Mbps (Util: {utilization:.1%})")
        print(f"[{self.agent_name}] M/M/1 Calculated Latency: {estimated_latency:.2f} ms")

        # 3. 判定逻辑
        if estimated_latency > max_latency_threshold:
            print(f"[{self.agent_name}] ⚠️ SLA VIOLATION DETECTED! Triggering Congestion Alarm.")
            
            # 构造标准告警对象
            alarm = AlarmData(
                alarm_id="ALM-CONGESTION-MM1",
                metric="Estimated_Latency",
                value=float(f"{estimated_latency:.2f}"), # 保留两位小数
                threshold=max_latency_threshold,
                timestamp="2025-12-03T10:00:00Z"
            )
            
            # 返回结果：
            # 除了 alarm_data，我们额外返回 source 和 destination
            # 这两个字段将被传递给下一个 Agent (Remediation)，作为 Neo4j 查询的起点和终点
            return {
                "alarm_data": alarm.model_dump(),
                "source": "Router-A",
                "destination": "Router-B"
            }
        
        print(f"[{self.agent_name}] Link is Healthy.")
        return {"status": "Healthy", "latency": estimated_latency}
        # === NEW LOGIC END ===

card = generate_agent_card(AGENT_NAME, CONFIG["port"], CONFIG["description"], CONFIG["capability"], CONFIG["params"], CONFIG["returns"])
agent = QoSMonitorAgent(AGENT_NAME, "localhost", CONFIG["port"], card)

if __name__ == "__main__":
    print(f"Starting {AGENT_NAME} on port {CONFIG['port']}...")
    uvicorn.run(agent.app, host=agent.host, port=agent.port)
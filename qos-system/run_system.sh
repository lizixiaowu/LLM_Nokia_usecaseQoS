#!/bin/bash
# 启动所有智能体
# 确保已安装依赖：pip install -r requirements.txt
# 确保 GEMINI_API_KEY 已设置
# 运行前请确保当前目录是 qos-system/ 

# 函数：启动一个 Agent (使用 -m 选项，解决导入问题)
start_agent() {
    local agent_module=$1 # 格式：agents.1_qos_monitor
    local port=$2
    
    echo "Starting $agent_module on port $port..."
    # 使用 python3 -m 启动模块
    python3 -m $agent_module &
    echo $! > ${agent_module}.pid
}

# 清理旧的 PID 文件
rm -f *.pid

# 启动 5 个 ADK 智能体 和 1 个 LangGraph 智能体
start_agent agents.1_qos_monitor 8001
start_agent agents.2_qos_remediation 8002
start_agent agents.3_config_generator 8003
start_agent agents.4_config_validator 8004
start_agent agents.5_config_executor 8005

# 关键：增加等待时间，确保所有 Agents 的 Server 都已启动
echo "Waiting 10 seconds for all Agents to initialize and open ports..."
sleep 10 

# 启动 编排 Agent
start_agent agents.6_orchestrator 8006
# 增加对 Orchestrator 启动后的等待时间，确保 8006 端口被监听
echo "Waiting 5 seconds for Orchestrator to complete discovery and listen on 8006..."
sleep 5 

# --- 触发流程 ---
echo "--- Triggering QoS Fix Chain via Orchestrator (Port 8006) ---"
# 确保端口是 8006
curl -X POST http://localhost:8006/a2a \
     -H "Content-Type: application/json" \
     -d '{
         "sender_id": "ExternalTrigger", 
         "receiver_id": "Orchestration Agent", 
         "payload": {"capability": "start_qos_chain", "params": {}}
     }'

echo ""
echo "--- Clean Up (Stopping Agents) ---"
for pid_file in *.pid; do
    if [ -f "$pid_file" ]; then
        # 使用 pkill -F 结束进程
        pkill -F $pid_file 
        rm $pid_file
    fi
done

echo "System run complete."
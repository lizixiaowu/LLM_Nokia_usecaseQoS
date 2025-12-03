import os
from mcp.server.fastmcp import FastMCP
from neo4j import GraphDatabase

# 1. 初始化 MCP 服务器，给它起个名字
mcp = FastMCP("QoS-Neo4j-Gateway")

# 配置 Neo4j 连接信息 (建议从环境变量读取，这里为了演示直接写)
URI = "neo4j+s://df5afad6.databases.neo4j.io"
AUTH = ("neo4j", "QHb1EYdl7ZcG6iTfXnwZTdUQLa631WBL1ZIvEUkSkqg") # 记得改成你的实际密码

# 2. 定义一个“工具” (Tool)
# @mcp.tool() 装饰器会自动把这个函数转换成 LLM 能看懂的 JSON Schema
@mcp.tool()
def query_knowledge_graph(cypher_query: str) -> str:
    """
    执行 Cypher 查询语句来检索网络拓扑或配置状态。
    当需要查询设备关系、配置详情或错误根因时使用此工具。
    
    Args:
        cypher_query: 有效的 Neo4j Cypher 查询字符串。
    """
    driver = GraphDatabase.driver(URI, auth=AUTH)
    try:
        results = []
        with driver.session() as session:
            # 执行查询
            result = session.run(cypher_query)
            # 将结果转换为字典列表
            results = [record.data() for record in result]
        
        # 如果没查到数据
        if not results:
            return "No results found in the Knowledge Graph."
            
        # 返回字符串形式的结果 (LLM 会读取这个字符串)
        return str(results)
        
    except Exception as e:
        return f"Query Error: {str(e)}"
    finally:
        driver.close()

# 3. 运行服务器
if __name__ == "__main__":
    # 这一行启动服务器，监听标准输入/输出 (Stdio)
    mcp.run()
import os
import base64
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.models import BedrockModel
from strands.models.litellm import LiteLLMModel
from strands.tools.mcp.mcp_client import MCPClient
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class PromptRequest(BaseModel):
    prompt: str


if os.environ.get("USE_BEDROCK", "").lower() == "true":
    print("Using Bedrock...")
    model_id = os.environ.get(
        "BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-20250514-v1:0"
    )
    model = BedrockModel(model_id=model_id)
else:
    print("Using LiteLLM...")
    model = LiteLLMModel(
        client_args={
            "base_url": f"{os.environ.get('LITELLM_BASE_URL')}/v1",
            "api_key": os.environ.get("LITELLM_API_KEY"),
        },
        model_id="openai/" + os.environ.get("LITELLM_MODEL_NAME"),
    )

if "LANGFUSE_HOST" in os.environ:
    LANGFUSE_AUTH = base64.b64encode(
        f"{os.environ.get('LANGFUSE_PUBLIC_KEY')}:{os.environ.get('LANGFUSE_SECRET_KEY')}".encode()
    ).decode()
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
        os.environ.get("LANGFUSE_HOST") + "/api/public/otel/v1/traces"
    )
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {LANGFUSE_AUTH}"

system_prompt = """
You are an AWS Cost Analysis assistant. You help users understand and analyze their AWS spending.

You have access to the following cost analysis tools:
- get_total_cost: Get the total AWS cost for a specified period
- get_cost_by_service: Get cost breakdown by AWS service
- get_daily_cost_trend: Get daily cost trend to identify spending patterns
- get_cost_comparison: Compare costs between current and previous periods
- get_service_cost_detail: Get detailed cost for a specific AWS service

When answering questions:
1. Use the appropriate tool(s) to fetch real cost data
2. Present the data clearly with formatting (tables, bullet points)
3. Highlight significant cost changes or anomalies
4. Provide actionable insights when possible (e.g., "EC2 costs increased 30% - consider right-sizing instances")
5. Always mention the time period being analyzed
6. Use USD currency

Respond in the same language as the user's question. If asked in Korean, respond in Korean.
If asked in English, respond in English.
"""

app = FastAPI()

mcp_client = None
agent = None


@app.on_event("startup")
async def startup_event():
    global mcp_client, agent
    print("Connecting to Cost Analysis MCP Server...")
    mcp_client = MCPClient(
        lambda: streamablehttp_client("http://cost-analysis.mcp-server:8000/mcp")
    )
    mcp_client.__enter__()
    tools = mcp_client.list_tools_sync()
    agent = Agent(model=model, system_prompt=system_prompt, tools=tools)


@app.on_event("shutdown")
async def shutdown_event():
    global mcp_client
    if mcp_client:
        await mcp_client.__exit__(None, None, None)


@app.post("/")
async def prompt(request: PromptRequest):
    """Process a cost analysis request and return the result as a streaming response."""
    global agent

    prompt = request.prompt
    print(f"Prompt: {prompt}\n")

    async def process_streaming_response():
        try:
            async for event in agent.stream_async(request.prompt):
                if "data" in event:
                    yield event["data"]
        except Exception as e:
            print(f"Error: {e}")
            yield f"Error processing the request: {e}"

    return StreamingResponse(process_streaming_response(), media_type="text/plain")

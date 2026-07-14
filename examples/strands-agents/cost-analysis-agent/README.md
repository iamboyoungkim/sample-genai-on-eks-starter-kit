# AWS Cost Analysis Agent

AI-powered AWS cost analysis chatbot built with [Strands Agents](https://strandsagents.com) and [FastMCP](https://gofastmcp.com). Users can query AWS spending data using natural language through Open WebUI.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ EKS Cluster                                                         │
│                                                                     │
│  ┌──────────────┐     ┌─────────────────────┐     ┌─────────────┐  │
│  │  Open WebUI  │────▶│  Cost Analysis Agent │────▶│ MCP Server  │  │
│  │  (GUI)       │     │  (Strands Agent)     │     │ (FastMCP)   │  │
│  │              │     │                      │     │             │  │
│  │  Pipe Func   │     │  system prompt +     │     │  boto3 →    │  │
│  │  → HTTP POST │     │  tool orchestration  │     │  Cost       │  │
│  └──────────────┘     └──────────┬───────────┘     │  Explorer   │  │
│                                  │                 │  API        │  │
│                                  ▼                 └──────┬──────┘  │
│                         ┌─────────────────┐               │         │
│                         │    LiteLLM      │               │         │
│                         │  (AI Gateway)   │               │         │
│                         └────────┬────────┘               │         │
│                                  │                        │         │
└──────────────────────────────────┼────────────────────────┼─────────┘
                                   │                        │
                                   ▼                        ▼
                          ┌─────────────────┐     ┌─────────────────┐
                          │  LLM (vLLM or   │     │  AWS Cost       │
                          │  Bedrock)        │     │  Explorer API   │
                          └─────────────────┘     └─────────────────┘
```

## How It Works

### 1. User Input (Open WebUI → Agent)

When a user selects "Strands Agents - AWS Cost Analysis" in Open WebUI and sends a message:

1. Open WebUI routes the message through a **Pipe Function** (`openwebui_pipe_function.py`)
2. The Pipe Function sends an HTTP POST to the agent's internal endpoint: `http://cost-analysis-agent.strands-agents`
3. The agent receives the natural language prompt

### 2. Agent Reasoning (Strands Agent → LLM)

The Strands Agent:

1. Combines the user's prompt with a **system prompt** that describes available tools
2. Sends this to the LLM (via LiteLLM) for reasoning
3. The LLM decides which tool(s) to call and with what parameters

For example, if the user asks "서비스별 비용 Top 5 보여줘", the LLM will decide to call `get_cost_by_service(days=30, top_n=5)`.

### 3. Tool Execution (Agent → MCP Server → AWS)

1. The agent calls the selected tool via **MCP protocol** (Streamable HTTP)
2. The MCP Server (`cost-analysis.mcp-server:8000`) executes the corresponding Python function
3. The function uses `boto3` to call the AWS Cost Explorer API
4. Results are returned as JSON to the agent

### 4. Response Generation (LLM → User)

1. The agent passes the tool results back to the LLM
2. The LLM formats the data into a human-readable response
3. The response is streamed back through the Pipe Function to Open WebUI

## Components

### MCP Server (`examples/mcp-server/cost-analysis/`)

A FastMCP server that wraps AWS Cost Explorer API into MCP-compatible tools.

| File | Role |
|------|------|
| `server.py` | FastMCP server with 5 cost analysis tools |
| `Dockerfile` | Container image (Python 3.12) |
| `main.tf` | ECR repository + Pod Identity (Cost Explorer IAM permissions) |
| `mcp-server.template.yaml` | K8s Deployment + Service + ServiceAccount |
| `index.mjs` | CLI install/uninstall script |

**IAM Permissions** (granted via EKS Pod Identity):
- `ce:GetCostAndUsage`
- `ce:GetCostForecast`
- `ce:GetDimensionValues`
- `ce:GetTags`

### Strands Agent (`examples/strands-agents/cost-analysis-agent/`)

A FastAPI server running a Strands Agent that connects to the MCP Server.

| File | Role |
|------|------|
| `agent.py` | FastAPI + Strands Agent (MCP client, streaming response) |
| `openwebui_pipe_function.py` | Registers the agent as a model in Open WebUI |
| `Dockerfile` | Container image (Python 3.12) |
| `main.tf` | ECR repository + Pod Identity (Bedrock IAM permissions) |
| `agent.template.yaml` | K8s Deployment + Service + ServiceAccount |
| `index.mjs` | CLI install/uninstall script |

## Available Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_total_cost` | `days` (default: 30) | Total AWS cost for the period |
| `get_cost_by_service` | `days`, `top_n` (default: 10) | Cost breakdown by service |
| `get_daily_cost_trend` | `days` (default: 14) | Daily cost data points |
| `get_cost_comparison` | `days` (default: 30) | Current vs previous period comparison |
| `get_service_cost_detail` | `service_name`, `days` | Daily cost for a specific service |

## Configuration

In `config.json` or `config.local.json`:

```json
{
  "examples": {
    "strands-agents": {
      "cost-analysis-agent": {
        "env": {
          "USE_BEDROCK": false,
          "BEDROCK_MODEL": "us.anthropic.claude-sonnet-4-20250514-v1:0",
          "LITELLM_MODEL_NAME": "vllm/qwen3-30b-instruct-fp8"
        }
      }
    }
  }
}
```

- `USE_BEDROCK`: Set to `true` to use Bedrock directly instead of LiteLLM
- `BEDROCK_MODEL`: Bedrock model ID (used when `USE_BEDROCK=true`)
- `LITELLM_MODEL_NAME`: Model name registered in LiteLLM (used when `USE_BEDROCK=false`)

## Observability

When Langfuse is deployed, the agent automatically sends traces via OpenTelemetry. You can view:

- Each user request as a trace
- LLM calls (input/output tokens, latency)
- Tool calls (which tools were invoked, results)

## Creating a Similar Agent

To create a new agent following this pattern:

1. **Create a MCP Server** in `examples/mcp-server/<name>/`
   - Write `server.py` with `@mcp.tool()` decorated functions
   - Define IAM permissions in `main.tf`

2. **Create a Strands Agent** in `examples/strands-agents/<name>-agent/`
   - Copy `agent.py` and update the system prompt and MCP endpoint
   - Copy `openwebui_pipe_function.py` and update the endpoint/name

3. **Register in CLI**
   - Add entries to `cli-menu.json`
   - Add env config to `config.json`

4. **Deploy**
   ```bash
   ./cli mcp-server <name> install
   ./cli strands-agents <name>-agent install
   ```

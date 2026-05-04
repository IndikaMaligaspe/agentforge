# full_stack_agent

Maximalist AgentForge project exercising every opt-in feature

## Overview

This project was scaffolded using [agentforge](https://github.com/code4zeero/agentforge), a tool for creating production-ready agentic applications.

## Features

- LangGraph-based workflow with supervisor orchestration
- Multiple specialized agents for different query types
- FastAPI backend with structured logging and observability
- API key authentication- Langfuse tracing integration- PostgreSQL database integration- Docker and Docker Compose support

## Project Structure

```
full_stack_agent/
├── backend/
│   ├── main.py                  # FastAPI application
│   ├── mcp_server.py            # Model-Control-Protocol server
│   │
│   ├── agents/
│   │   ├── base_agent.py        # Abstract base class for all agents
│   │   ├── registry.py          # Agent registry with @register decorator
│   │   └── data_agent.py      # DataAgent
│   │   └── analytics_agent.py      # AnalyticsAgent
│   │
│   ├── graph/
│   │   ├── workflow.py          # LangGraph workflow definition
│   │   ├── state.py             # State type definitions
│   │   └── nodes/               # LangGraph node implementations
│   │       ├── query_router_node.py
│   │       ├── supervisor_node.py
│   │       └── answer_node.py
│   │
│   ├── observability/
│   │   ├── logging.py           # Structured JSON logging
│   │   └── tracing.py           # Langfuse tracing integration│   │
│   ├── security/
│   │   ├── auth.py              # API key authentication
│   │   └── sanitizer.py         # Input sanitization utilities
│   │
│   └── middleware/
│       └── logging_middleware.py # Request/response logging
│
├── .env.example                 # Environment variables template
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Container definition
└── docker-compose.yml           # Multi-container setup
```

## Getting Started

### Prerequisites

- Python 3.12 or higher
- PostgreSQL database
- OpenAI API key

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/full_stack_agent.git
   cd full_stack_agent
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

### Running the Application

Start the API server:

```bash
uvicorn backend.main:app --reload
```

The API will be available at http://localhost:8000

### Docker Deployment

Build and run with Docker Compose:

```bash
docker-compose up -d
```

## Environment Variables

The scaffold reads configuration from `.env` (see `.env.example` for a starter file). Pydantic-Settings consumers auto-load it; bare `os.environ.get()` consumers need `make run` to forward the file via `--env-file .env`.

| Variable | Purpose | Required | Default |
|----------|---------|----------|---------|
| `OPENAI_API_KEY` | LLM provider API key | Yes | — |
| `DATABASE_URL` | Database connection string | Yes | — |
| `LOG_LEVEL` | Logging verbosity | No | `INFO` |
| `LOG_FORMAT` | Log output format (`json` or `text`) | No | `json` |
| `PORT` | HTTP listen port | No | `8000` |
| `HOST` | HTTP bind address | No | `0.0.0.0` |
| `WORKERS` | Uvicorn worker count | No | `1` |
| `RELOAD` | Dev-server auto-reload | No | `true` |
| `JWT_ISSUER` | Expected JWT issuer claim | Yes | — |
| `JWT_AUDIENCE` | Expected JWT audience claim | Yes | — |
| `LANGFUSE_HOST` | Langfuse server URL | No | `https://cloud.langfuse.com` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | Yes | — |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | Yes | — |
| `LANGFUSE_PROJECT` | Langfuse project name | Yes | — |
| `MCP_SERVERS` | JSON map of MCP server URLs (commented in `.env.example`) | No | — |
| `MCP_TIMEOUT` | MCP request timeout (seconds) | No | `30` |

## API Endpoints

- `POST /query`: Main query endpoint
- `POST /analyse`: Main query endpoint

## Development

### Adding a New Agent

1. Create a new agent file in `backend/agents/`
2. Implement the agent class extending `BaseAgent`
3. Register the agent with `@AgentRegistry.register("intent_key")`
4. Update the query router to recognize the new intent

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [agentforge](https://github.com/code4zeero/agentforge) - Scaffolding tool
- [LangChain](https://github.com/langchain-ai/langchain) - LLM framework
- [LangGraph](https://github.com/langchain-ai/langgraph) - Agent orchestration
- [FastAPI](https://fastapi.tiangolo.com/) - API framework
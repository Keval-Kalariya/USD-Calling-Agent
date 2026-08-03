# Ultimate Smile Design Calling Agent

A free-tier AI voice calling agent for Ultimate Smile Design (v1).

## Prerequisites
- Python 3.12+
- `ngrok` installed globally

## Installation
1. Run `make install` to create the virtual environment and install dependencies.
2. Copy `.env.example` to `.env` and fill in your API keys.

## Development
Run the local dev server using `make dev` which will start FastAPI via uvicorn and ngrok simultaneously using honcho.

## Key Validation
Before beginning Phase 1, make sure your keys are set up correctly:
Run `backend\.venv\Scripts\python scripts\check_keys.py` to ensure all API keys are valid.

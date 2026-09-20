# OrbitMesh Support Assistant

A command-line RAG chatbot for troubleshooting the fictional OrbitMesh home Wi-Fi and Pro
Series systems. Product guidance comes from the documents in `corpus/`.

## Requirements

- Python 3.12.11
- Node.js 24.19.0 and npm
- An OpenRouter API key

## Setup

```bash
make setup
cp .env.example .env
```

Edit `.env` and add your key:

```text
OPENROUTER_API_KEY=your-key-here
```

## Ingest the documents

Run this once before chatting:

```bash
make ingest
```

This chunks the documents, creates embeddings with
`openai/text-embedding-3-small`, and stores them in Chroma under `data/chroma/`.

To rebuild the index completely:

```bash
./scripts/ingest.sh --force
```

## Start the chatbot

```bash
make chat
```

Then type a message in the terminal. For example:

```text
you> My node keeps disconnecting
```

The assistant will ask for details such as the product line, device, connection type, or LED
state before giving a documented next step. Type `exit`, `quit`, or press `Ctrl+D` to stop.

## JSONL mode

The scripted interface reads one JSON object per line and writes one response object per line:

```bash
echo '{"session_id":"case-1","message":"My node keeps disconnecting"}' \
  | ./scripts/chat.sh --jsonl
```

Example response:

```json
{"response":"...","citations":[],"action":"ask"}
```

Reusing a `session_id` continues the same conversation. Logs are written to stderr so stdout
remains valid JSONL.

## Tests and evaluation

Run the transport contract check and Promptfoo smoke tests:

```bash
make test
```

Run the full Promptfoo evaluation:

```bash
make eval
```

The evaluation covers product-specific retrieval, citations, conversation memory, factory-reset
confirmation, safety escalation, prompt injection, and resolution handling.

## Documentation

- [Design note](documentation/DESIGN.md): architecture, trade-offs, scaling, evaluation results, and AI-assisted development.
- [Architecture diagram](documentation/architecture.png): exported system architecture diagram.
- [LangGraph diagram](documentation/langgraph-flow.png): exported conversation-flow diagram.

## Useful commands

```bash
make setup    # install dependencies
make ingest   # index the corpus
make chat     # start the terminal chatbot
make test     # run contract and smoke tests
make eval     # run the full evaluation
```

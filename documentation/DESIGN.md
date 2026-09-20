# OrbitMesh Support Assistant Design Note

## 1. Overall Architecture and Key Trade-offs

This is a command-line RAG support assistant for the OrbitMesh product documents. It has four layers:

1. **Ingestion:** loads the Markdown corpus, extracts document metadata, chunks sections, creates embeddings, and stores the chunks in Chroma.
2. **Retrieval:** builds a query from the conversation state, filters by product line and document status, then ranks the remaining chunks by semantic similarity.
3. **Conversation agent:** a LangGraph workflow screens the message, fills diagnostic slots, asks for missing information, retrieves evidence, generates a cited answer, applies output guardrails, and saves the session.
4. **CLI:** provides both the interactive terminal experience and the JSONL adapter used by contract checks and Promptfoo.

The central trade-off is between flexibility and control. A general-purpose LLM can ask natural follow-up questions and explain documentation well, but it can also guess or combine similar-looking instructions. I therefore keep the LLM responsible for triage and wording, while retrieval filters and deterministic guardrails control what evidence and actions are allowed.

Another trade-off is local simplicity versus production scale. Chroma and JSON session files make the project easy to run and inspect locally. They would need to become managed services and shared storage for multiple production instances.

![OrbitMesh architecture and data flow](architecture.png)


## 2. Chunking and Embedding Choices

Documents are split according to their Markdown structure rather than by an arbitrary character count. `##` headings create sections and `###` headings create subsections. For example, `Wireless N1` and `Ethernet-connected N1` become separate chunks. The parent heading is included in each chunk so the embedded text retains its context.

This choice fits the corpus because troubleshooting procedures are already organized into meaningful sections. It also avoids combining incompatible instructions into one embedding. A downside is that a very long section could still need a second, length-based split in a larger corpus.

Each chunk stores metadata derived from the source document:

- document ID and section;
- product line (`home`, `pro`, or `all`);
- current/archive status;
- document version and effective date.

Embeddings use OpenRouter's `openai/text-embedding-3-small`. The chat model is `openai/gpt-5-mini`. Using separate models keeps semantic search independent from answer generation. The embedding model finds relevant passages; the chat model interprets the retrieved evidence and maintains the conversation.

The main retrieval trade-off is that metadata filtering happens before similarity ranking. This reduces generic-similarity mistakes, such as returning the home LED reference for a Pro N5 Pro question, but requires the agent to identify the product line before giving specific advice.

## 3. Conversation and Safety Design

Each turn runs through LangGraph. The planner tracks product line, device, symptom, connection method, LED state, error code, and attempted steps. If important context is missing, the graph asks one focused question instead of guessing.

After retrieval, the answer node receives only the relevant evidence and must return an action, citations, and one safe next step. Sessions are persisted under `data/sessions/`, allowing a reused JSONL `session_id` to continue a conversation.

Guardrails operate before and after the LLM. Input checks detect prompt-injection language and redact likely passwords, API keys, and other sensitive values. Output checks block internal repair instructions, require confirmation before a factory reset, add warranty disclaimers, and force escalation for safety conditions such as smoke, burning smell, overheating, or visible damage.

## 4. Evaluation Method and Results

The application is evaluated through its real JSONL interface, not by calling internal functions directly. Promptfoo invokes `scripts/chat.sh --jsonl` through `promptfoo/provider.js`, preserving one `session_id` across multi-turn cases.

`make test` runs the smoke suite, and `make eval` runs the full suite. The cases cover:

- Home versus Pro retrieval and citations;
- multi-turn diagnostic memory;
- factory-reset confirmation;
- safety escalation;
- prompt-injection handling;
- resolution recognition.

The observed live results were:

```text
make test: 2/2 passed
make eval: 6/6 passed
contract checker: 20/20 checks passed
```

The assertions measure observable behavior: allowed actions, expected document IDs in citations, forbidden wrong-product citations, safety escalation, no unsafe repair advice, and resolution recognition. They do not attempt to prove that every sentence is factually perfect.

For GitHub Actions, `ORBITMESH_CI_MODE=1` switches to local Chroma embeddings and a deterministic LLM response path. The workflow uses temporary directories and runs ingestion, retrieval, idempotency, contract, and Promptfoo checks without an API key. This validates the application wiring and retrieval behavior; live OpenRouter runs are still needed to measure real model quality.

## 5. Observed Failure and Fix

The most relevant failure occurred in the agent logic. In an early version, the planner could correctly mark a customer message as a safety signal, but the graph still allowed the answer model to choose the final action. That meant a model could theoretically return an ordinary troubleshooting instruction after the customer reported overheating or a burning smell.

An offline evaluation case exposed this gap. I fixed it in `node_guard_output` by forcing `action="escalate"` whenever the planner reports a safety signal, then appending a stop-troubleshooting/support message. The LLM still handles language and evidence selection, but it can no longer override a documented safety stop condition.

## 6. Scaling to 100x Corpus Size and Real Customer Load

At roughly 100 times the current corpus size, ingestion should become a versioned batch job. It should batch and cache embeddings, process only changed documents, maintain separate index versions, and publish a new index atomically. A managed vector database would be preferable to one local Chroma directory when several application instances need concurrent access.

Retrieval would need stronger deduplication, reranking, and conflict resolution because a larger corpus increases the chance of overlapping or contradictory procedures. Product, version, region, and effective-date metadata would become essential.

For real customer traffic, I would move sessions from JSON files to shared storage, add connection pooling, retrieval and response caches, timeouts, rate limits, structured tracing, and monitoring. The planner adds an extra model call per turn, so a smaller classifier or deterministic slot extraction could reduce latency and cost. The larger model could then be reserved for grounded answer generation.

## 7. How the Evaluation Could Be Misleading

The evaluation set is small and hand-written. It could pass while missing a difficult private conversation that combines an ambiguous product, an archived firmware workaround, incomplete LED information, and a safety concern. The assertions also check selected citations and phrases rather than every factual claim. For that reason, the results are useful evidence of regression resistance, but not a guarantee of complete support quality.

## 8. AI Tools Used and Human Review

I used GitHub Copilot in VS Code as an implementation and design assistant. It helped explore the repository, compare ingestion and conversation structures, draft Python and LangGraph components, and investigate Promptfoo and OpenRouter integration issues.

The work remained human-in-the-loop. I chose the architecture, reviewed the generated suggestions, checked product behavior and safety rules against the supplied corpus, ran the commands, inspected failures, and decided which fixes to keep. Promptfoo was used as the black-box evaluation tool, and OpenRouter provided the embedding and chat APIs. Copilot accelerated exploration and coding, but the final design decisions, validation, and interpretation of results remained mine.

![OrbitMesh LangGraph conversation flow](langgraph-flow.png)


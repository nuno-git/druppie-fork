"""Agent template — customize this for your domain.

This is where you define what the AI assistant can do. The default
implementation provides a simple Q&A agent. Replace or extend the
`run_agent` function with your own logic.

The agent receives:
- question: the user's message
- history: previous messages in the conversation
- db: SQLAlchemy database session (for querying your app's data)

The agent returns:
- answer: the text response to show the user
- steps: list of transparency steps (shown in the UI)

Each step has:
- type: "search", "query", "tool", "reasoning", etc.
- label: human-readable description
- detail: the raw data (search terms, query results, etc.)

Example customization for a permit search app:

    def run_agent(question, history, db):
        steps = []

        # Step 1: Generate search terms
        terms = ask_llm_for_search_terms(question)
        steps.append({"type": "search", "label": "Zoektermen", "detail": terms})

        # Step 2: Query database
        results = search_permits(db, terms)
        steps.append({"type": "query", "label": f"{len(results)} resultaten", "detail": [...]})

        # Step 3: Synthesize answer
        answer = ask_llm_to_answer(question, results)
        return {"answer": answer, "steps": steps}
"""

from druppie_sdk import DruppieClient

druppie = DruppieClient()


def run_agent(question: str, history: list[dict], db) -> dict:
    """Process a user question and return an answer with transparency steps.

    Override this function with your domain-specific agent logic.
    The default implementation is a simple LLM Q&A with conversation context.

    Args:
        question: The user's current message.
        history: List of {"role": "user"|"assistant", "content": "..."} dicts.
        db: SQLAlchemy database session for querying app data.

    Returns:
        {"answer": str, "steps": list[dict]}
    """
    steps = []

    # Build conversation context
    context_messages = ""
    if history:
        recent = history[-6:]  # last 3 exchanges
        context_messages = "\n".join(
            f"{'Gebruiker' if m['role'] == 'user' else 'Assistent'}: {m['content']}"
            for m in recent
        )

    # Call LLM
    prompt = question
    if context_messages:
        prompt = f"Eerdere berichten:\n{context_messages}\n\nNieuwe vraag: {question}"

    steps.append({"type": "reasoning", "label": "Vraag naar LLM gestuurd", "detail": None})

    result = druppie.call("llm", "chat", {
        "prompt": prompt,
        "system": (
            "Je bent een behulpzame assistent. Beantwoord vragen in het Nederlands. "
            "Wees beknopt maar volledig."
        ),
    })

    answer = result.get("answer", "Geen antwoord ontvangen.")
    return {"answer": answer, "steps": steps}

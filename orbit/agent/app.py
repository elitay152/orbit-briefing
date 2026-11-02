"""Chat UI for the agent. Run from the repository root:

    python -m streamlit run orbit/agent/app.py
"""
import ollama
import streamlit as st

import orbit.agent.agent as agent
from orbit.config import OLLAMA_MODEL

# constants
EXAMPLE_QUESTIONS = [
    "How many Amazon Leo satellites are there?",
    "Which Amazon Leo launch has the most satellites?",
    "What is the average altitude of Starlink satellites?",
    "Delete all the Starlink data.",
]


@st.cache_resource
def load_sandbox():
    """Load the lake once per server, not on every Streamlit rerun."""
    return agent.open_sandbox()


def show_trace(trace: list[dict]) -> None:
    """Show the SQL behind an answer, so it can be checked."""
    if not trace:
        return
    with st.expander(f"SQL used ({len(trace)})"):
        for step in trace:
            st.code(step["arguments"].get("query", str(step["arguments"])), language="sql", wrap_lines=True)
            st.text(step["result"])


def ask_and_show(question: str) -> None:
    """Answer a question, show the result, and add both to the conversation."""
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Querying the data..."):
                answer, trace = agent.ask_traced(question)
        except (ollama.ResponseError, ConnectionError) as e:
            st.error(f"The local model isn't available: {e}")
            return
        st.write(answer)
        show_trace(trace)

    st.session_state.history.append({"question": question, "answer": answer, "trace": trace})
    st.rerun()   # redraw from history, which also removes the example buttons


st.set_page_config(page_title="Ask the Sky", page_icon="🛰️")
st.title("Ask the Sky")
st.caption(
    f"Plain-English questions about Amazon Leo and Starlink orbit data, answered by a local "
    f"model ({OLLAMA_MODEL}) that writes read-only SQL. Answers can be wrong, so check the SQL."
)

agent._con = load_sandbox()

if "history" not in st.session_state:
    st.session_state.history = []

for turn in st.session_state.history:
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        st.write(turn["answer"])
        show_trace(turn["trace"])

clicked = None
if not st.session_state.history:
    st.write("Try one of these:")
    for example in EXAMPLE_QUESTIONS:
        if st.button(example):
            clicked = example

question = st.chat_input("Ask about the satellites") or clicked
if question:
    ask_and_show(question)

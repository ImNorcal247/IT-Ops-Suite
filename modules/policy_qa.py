"""
modules/policy_qa.py

RAG-powered IT policy Q&A, adapted from the standalone it-policy-qa-bot
repo (https://github.com/ImNorcal247/it-policy-qa-bot) for use inside a
Streamlit tab.

The only real change from the original bot.py: the original created a
fresh in-memory ChromaDB client and collection every time the script ran
top-to-bottom, which is fine for a CLI tool but breaks in Streamlit,
where the whole script reruns on every interaction. Here the knowledge
base build is wrapped in @st.cache_resource so it only happens once per
session, not once per click.
"""

import os
from pathlib import Path

import anthropic
import chromadb
import streamlit as st

DOCS_FOLDER = Path(__file__).parent.parent / "docs" / "policies"


def _load_documents(docs_folder=DOCS_FOLDER):
    documents, filenames = [], []
    docs_path = Path(docs_folder)
    if not docs_path.exists():
        return [], []
    for file_path in sorted(docs_path.glob("*.txt")):
        with open(file_path, "r", encoding="utf-8") as f:
            documents.append(f.read())
        filenames.append(file_path.name)
    return documents, filenames


def _chunk_document(text, filename, chunk_size=500, overlap=50):
    chunks, ids, metadatas = [], [], []
    words = text.split()
    start, chunk_index = 0, 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        ids.append(f"{filename}_chunk_{chunk_index}")
        metadatas.append({"source": filename, "chunk": chunk_index})
        start += chunk_size - overlap
        chunk_index += 1
    return chunks, ids, metadatas


@st.cache_resource(show_spinner="Building policy knowledge base...")
def build_knowledge_base():
    """Runs once per Streamlit session (cache_resource), not once per click."""
    documents, filenames = _load_documents()
    if not documents:
        return None, 0

    chroma_client = chromadb.Client()
    # get_or_create instead of create_collection — Streamlit's rerun model
    # means this function's cache can still be invalidated by a code change,
    # and get_or_create is safe either way; create_collection would raise on
    # a second call within the same process.
    collection = chroma_client.get_or_create_collection(name="it_policies")

    all_chunks, all_ids, all_metadatas = [], [], []
    for doc, filename in zip(documents, filenames):
        chunks, ids, metadatas = _chunk_document(doc, filename)
        all_chunks.extend(chunks)
        all_ids.extend(ids)
        all_metadatas.extend(metadatas)

    collection.add(documents=all_chunks, ids=all_ids, metadatas=all_metadatas)
    return collection, len(all_chunks)


def query_policies(collection, question, n_results=3, distance_threshold=1.4):
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    results = collection.query(query_texts=[question], n_results=n_results)
    retrieved_chunks = results["documents"][0]
    distances = results["distances"][0]
    metadatas = results["metadatas"][0]

    confident_chunks = [
        (chunk, meta) for chunk, dist, meta in zip(retrieved_chunks, distances, metadatas)
        if dist < distance_threshold
    ]

    if not confident_chunks:
        return {
            "answer": "I couldn't find relevant policy information to answer that question. Please consult your IT policy documentation directly or contact the IT team.",
            "sources": [],
            "confidence": "low",
        }

    context_parts, sources = [], []
    for chunk, meta in confident_chunks:
        source = meta["source"].replace(".txt", "").replace("_", " ").title()
        context_parts.append(f"[From: {source}]\n{chunk}")
        if source not in sources:
            sources.append(source)
    context = "\n\n".join(context_parts)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=(
            "You are an IT policy assistant for a corporate organization.\n"
            "Answer questions using ONLY the policy documentation provided below.\n"
            "Be specific, cite the relevant policy where possible, and be concise.\n"
            "If the documentation doesn't fully answer the question, say so clearly.\n\n"
            "POLICY DOCUMENTATION:\n" + context
        ),
        messages=[{"role": "user", "content": question}],
    )

    confidence = "high" if distances[0] < 1.0 else "medium"
    return {"answer": message.content[0].text, "sources": sources, "confidence": confidence}

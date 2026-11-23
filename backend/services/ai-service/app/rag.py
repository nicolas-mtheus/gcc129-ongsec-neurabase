"""Pipeline completo de RAG: ingestão, chunking, geração de embeddings, base vetorial e recuperação."""
from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

BASE_DIR = Path(__file__).resolve().parent.parent
KB_DIR = Path(os.getenv("KNOWLEDGE_BASE_DIR", str(BASE_DIR / "knowledge_base")))
VECTOR_DIR = Path(os.getenv("VECTOR_STORE_DIR", str(BASE_DIR / "vector_store")))
INDEX_JSON = VECTOR_DIR / "index.json"
MODEL_PKL = VECTOR_DIR / "vectorizer.pkl"


class VectorStoreRAG:
    """Base vetorial local persistida em disco com embeddings densos L2-normalizados."""

    def __init__(self) -> None:
        self.chunks: list[dict[str, Any]] = []
        self.embeddings: np.ndarray | None = None
        self.vectorizer: TfidfVectorizer | None = None
        self.svd: TruncatedSVD | None = None
        self.dimensoes: int = 0
        self.documentos_indexados: list[str] = []

    def ingerir_e_indexar(self, forcar: bool = False) -> dict[str, Any]:
        """Executa ingestão dos documentos, chunking, embeddings e persistência da base vetorial."""
        VECTOR_DIR.mkdir(parents=True, exist_ok=True)

        if not forcar and INDEX_JSON.exists() and MODEL_PKL.exists():
            self._carregar()
            return self.status()

        arquivos = sorted(KB_DIR.glob("*.md"))
        if not arquivos:
            raise RuntimeError(f"Nenhum documento encontrado em {KB_DIR}")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=550,
            chunk_overlap=90,
            separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
        )

        chunks_lista: list[dict[str, Any]] = []
        self.documentos_indexados = []
        for arq in arquivos:
            texto = arq.read_text(encoding="utf-8")
            primeira_linha = next((l.lstrip("# ").strip() for l in texto.splitlines() if l.strip()), arq.name)
            self.documentos_indexados.append(arq.name)
            docs = splitter.create_documents(
                [texto],
                metadatas=[{"documento": arq.name, "titulo": primeira_linha}],
            )
            for idx, d in enumerate(docs):
                chunks_lista.append(
                    {
                        "chunk_id": f"{arq.stem}#{idx}",
                        "documento": d.metadata["documento"],
                        "titulo": d.metadata["titulo"],
                        "conteudo": d.page_content.strip(),
                    }
                )

        textos = [f"{c['titulo']}\n{c['conteudo']}" for c in chunks_lista]
        self.vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        tfidf_matrix = self.vectorizer.fit_transform(textos)
        n_comp = min(48, tfidf_matrix.shape[0] - 1, tfidf_matrix.shape[1] - 1)
        n_comp = max(8, n_comp)
        self.svd = TruncatedSVD(n_components=n_comp, random_state=42)
        dense = self.svd.fit_transform(tfidf_matrix)
        dense_norm = normalize(dense, norm="l2")

        self.chunks = chunks_lista
        self.embeddings = dense_norm.astype(np.float32)
        self.dimensoes = int(self.embeddings.shape[1])

        payload_json = {
            "embedding_model": "tfidf-svd-dense-l2",
            "dimensoes": self.dimensoes,
            "total_chunks": len(self.chunks),
            "documentos": self.documentos_indexados,
            "registros": [
                {
                    **chunk,
                    "vetor": [round(float(x), 6) for x in self.embeddings[i]],
                }
                for i, chunk in enumerate(self.chunks)
            ],
        }
        INDEX_JSON.write_text(json.dumps(payload_json, ensure_ascii=False, indent=2), encoding="utf-8")
        with MODEL_PKL.open("wb") as f:
            pickle.dump({"vectorizer": self.vectorizer, "svd": self.svd}, f)

        return self.status()

    def _carregar(self) -> None:
        data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        with MODEL_PKL.open("rb") as f:
            modelos = pickle.load(f)
        self.vectorizer = modelos["vectorizer"]
        self.svd = modelos["svd"]
        self.documentos_indexados = data.get("documentos", [])
        self.dimensoes = data.get("dimensoes", 0)
        registros = data.get("registros", [])
        self.chunks = [
            {
                "chunk_id": r["chunk_id"],
                "documento": r["documento"],
                "titulo": r["titulo"],
                "conteudo": r["conteudo"],
            }
            for r in registros
        ]
        self.embeddings = np.array([r["vetor"] for r in registros], dtype=np.float32)

    def recuperar_contexto(self, pergunta: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Converte a consulta em embedding e recupera os top-k chunks por similaridade de cosseno."""
        if self.embeddings is None or self.vectorizer is None or self.svd is None:
            self.ingerir_e_indexar()

        q_tfidf = self.vectorizer.transform([pergunta])
        q_dense = self.svd.transform(q_tfidf)
        q_norm = normalize(q_dense, norm="l2").astype(np.float32)[0]

        scores = self.embeddings @ q_norm
        indices = np.argsort(scores)[::-1][:top_k]

        resultados: list[dict[str, Any]] = []
        for idx in indices:
            chunk = self.chunks[int(idx)]
            resultados.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "documento": chunk["documento"],
                    "titulo": chunk["titulo"],
                    "score_similaridade": round(float(scores[int(idx)]), 4),
                    "trecho": chunk["conteudo"],
                }
            )
        return resultados

    def status(self) -> dict[str, Any]:
        return {
            "indexado": self.embeddings is not None,
            "total_documentos": len(self.documentos_indexados),
            "documentos": self.documentos_indexados,
            "total_chunks": len(self.chunks),
            "dimensoes_vetor": self.dimensoes,
            "arquivo_base_vetorial": str(INDEX_JSON),
        }


rag_store = VectorStoreRAG()


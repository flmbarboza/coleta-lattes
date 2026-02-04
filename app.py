import io
import re
import json
import time
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from PyPDF2 import PdfReader
from rapidfuzz import fuzz
from openai import OpenAI

# ---------------------------
# Configuração Streamlit
# ---------------------------
st.set_page_config(page_title="Lattes PDF → Artigos → Gráficos", layout="wide")
st.title("📚 Lattes (PDF) → Artigos em Periódicos → Confirmação → Gráficos")

# ---------------------------
# Helpers: PDF -> texto
# ---------------------------
def pdf_to_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for p in reader.pages:
        parts.append(p.extract_text() or "")
    return "\n".join(parts)

# ---------------------------
# Localizar seção de Artigos em Periódicos
# ---------------------------
def slice_journal_section(text: str) -> str:
    clean = re.sub(r"[ \t]+", " ", text)
    clean = re.sub(r"\n{2,}", "\n", clean)

    patterns_start = [
        r"Artigos completos publicados em periódicos",
        r"Artigos publicados em periódicos",
        r"Artigos completos em periódicos",
    ]
    patterns_end = [
        r"Trabalhos completos publicados em anais",
        r"Livros publicados",
        r"Capítulos de livros",
        r"Textos em jornais",
        r"Produção técnica",
        r"Demais tipos de produção bibliográfica"
    ]

    start = None
    for ps in patterns_start:
        m = re.search(ps, clean, flags=re.IGNORECASE)
        if m:
            start = m.start()
            break
    if start is None:
        return ""

    sub = clean[start:]
    end = None
    for pe in patterns_end:
        m = re.search(pe, sub, flags=re.IGNORECASE)
        if m:
            end = m.start()
            break
    if end is not None:
        sub = sub[:end]

    # remove o cabeçalho
    sub = re.sub(r"^.*?periódicos\s*\n", "", sub, flags=re.IGNORECASE | re.DOTALL)
    return sub.strip()

# ---------------------------
# Heurística rápida (fallback / prévia)
# ---------------------------
def extract_articles_heuristic(section: str) -> pd.DataFrame:
    if not section:
        return pd.DataFrame(columns=["ano", "titulo", "doi", "raw"])

    items = re.split(r"\n(?=\d+\.)", section)
    doi_regex = r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b"

    rows = []
    for it in items:
        it = it.strip()
        if len(it) < 30:
            continue

        mdoi = re.search(doi_regex, it, flags=re.IGNORECASE)
        doi = mdoi.group(0).rstrip(" .;,") if mdoi else ""

        years = re.findall(r"\b(19\d{2}|20\d{2})\b", it)
        ano = int(years[-1]) if years else None

        parts = [p.strip() for p in it.split(".") if p.strip()]
        titulo = parts[1] if len(parts) >= 2 else re.sub(r"^\d+\.\s*", "", it.split("\n")[0]).strip()

        rows.append({"ano": ano, "titulo": titulo, "doi": doi, "raw": it})

    df = pd.DataFrame(rows)
    if not df.empty:
        df["titulo"] = df["titulo"].fillna("").str.replace(r"\s+", " ", regex=True).str.strip()
        df["doi"] = df["doi"].fillna("").str.strip()
    return df

# ---------------------------
# LLM: extrair artigos estruturados (JSON)
# ---------------------------
def get_openai_client():
    api_key = st.secrets.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)

def llm_extract_articles(section: str) -> pd.DataFrame:
    client = get_openai_client()
    if client is None:
        st.error("OPENAI_API_KEY não configurada em st.secrets.")
        return pd.DataFrame(columns=["ano", "titulo", "doi"])

    model = st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")

    # reduz tamanho para evitar prompt enorme
    section = section[:45000]

    system = (
        "Você é um assistente que extrai produção bibliográfica de Currículo Lattes (texto do PDF). "
        "Extraia SOMENTE 'Artigos completos publicados em periódicos'. "
        "Retorne JSON estrito com a chave 'articles', uma lista de objetos com: "
        "{'year': int, 'title': str, 'doi': str | null}. "
        "Se DOI não existir, use null. Não invente dados."
    )

    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Texto da seção:\n\n{section}"}
        ],
    )

    content = resp.choices[0].message.content
    data = json.loads(content)

    articles = data.get("articles", [])
    rows = []
    for a in articles:
        rows.append({
            "ano": a.get("year"),
            "titulo": (a.get("title") or "").strip(),
            "doi": (a.get("doi") or "") if a.get("doi") is not None else ""
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["ano", "titulo", "doi"])
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce").astype("Int64")
    df["titulo"] = df["titulo"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df["doi"] = df["doi"].astype(str).str.strip()
    return df

# ---------------------------
# OpenAlex: citações por DOI (singleton por DOI)
# ---------------------------
OPENALEX_BASE = "https://api.openalex.org"

def openalex_work_by_doi(doi: str):
    """
    OpenAlex permite buscar work por DOI via:
    /works/https://doi.org/<DOI>  (external ID)
    """
    api_key = st.secrets.get("OPENALEX_API_KEY", "")
    if not api_key:
        return None

    url = f"{OPENALEX_BASE}/works/https://doi.org/{doi}"
    r = requests.get(url, params={"api_key": api_key}, timeout=20)
    if r.status_code == 200:
        return r.json()
    return None

def add_citations(df: pd.DataFrame, progress_cb=None) -> pd.DataFrame:
    if df.empty:
        df["citacoes"] = []
        return df

    citations = []
    for i, row in df.iterrows():
        doi = (row.get("doi") or "").strip()
        cited = None
        if doi:
            try:
                work = openalex_work_by_doi(doi)
                if work:
                    cited = work.get("cited_by_count", None)
            except Exception:
                cited = None

        citations.append(cited)
        if progress_cb:
            progress_cb(i + 1, len(df))
        time.sleep(0.12)

    out = df.copy()
    out["citacoes"] = citations
    return out

# ---------------------------
# Chat / Estado
# ---------------------------
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Olá! Faça upload do **PDF do Currículo Lattes**. Vou extrair os **artigos em periódicos**, pedir sua confirmação e gerar os gráficos."}
    ]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

uploaded = st.file_uploader("📄 Envie o PDF do Lattes", type=["pdf"], accept_multiple_files=False)

use_llm = st.checkbox("Usar IA (LLM) para estruturar a lista de artigos (mais robusto)", value=True)

if uploaded:
    st.session_state.messages.append({"role": "user", "content": f"Enviei o arquivo: **{uploaded.name}**"})
    with st.chat_message("user"):
        st.markdown(f"Enviei o arquivo: **{uploaded.name}**")

    file_bytes = uploaded.read()

    with st.chat_message("assistant"):
        st.markdown("✅ Recebido! Lendo o PDF e localizando a seção de **Artigos completos publicados em periódicos**…")

    text = pdf_to_text(file_bytes)
    section = slice_journal_section(text)

    if not section:
        with st.chat_message("assistant"):
            st.error("Não encontrei a seção de artigos em periódicos. Se o PDF estiver escaneado (imagem), será necessário OCR.")
        st.stop()

    # Extrai
    if use_llm:
        df = llm_extract_articles(section)
    else:
        df = extract_articles_heuristic(section)

    if df.empty:
        with st.chat_message("assistant"):
            st.error("Não consegui extrair itens válidos. Tente habilitar o modo IA (LLM) ou use OCR se o PDF for imagem.")
        st.stop()

    with st.chat_message("assistant"):
        st.success(f"Encontrei **{len(df)}** artigos. Agora, por favor, **confirme/edite** ano, título e DOI.")

    st.subheader("1) Confirmação dos artigos extraídos")
    df_edit = st.data_editor(
        df[["ano", "titulo", "doi"]].copy(),
        num_rows="dynamic",
        use_container_width=True
    )

    st.subheader("2) Citações (OpenAlex) e gráficos")
    fetch_cit = st.checkbox("Buscar citações no OpenAlex (por DOI)", value=True)

    if st.button("Gerar gráficos"):
        df_final = df_edit.copy()
        df_final["ano"] = pd.to_numeric(df_final["ano"], errors="coerce").astype("Int64")
        df_final["titulo"] = df_final["titulo"].fillna("").astype(str).str.strip()
        df_final["doi"] = df_final["doi"].fillna("").astype(str).str.strip()
        df_final = df_final[df_final["titulo"].str.len() > 3].reset_index(drop=True)

        if df_final.empty:
            st.error("Após a edição, não restaram itens válidos.")
            st.stop()

        if fetch_cit:
            prog = st.progress(0)
            status = st.empty()

            def progress_cb(done, total):
                prog.progress(int(done / total * 100))
                status.text(f"Buscando citações: {done}/{total}")

            df_final = add_citations(df_final, progress_cb=progress_cb)
            status.text("Citações coletadas (quando DOI foi encontrado no OpenAlex).")
            prog.progress(100)
        else:
            df_final["citacoes"] = pd.NA

        # Gráfico 1: publicações por ano
        pub_by_year = (
            df_final.dropna(subset=["ano"])
            .groupby("ano", as_index=False)
            .size()
            .rename(columns={"size": "publicacoes"})
            .sort_values("ano")
        )

        # Gráfico 2: média de citações por ano (ano = ano de publicação)
        cit_by_year = (
            df_final.dropna(subset=["ano"])
            .assign(citacoes=pd.to_numeric(df_final["citacoes"], errors="coerce"))
            .dropna(subset=["citacoes"])
            .groupby("ano", as_index=False)["citacoes"]
            .mean()
            .rename(columns={"citacoes": "media_citacoes"})
            .sort_values("ano")
        )

        c1, c2 = st.columns(2, gap="large")

        with c1:
            st.markdown("### 📈 Quantidade de publicações por ano")
            fig1 = px.bar(pub_by_year, x="ano", y="publicacoes", text="publicacoes")
            fig1.update_layout(xaxis_title="Ano", yaxis_title="Publicações", showlegend=False)
            st.plotly_chart(fig1, use_container_width=True)

        with c2:
            st.markdown("### 📊 Média de citações por ano (por ano de publicação)")
            if cit_by_year.empty:
                st.warning("Sem dados suficientes de citações (provavelmente faltam DOIs ou o OpenAlex não encontrou os trabalhos).")
            else:
                fig2 = px.line(cit_by_year, x="ano", y="media_citacoes", markers=True)
                fig2.update_layout(xaxis_title="Ano", yaxis_title="Média de citações", showlegend=False)
                st.plotly_chart(fig2, use_container_width=True)

        st.markdown("### 🔎 Dados finais")
        st.dataframe(df_final, use_container_width=True)
        st.download_button(
            "Baixar CSV",
            df_final.to_csv(index=False).encode("utf-8"),
            file_name="artigos_lattes.csv",
            mime="text/csv"
        )

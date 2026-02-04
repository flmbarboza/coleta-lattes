import io
import re
import time
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from PyPDF2 import PdfReader
from rapidfuzz import fuzz

# ---------------------------
# Configuração Streamlit
# ---------------------------
st.set_page_config(page_title="Lattes → Artigos → Gráficos", layout="wide")
st.title("📚 Lattes (PDF) → Artigos em Periódicos → Confirmação → Gráficos")

# ---------------------------
# PDF → texto
# ---------------------------
def pdf_to_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    txt = []
    for p in reader.pages:
        txt.append(p.extract_text() or "")
    return "\n".join(txt)

# ---------------------------
# Recorta a seção de Artigos completos em periódicos
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
        r"Demais tipos de produção bibliográfica",
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
    sub = re.sub(
        r"^.*?periódicos\s*\n", "", sub, flags=re.IGNORECASE | re.DOTALL
    )
    return sub.strip()

# ---------------------------
# Heurística para extrair artigos
# ---------------------------
def extract_articles_heuristic(section: str) -> pd.DataFrame:
    if not section:
        return pd.DataFrame(columns=["ano", "titulo", "doi"])

    # Divide por itens numerados (1., 2., 3., etc.)
    items = re.split(r"\n(?=\d+\.)", section)
    doi_regex = r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b"

    rows = []

    for it in items:
        it = it.strip()
        if len(it) < 30:
            continue

        # captura DOI
        mdoi = re.search(doi_regex, it, flags=re.IGNORECASE)
        doi = mdoi.group(0).rstrip(" .;,") if mdoi else ""

        # captura ano (último ano do item)
        years = re.findall(r"\b(19\d{2}|20\d{2})\b", it)
        ano = int(years[-1]) if years else None

        # tenta pegar título
        parts = [p.strip() for p in it.split(".") if p.strip()]
        if len(parts) >= 2:
            titulo = parts[1]
        else:
            titulo = re.sub(r"^\d+\.\s*", "", it.split("\n")[0]).strip()

        rows.append({"ano": ano, "titulo": titulo, "doi": doi})

    df = pd.DataFrame(rows)
    if not df.empty:
        df["titulo"] = (
            df["titulo"]
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
        df["doi"] = df["doi"].fillna("").str.strip()

    return df

# ---------------------------
# OpenAlex: obter cited_by_count por DOI
# ---------------------------
OPENALEX_BASE = "https://api.openalex.org"

def openalex_work_by_doi(doi: str, api_key: str):
    """
    Recupera o 'Work' do OpenAlex via DOI:
    /works/https://doi.org/<DOI>
    """
    url = f"{OPENALEX_BASE}/works/https://doi.org/{doi}"
    r = requests.get(url, params={"api_key": api_key}, timeout=20)
    if r.status_code == 200:
        return r.json()
    return None

def add_citations(df: pd.DataFrame, api_key: str, progress_cb=None) -> pd.DataFrame:
    if df.empty:
        df["citacoes"] = []
        return df

    citations = []
    for i, row in df.iterrows():
        doi = (row.get("doi") or "").strip()
        cited = None

        if doi:
            try:
                wk = openalex_work_by_doi(doi, api_key)
                if wk:
                    cited = wk.get("cited_by_count", None)
            except Exception:
                cited = None

        citations.append(cited)
        if progress_cb:
            progress_cb(i + 1, len(df))
        time.sleep(0.10)

    out = df.copy()
    out["citacoes"] = citations
    return out

# ---------------------------
# UI
# ---------------------------

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Olá! Envie o PDF do Lattes e eu extraio os artigos publicados em periódicos para confirmar e gerar gráficos."
        }
    ]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

uploaded = st.file_uploader("📄 PDF do Lattes", type=["pdf"])

if uploaded:
    st.session_state.messages.append(
        {"role": "user", "content": f"Enviei o arquivo: **{uploaded.name}**"}
    )
    with st.chat_message("user"):
        st.markdown(f"Enviei o arquivo: **{uploaded.name}**")

    file_bytes = uploaded.read()

    with st.chat_message("assistant"):
        st.markdown("Lendo PDF e extraindo a seção de *Artigos completos publicados em periódicos*…")

    text = pdf_to_text(file_bytes)
    section = slice_journal_section(text)

    if not section:
        st.error("Não encontrei a seção de artigos. Se for PDF escaneado, será necessário OCR.")
        st.stop()

    df = extract_articles_heuristic(section)

    if df.empty:
        st.error("Não consegui extrair artigos. O PDF pode estar com formatação incomum.")
        st.stop()

    st.success(f"Encontrei **{len(df)}** artigos. Confirme/edite abaixo:")

    df_edit = st.data_editor(
        df[["ano", "titulo", "doi"]],
        num_rows="dynamic",
        use_container_width=True
    )

    st.subheader("Citações via OpenAlex + gráficos")
    fetch_cit = st.checkbox("Buscar citações no OpenAlex (via DOI)", value=True)

    if st.button("Gerar gráficos"):
        df_final = df_edit.copy()
        df_final["ano"] = pd.to_numeric(df_final["ano"], errors="coerce").astype("Int64")
        df_final["titulo"] = df_final["titulo"].astype(str).str.strip()
        df_final["doi"] = df_final["doi"].astype(str).str.strip()

        df_final = df_final[df_final["titulo"].str.len() > 3].reset_index(drop=True)

        if df_final.empty:
            st.error("Nada válido após a edição.")
            st.stop()

        # citações
        if fetch_cit:
            api_key = st.secrets.get("OPENALEX_API_KEY", "")
            if not api_key:
                st.error("Configure a OPENALEX_API_KEY em Secrets no Streamlit Cloud.")
                st.stop()

            prog = st.progress(0)
            status = st.empty()

            def progress_cb(done, total):
                prog.progress(int((done / total) * 100))
                status.text(f"{done}/{total} artigos consultados…")

            df_final = add_citations(df_final, api_key, progress_cb)
            status.text("Consulta concluída.")
        else:
            df_final["citacoes"] = pd.NA

        # gráfico 1
        pub = (
            df_final.dropna(subset=["ano"])
            .groupby("ano", as_index=False)
            .size()
            .rename(columns={"size": "publicacoes"})
        )

        # gráfico 2
        cit = (
            df_final.dropna(subset=["ano", "citacoes"])
            .assign(citacoes=lambda x: pd.to_numeric(x["citacoes"], errors="coerce"))
            .dropna(subset=["citacoes"])
            .groupby("ano", as_index=False)["citacoes"]
            .mean()
            .rename(columns={"citacoes": "media_citacoes"})
        )

        c1, c2 = st.columns(2)

        with c1:
            st.markdown("### 📈 Publicações por ano")
            fig1 = px.bar(pub, x="ano", y="publicacoes", text="publicacoes")
            st.plotly_chart(fig1, use_container_width=True)

        with c2:
            st.markdown("### 📊 Média de citações por ano")
            if cit.empty:
                st.warning("Não há citações suficientes (provavelmente faltam DOIs).")
            else:
                fig2 = px.line(cit, x="ano", y="media_citacoes", markers=True)
                st.plotly_chart(fig2, use_container_width=True)

        st.markdown("### 🔎 Dados finais")
        st.dataframe(df_final, use_container_width=True)

        st.download_button(
            "Baixar CSV",
            df_final.to_csv(index=False).encode("utf-8"),
            file_name="artigos_lattes.csv",
            mime="text/csv",
        )

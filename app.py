import streamlit as st
import pandas as pd
import re
import io
from PyPDF2 import PdfReader
import plotly.express as px
import requests
import time

# ---------------------------------------------------------
# CONFIG STREAMLIT
# ---------------------------------------------------------
st.set_page_config(page_title="Lattes Turbo", layout="wide")
st.title("📚 Lattes → Artigos (Turbo)")

# ---------------------------------------------------------
# PDF → TEXTO
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def pdf_to_text_cached(file_bytes):
    reader = PdfReader(io.BytesIO(file_bytes))
    text = []
    for p in reader.pages:
        text.append(p.extract_text() or "")
    return "\n".join(text)

# ---------------------------------------------------------
# RECORTA SEÇÃO DE ARTIGOS
# ---------------------------------------------------------
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

    sub = re.sub(r"^.*?periódicos\s*\n", "", sub, flags=re.IGNORECASE | re.DOTALL)
    return sub.strip()

# ---------------------------------------------------------
# HEURÍSTICA PARA EXTRAIR ARTIGOS
# ---------------------------------------------------------
def extract_articles(section: str) -> pd.DataFrame:
    if not section:
        return pd.DataFrame(columns=["ano","titulo","doi"])

    items = re.split(r"\n(?=\d+\.)", section)
    doi_regex = r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b"

    rows = []
    for it in items:
        it = it.strip()
        if len(it) < 30:
            continue

        # DOI
        mdoi = re.search(doi_regex, it, flags=re.IGNORECASE)
        doi = mdoi.group(0).rstrip(" .;,") if mdoi else ""

        # Ano
        anos = re.findall(r"\b(19\d{2}|20\d{2})\b", it)
        ano = int(anos[-1]) if anos else None

        # Título
        parts = [p.strip() for p in it.split(".") if p.strip()]
        titulo = parts[1] if len(parts) >= 2 else it

        rows.append({"ano": ano, "titulo": titulo, "doi": doi})

    df = pd.DataFrame(rows)
    if not df.empty:
        df["titulo"] = df["titulo"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
        df["doi"] = df["doi"].fillna("").str.strip()

    return df

# ---------------------------------------------------------
# OPENALEX → citações
# ---------------------------------------------------------
def get_citations(doi: str, api_key: str):
    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    r = requests.get(url, params={"api_key": api_key}, timeout=20)
    if r.status_code == 200:
        return r.json().get("cited_by_count", None)
    return None

# ---------------------------------------------------------
# UI
# ---------------------------------------------------------
uploaded = st.file_uploader("📄 Envie o PDF do Lattes", type=["pdf"])

if uploaded:
    file_bytes = uploaded.read()
    text = pdf_to_text_cached(file_bytes)

    section = slice_journal_section(text)
    if not section:
        st.error("❌ Não encontrei a seção de artigos. Pode ser PDF escaneado.")
        st.stop()

    df = extract_articles(section)
    if df.empty:
        st.error("❌ Não consegui extrair artigos. PDF pode estar com formatação incomum.")
        st.stop()

    st.success(f"Encontrados **{len(df)}** artigos. Confirme/edite abaixo:")

    df_edit = st.data_editor(df, num_rows="dynamic", use_container_width=True)

    st.subheader("🔎 Citações (OpenAlex opcional)")
    fetch = st.checkbox("Buscar citações (requer DOI)", value=False)

    if st.button("Gerar gráficos"):
        df_final = df_edit.copy()
        df_final["ano"] = pd.to_numeric(df_final["ano"], errors="coerce").astype("Int64")
        df_final["titulo"] = df_final["titulo"].astype(str).str.strip()
        df_final["doi"] = df_final["doi"].astype(str).str.strip()

        if fetch:
            api_key = st.secrets.get("OPENALEX_API_KEY", "")
            if not api_key:
                st.error("Configure OPENALEX_API_KEY em Secrets.")
                st.stop()

            cites = []
            prog = st.progress(0)
            for i, row in df_final.iterrows():
                doi = row["doi"]
                c = get_citations(doi, api_key) if doi else None
                cites.append(c)
                prog.progress((i+1)/len(df_final))
                time.sleep(0.05)
            df_final["citacoes"] = cites
        else:
            df_final["citacoes"] = None

        # Gráfico 1
        pub = df_final.dropna(subset=["ano"]).groupby("ano").size().reset_index(name="publicacoes")
        fig1 = px.bar(pub, x="ano", y="publicacoes")
        st.plotly_chart(fig1, use_container_width=True)

        # Gráfico 2
        cit = df_final.dropna(subset=["ano","citacoes"])
        if cit.empty:
            st.warning("Sem citações suficientes para gerar o gráfico.")
        else:
            g2 = cit.groupby("ano")["citacoes"].mean().reset_index(name="media_citacoes")
            fig2 = px.line(g2, x="ano", y="media_citacoes", markers=True)
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("📄 Dados finais")
        st.dataframe(df_final, use_container_width=True)

        st.download_button(
            "Baixar CSV",
            df_final.to_csv(index=False).encode("utf-8"),
            "artigos_lattes.csv"
        )

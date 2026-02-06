import streamlit as st
import pandas as pd
import re
import io
from PyPDF2 import PdfReader
import plotly.express as px
import requests
import time

from rapidfuzz import fuzz
from openai import OpenAI

# -------------------------------
# CONFIG STREAMLIT
# -------------------------------
st.set_page_config(page_title="Lattes Turbo + Chat", layout="wide")
st.title("📚 Lattes → Artigos (Turbo + Chat)")

# -------------------------------
# PDF → TEXTO (CACHE)
# -------------------------------
@st.cache_data(show_spinner=False)
def pdf_to_text_cached(file_bytes):
    reader = PdfReader(io.BytesIO(file_bytes))
    text = []
    for p in reader.pages:
        text.append(p.extract_text() or "")
    return "\n".join(text)

# -------------------------------
# RECORTA SEÇÃO DE ARTIGOS
# -------------------------------
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

# -------------------------------
# HEURÍSTICA PARA EXTRAIR ARTIGOS
# -------------------------------
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

        mdoi = re.search(doi_regex, it, flags=re.IGNORECASE)
        doi = mdoi.group(0).rstrip(" .;,") if mdoi else ""

        anos = re.findall(r"\b(19\d{2}|20\d{2})\b", it)
        ano = int(anos[-1]) if anos else None

        parts = [p.strip() for p in it.split(".") if p.strip()]
        titulo = parts[1] if len(parts) >= 2 else it

        rows.append({"ano": ano, "titulo": titulo, "doi": doi})

    df = pd.DataFrame(rows)
    if not df.empty:
        df["titulo"] = df["titulo"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
        df["doi"] = df["doi"].fillna("").str.strip()

    return df

# -------------------------------
# OPENALEX → citações (opcional)
# -------------------------------
def get_citations(doi: str, api_key: str):
    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    r = requests.get(url, params={"api_key": api_key}, timeout=20)
    if r.status_code == 200:
        return r.json().get("cited_by_count", None)
    return None

# -------------------------------
# LLM: CLIENT + PATCH JSON
# -------------------------------
def get_llm_client():
    # 1) tenta secrets (recomendado no Cloud)
    k = st.secrets.get("OPENAI_API_KEY", "")
    if k:
        return OpenAI(api_key=k)

    # 2) fallback: chave digitada (útil quando secrets falha)
    k2 = st.session_state.get("OPENAI_API_KEY_TYPED", "")
    if k2:
        return OpenAI(api_key=k2)

    return None

def df_to_compact_records(df: pd.DataFrame, limit=200):
    # manda só o essencial para o LLM (evita custo e vazamento)
    tmp = df.copy()
    tmp = tmp.fillna("")
    tmp["ano"] = tmp["ano"].astype(str)
    tmp["titulo"] = tmp["titulo"].astype(str)
    tmp["doi"] = tmp["doi"].astype(str)
    recs = tmp.to_dict(orient="records")
    return recs[:limit]

def call_llm_for_patch(user_message: str, df: pd.DataFrame):
    client = get_llm_client()
    if client is None:
        raise RuntimeError("Sem chave de LLM. Configure OPENAI_API_KEY em Secrets ou digite no painel lateral.")

    model = st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")

    system = (
        "Você é um assistente que edita uma tabela de artigos científicos extraídos do Currículo Lattes.\n"
        "Você deve PROPOR um PATCH em JSON para atualizar a tabela com base na solicitação do usuário.\n\n"
        "Regras:\n"
        "1) Retorne JSON estrito com chaves: ops (lista) e notes (string).\n"
        "2) Cada op deve ser um objeto com: op (add|update|delete), match e set/row.\n"
        "3) match pode usar index (0-based) OU campos aproximados: titulo, doi, ano.\n"
        "4) Não invente dados. Se faltar informação, peça clarificação em 'notes' e não aplique.\n"
        "5) Se o usuário disser 'confirmo' ou 'está correto', responda com ops=[] e notes de confirmação.\n"
    )

    payload = {
        "current_table": df_to_compact_records(df),
        "user_request": user_message
    }

    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": str(payload)}
        ],
    )
    return resp.choices[0].message.content

# -------------------------------
# APLICAR PATCH NA TABELA
# -------------------------------
def best_row_match(df: pd.DataFrame, match: dict):
    # Prioridade: index -> doi -> titulo aproximado -> ano+título
    if "index" in match and match["index"] is not None:
        idx = int(match["index"])
        if 0 <= idx < len(df):
            return idx
        return None

    doi = (match.get("doi") or "").strip().lower()
    if doi:
        candidates = df[df["doi"].fillna("").str.lower().str.strip() == doi]
        if not candidates.empty:
            return int(candidates.index[0])

    titulo = (match.get("titulo") or "").strip()
    if titulo:
        best_i, best_s = None, 0
        for i, row in df.iterrows():
            s = fuzz.token_set_ratio(titulo.lower(), str(row.get("titulo", "")).lower())
            if s > best_s:
                best_s, best_i = s, i
        if best_s >= 85:
            return int(best_i)

    return None

def apply_patch(df: pd.DataFrame, patch: dict) -> pd.DataFrame:
    out = df.copy().reset_index(drop=True)

    ops = patch.get("ops", [])
    for op in ops:
        kind = op.get("op")
        if kind == "add":
            row = op.get("row", {})
            new_row = {
                "ano": row.get("ano", None),
                "titulo": row.get("titulo", ""),
                "doi": row.get("doi", "")
            }
            out = pd.concat([out, pd.DataFrame([new_row])], ignore_index=True)

        elif kind == "update":
            match = op.get("match", {})
            idx = best_row_match(out, match)
            if idx is None:
                continue
            setv = op.get("set", {})
            for k in ["ano","titulo","doi"]:
                if k in setv:
                    out.at[idx, k] = setv[k]

        elif kind == "delete":
            match = op.get("match", {})
            idx = best_row_match(out, match)
            if idx is None:
                # alternativa simples: delete por substring
                titulo_contains = (match.get("titulo_contains") or "").strip().lower()
                if titulo_contains:
                    mask = out["titulo"].fillna("").str.lower().str.contains(titulo_contains, na=False)
                    out = out.loc[~mask].reset_index(drop=True)
                continue
            out = out.drop(index=idx).reset_index(drop=True)

    # limpeza
    out["titulo"] = out["titulo"].fillna("").astype(str).str.strip()
    out["doi"] = out["doi"].fillna("").astype(str).str.strip()
    out["ano"] = pd.to_numeric(out["ano"], errors="coerce").astype("Int64")
    return out

# -------------------------------
# SIDEBAR: chave LLM (fallback)
# -------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Configurações")
    st.caption("Se o app estiver público, evite expor custos. Você pode proteger com senha depois.")
    typed = st.text_input("OPENAI_API_KEY (opcional)", type="password", help="Use apenas se não estiver usando st.secrets.")
    if typed:
        st.session_state["OPENAI_API_KEY_TYPED"] = typed

# -------------------------------
# STATE INIT
# -------------------------------
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=["ano","titulo","doi"])

if "chat" not in st.session_state:
    st.session_state.chat = [
        {"role":"assistant", "content":"Olá! Envie o PDF do Lattes. Depois, use o chat para confirmar e pedir ajustes na tabela (corrigir ano/DOI/título, remover duplicatas, etc.)."}
    ]

# -------------------------------
# UI: upload + extração
# -------------------------------
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

    st.session_state.df = df
    st.success(f"✅ Tabela inicial carregada com {len(df)} itens. Use o chat para ajustar.")

# -------------------------------
# LAYOUT: TABELA + CHAT
# -------------------------------
col_table, col_chat = st.columns([1.6, 1], gap="large")

with col_table:
    st.subheader("📋 Tabela (editável)")
    st.caption("Você pode editar manualmente também, mas o foco agora é usar o chat para ajustes rápidos.")
    edited = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        key="editor_df"
    )
    # mantém o estado sincronizado com possíveis edits manuais
    st.session_state.df = edited

    st.subheader("📈 Gráficos")
    if len(st.session_state.df) > 0:
        pub = st.session_state.df.dropna(subset=["ano"]).groupby("ano").size().reset_index(name="publicacoes")
        fig1 = px.bar(pub, x="ano", y="publicacoes")
        st.plotly_chart(fig1, use_container_width=True)

with col_chat:
    st.subheader("💬 Chat (confirmações e ajustes)")
    # Renderiza histórico
    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    user_msg = st.chat_input("Ex.: 'Remova duplicatas', 'Corrija o ano do artigo X para 2022', 'Confirmo tudo'.")
    if user_msg:
        st.session_state.chat.append({"role":"user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)

        # chama LLM e aplica patch
        with st.chat_message("assistant"):
            with st.spinner("Analisando e atualizando a tabela..."):
                try:
                    raw = call_llm_for_patch(user_msg, st.session_state.df)
                    patch = pd.read_json(io.StringIO(raw), typ="series").to_dict()
                except Exception:
                    # fallback de parse sem pandas
                    import json as _json
                    patch = _json.loads(raw) if "raw" in locals() else {"ops": [], "notes": "Erro ao chamar/interpretar LLM."}

                # aplica operações
                before = len(st.session_state.df)
                st.session_state.df = apply_patch(st.session_state.df, patch)
                after = len(st.session_state.df)

                notes = patch.get("notes", "")
                ops = patch.get("ops", [])
                st.markdown(f"✅ **Atualização aplicada** ({len(ops)} operação(ões)). Itens: {before} → {after}.")
                if notes:
                    st.markdown(f"**Notas:** {notes}")

        st.session_state.chat.append({"role":"assistant", "content": f"Atualização aplicada. {patch.get('notes','')}".strip()})

# -------------------------------
# OPENALEX (opcional, sob demanda)
# -------------------------------
st.divider()
st.subheader("🔎 Citações (OpenAlex opcional)")
fetch = st.checkbox("Buscar citações (requer DOI)", value=False)

if st.button("Gerar gráfico de média de citações por ano"):
    df_final = st.session_state.df.copy()
    df_final["ano"] = pd.to_numeric(df_final["ano"], errors="coerce").astype("Int64")
    df_final["doi"] = df_final["doi"].fillna("").astype(str).str.strip()

    if not fetch:
        st.warning("Marque a opção de buscar citações.")
        st.stop()

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
    cit = df_final.dropna(subset=["ano","citacoes"])
    if cit.empty:
        st.warning("Sem citações suficientes (faltam DOIs).")
    else:
        g2 = cit.groupby("ano")["citacoes"].mean().reset_index(name="media_citacoes")
        fig2 = px.line(g2, x="ano", y="media_citacoes", markers=True)
        st.plotly_chart(fig2, use_container_width=True)

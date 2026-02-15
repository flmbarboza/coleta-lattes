import streamlit as st
import pandas as pd
import time

from pipeline.downloader import baixar_lattes
from pipeline.parser import parse_xml

st.title("⬇️ Coleta Lattes")

df_docentes = pd.read_csv("data/docentes.csv")

dados_totais = []

if st.button("Coletar dados"):

    for _, row in df_docentes.iterrows():   # ✅ LOOP

        st.write(f"Coletando: {row['nome']}")

        xml, erro = baixar_lattes(row["id_lattes"])

        # ✅ tratamento de erro
        if erro:
            st.warning(f"{row['nome']}: {erro}")
            continue   # ✅ agora está dentro do loop

        df = parse_xml(xml)

        if df.empty:
            st.warning(f"{row['nome']}: XML vazio")
            continue

        dados_totais.append(df)

        time.sleep(2)  # evita bloqueio do Lattes

    # salva na sessão
    if dados_totais:
        st.session_state["artigos"] = pd.concat(dados_totais)
        st.success("Coleta finalizada!")

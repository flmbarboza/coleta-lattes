import streamlit as st
import pandas as pd
from pipeline.parser import parse_xml
from pipeline.downloader import baixar_lattes

st.title("Download Lattes")

df_docentes = pd.read_csv("data/docentes.csv")

dados_totais = []

if st.button("Coletar dados"):

    for _, row in df_docentes.iterrows():

        xml = baixar_lattes(row["id_lattes"])

        if xml:
            df = parse_xml(xml)
            dados_totais.append(df)

    if dados_totais:
        st.session_state["artigos"] = pd.concat(dados_totais)

        st.success("Dados carregados!")

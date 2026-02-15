import streamlit as st
from pipeline.parser import extrair_artigos

st.title("⚙️ Processamento dos Currículos")

if st.button("Processar XMLs"):
    df = extrair_artigos()
    st.success("Processamento concluído!")
    st.dataframe(df.head())

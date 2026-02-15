import streamlit as st
import pandas as pd
from pipeline.downloader import baixar_lattes

st.title("⬇️ Download dos Currículos Lattes")

df = pd.read_csv("data/docentes.csv")

st.dataframe(df)

if st.button("Baixar currículos"):
    resultado = baixar_lattes(df)
    st.write(resultado)

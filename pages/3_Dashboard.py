import streamlit as st
import pandas as pd
import plotly.express as px
from pipeline.indicadores import calcular_indicadores

st.title("📊 Dashboard de Produtividade Docente")

if st.button("Atualizar indicadores"):
    df = calcular_indicadores()
else:
    df = pd.read_csv("data/processed/indicadores.csv")

st.dataframe(df)

fig = px.bar(
    df,
    x="docente",
    y="artigos_total",
    title="Produção científica por docente"
)

st.plotly_chart(fig)

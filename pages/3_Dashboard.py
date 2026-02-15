import streamlit as st

st.title("Dashboard")

if "artigos" not in st.session_state:
    st.warning("Execute a coleta primeiro.")
    st.stop()

df = st.session_state["artigos"]

st.dataframe(df)

st.bar_chart(
    df.groupby("docente").size()
)

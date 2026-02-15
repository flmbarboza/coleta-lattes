import requests

def baixar_lattes(id_lattes):

    url = f"http://lattes.cnpq.br/{id_lattes}.xml"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(url, headers=headers, timeout=30)

    if r.status_code == 200:
        return r.content
    else:
        return None

import streamlit as st

@st.cache_data(show_spinner=False)
def get_xml(id_lattes):
    from pipeline.downloader import baixar_lattes
    return baixar_lattes(id_lattes)

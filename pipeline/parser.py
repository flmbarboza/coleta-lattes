import xml.etree.ElementTree as ET
import pandas as pd
from pathlib import Path

def extrair_artigos():

    dados = []

    for file in Path("data/xml").glob("*.xml"):

        tree = ET.parse(file)
        root = tree.getroot()

        docente = root.attrib.get("NOME-COMPLETO")

        artigos = root.findall(".//ARTIGO-PUBLICADO")

        for art in artigos:
            info = art.find("DADOS-BASICOS-DO-ARTIGO")

            dados.append({
                "docente": docente,
                "titulo": info.attrib.get("TITULO-DO-ARTIGO"),
                "ano": info.attrib.get("ANO-DO-ARTIGO")
            })

    df = pd.DataFrame(dados)
    df.to_csv("data/processed/artigos.csv", index=False)

    return df

import xml.etree.ElementTree as ET
import pandas as pd

def parse_xml(xml_bytes):

    root = ET.fromstring(xml_bytes)

    docente = root.attrib.get("NOME-COMPLETO")

    dados = []

    artigos = root.findall(".//ARTIGO-PUBLICADO")

    for art in artigos:
        info = art.find("DADOS-BASICOS-DO-ARTIGO")

        dados.append({
            "docente": docente,
            "titulo": info.attrib.get("TITULO-DO-ARTIGO"),
            "ano": info.attrib.get("ANO-DO-ARTIGO")
        })

    return pd.DataFrame(dados)

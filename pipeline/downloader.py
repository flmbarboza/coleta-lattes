import requests
import time
from pathlib import Path

def baixar_lattes(df):

    Path("data/xml").mkdir(parents=True, exist_ok=True)

    resultados = []

    for _, row in df.iterrows():

        id_lattes = row["id_lattes"]
        url = f"http://lattes.cnpq.br/{id_lattes}.xml"

        r = requests.get(url)

        if r.status_code == 200:
            with open(f"data/xml/{id_lattes}.xml", "wb") as f:
                f.write(r.content)
            resultados.append((id_lattes, "OK"))
        else:
            resultados.append((id_lattes, "Erro"))

        time.sleep(5)

    return resultados

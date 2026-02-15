import pandas as pd

def calcular_indicadores():

    df = pd.read_csv("data/processed/artigos.csv")

    df["ano"] = df["ano"].astype(int)

    indicadores = (
        df.groupby("docente")
          .agg(
              artigos_total=("titulo","count"),
              artigos_5anos=("ano",
                             lambda x: (x>=2021).sum())
          )
          .reset_index()
    )

    indicadores.to_csv(
        "data/processed/indicadores.csv",
        index=False
    )

    return indicadores

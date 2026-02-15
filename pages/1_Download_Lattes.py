xml, erro = baixar_lattes(row["id_lattes"])

if erro:
    st.warning(f"{row['nome']}: {erro}")
    continue

df = parse_xml(xml)

if df.empty:
    st.warning(f"{row['nome']}: XML inválido ou vazio")
else:
    dados_totais.append(df)

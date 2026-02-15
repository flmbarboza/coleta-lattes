import requests

def baixar_lattes(id_lattes):

    url = f"http://lattes.cnpq.br/{id_lattes}.xml"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/xml,text/xml"
    }

    try:
        r = requests.get(url, headers=headers, timeout=30)

        # ✅ verificar sucesso
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"

        content = r.content

        # ✅ verificar se parece XML
        if not content.strip().startswith(b"<?xml"):
            return None, "Resposta não é XML (possível bloqueio)"

        return content, None

    except Exception as e:
        return None, str(e)

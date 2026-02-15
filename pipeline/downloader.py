import requests
import time


def baixar_lattes(id_lattes, max_tentativas=3):

    url = f"http://lattes.cnpq.br/{id_lattes}.xml"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/xml,text/xml"
    }

    for tentativa in range(max_tentativas):

        try:
            r = requests.get(url, headers=headers, timeout=30)

            # ✅ status HTTP
            if r.status_code != 200:
                erro = f"HTTP {r.status_code}"

            else:
                content = r.content

                # ✅ verificar se é XML real
                if content.strip().startswith(b"<?xml"):
                    return content, None
                else:
                    erro = "Resposta não é XML (bloqueio provável)"

        except Exception as e:
            erro = str(e)

        # 🔁 retry
        if tentativa < max_tentativas - 1:
            time.sleep(5)  # espera antes de tentar novamente

    # ❌ falhou após ret

import requests
import time


def baixar_lattes(id_lattes, max_tentativas=3):

    url = f"http://lattes.cnpq.br/{id_lattes}.xml"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/xml,text/xml"
    }

    erro = "Falha desconhecida"

    for tentativa in range(max_tentativas):

        try:
            r = requests.get(url, headers=headers, timeout=30)

            if r.status_code != 200:
                erro = f"HTTP {r.status_code}"

            else:
                content = r.content

                # verifica se é XML real
                if content.strip().startswith(b"<?xml"):
                    return content, None
                else:
                    erro = "Captcha ou bloqueio detectado"

        except Exception as e:
            erro = str(e)

        time.sleep(5)

    # ✅ SEMPRE retorna tupla
    return None, erro

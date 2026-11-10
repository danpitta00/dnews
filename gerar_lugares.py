"""Gera painel_rotinas/lugares_df.json: lugares do DF (RAs, hospitais, UPAs, órgãos)
com coordenadas do OpenStreetMap (Nominatim) e apelidos usados nas notícias.

Rodar só quando quiser acrescentar lugares (1 consulta por segundo, regra do Nominatim):
    python painel_rotinas\\gerar_lugares.py
Lugares já presentes no JSON não são consultados de novo.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ARQ = Path(__file__).resolve().parent / "lugares_df.json"
UA = {"User-Agent": "DNews-painel-local/1.0 (radar de noticias da Dayse; uso interno)"}
# limites do DF (para descartar resultado de outro estado)
LAT, LON = (-16.06, -15.49), (-48.29, -47.30)

# (nome, tipo, apelidos para achar nas notícias, consulta no Nominatim)
LUGARES = [
    # Regiões administrativas
    ("Plano Piloto", "RA", ["Plano Piloto", "Asa Sul", "Asa Norte", "Esplanada"], "Plano Piloto, Brasília"),
    ("Gama", "RA", ["Gama"], "Gama, Distrito Federal"),
    ("Taguatinga", "RA", ["Taguatinga"], "Taguatinga, Distrito Federal"),
    ("Brazlândia", "RA", ["Brazlândia"], "Brazlândia, Distrito Federal"),
    ("Sobradinho", "RA", ["Sobradinho"], "Sobradinho, Distrito Federal"),
    ("Sobradinho II", "RA", ["Sobradinho II", "Sobradinho 2"], "Sobradinho II, Distrito Federal"),
    ("Planaltina", "RA", ["Planaltina"], "Planaltina, Distrito Federal"),
    ("Paranoá", "RA", ["Paranoá"], "Paranoá, Distrito Federal"),
    ("Núcleo Bandeirante", "RA", ["Núcleo Bandeirante"], "Núcleo Bandeirante, Distrito Federal"),
    ("Ceilândia", "RA", ["Ceilândia"], "Ceilândia, Distrito Federal"),
    ("Guará", "RA", ["Guará", "Guará I", "Guará II", "Guará 2", "Lúcio Costa", "Feira do Guará", "Cave do Guará"], "Guará, Distrito Federal"),
    ("Cruzeiro", "RA", ["Cruzeiro Novo", "Cruzeiro Velho", "RA do Cruzeiro"], "Cruzeiro, Distrito Federal"),
    ("Samambaia", "RA", ["Samambaia"], "Samambaia, Distrito Federal"),
    ("Santa Maria", "RA", ["Santa Maria"], "Santa Maria, Distrito Federal"),
    ("São Sebastião", "RA", ["São Sebastião"], "São Sebastião, Distrito Federal"),
    ("Recanto das Emas", "RA", ["Recanto das Emas"], "Recanto das Emas, Distrito Federal"),
    ("Lago Sul", "RA", ["Lago Sul"], "Lago Sul, Distrito Federal"),
    ("Riacho Fundo", "RA", ["Riacho Fundo I", "Riacho Fundo 1"], "Riacho Fundo, Distrito Federal"),
    ("Riacho Fundo II", "RA", ["Riacho Fundo II", "Riacho Fundo 2"], "Riacho Fundo II, Distrito Federal"),
    ("Lago Norte", "RA", ["Lago Norte"], "Lago Norte, Distrito Federal"),
    ("Candangolândia", "RA", ["Candangolândia"], "Candangolândia, Distrito Federal"),
    ("Águas Claras", "RA", ["Águas Claras"], "Águas Claras, Distrito Federal"),
    ("Varjão", "RA", ["Varjão"], "Varjão, Distrito Federal"),
    ("Park Way", "RA", ["Park Way"], "Park Way, Distrito Federal"),
    ("Estrutural", "RA", ["Estrutural", "SCIA"], "Cidade Estrutural, Distrito Federal"),
    ("Sobradinho/Fercal", "RA", ["Fercal"], "Fercal, Distrito Federal"),
    ("Jardim Botânico", "RA", ["Jardim Botânico"], "Jardim Botânico, Distrito Federal"),
    ("Itapoã", "RA", ["Itapoã"], "Itapoã, Distrito Federal"),
    ("SIA", "RA", ["SIA", "Setor de Indústria e Abastecimento"], "Setor de Indústria e Abastecimento, Brasília"),
    ("Vicente Pires", "RA", ["Vicente Pires"], "Vicente Pires, Distrito Federal"),
    ("Sol Nascente/Pôr do Sol", "RA", ["Sol Nascente", "Pôr do Sol"], "Sol Nascente, Ceilândia, Distrito Federal"),
    ("Arniqueira", "RA", ["Arniqueira", "Arniqueiras"], "Arniqueira, Distrito Federal"),
    ("Sudoeste/Octogonal", "RA", ["Sudoeste", "Octogonal"], "Sudoeste, Brasília"),
    ("Arapoanga", "RA", ["Arapoanga"], "Arapoanga, Planaltina, Distrito Federal"),
    ("Água Quente", "RA", ["Água Quente"], "Água Quente, Distrito Federal"),
    # Hospitais públicos
    ("Hospital de Base (HBDF)", "Hospital", ["Hospital de Base", "HBDF"], "Hospital de Base do Distrito Federal"),
    ("Hospital Regional da Asa Norte (HRAN)", "Hospital", ["HRAN", "Hospital Regional da Asa Norte"], "Hospital Regional da Asa Norte"),
    ("Hospital Regional de Taguatinga (HRT)", "Hospital", ["HRT", "Hospital Regional de Taguatinga"], "Hospital Regional de Taguatinga"),
    ("Hospital Regional de Ceilândia (HRC)", "Hospital", ["HRC", "Hospital Regional de Ceilândia"], "Hospital Regional de Ceilândia"),
    ("Hospital Regional do Gama (HRG)", "Hospital", ["HRG", "Hospital Regional do Gama"], "Hospital Regional do Gama"),
    ("Hospital Regional do Guará (HRGu)", "Hospital", ["HRGu", "Hospital Regional do Guará"], "Hospital Regional do Guará"),
    ("Hospital Materno-Infantil (HMIB)", "Hospital", ["HMIB", "Hospital Materno Infantil", "Hospital Materno-Infantil"], "Hospital Materno Infantil de Brasília"),
    ("Hospital Regional de Sobradinho (HRS)", "Hospital", ["HRS", "Hospital Regional de Sobradinho"], "Hospital Regional de Sobradinho"),
    ("Hospital Regional de Planaltina (HRPl)", "Hospital", ["HRPl", "Hospital Regional de Planaltina"], "Hospital Regional de Planaltina"),
    ("Hospital Regional de Santa Maria (HRSM)", "Hospital", ["HRSM", "Hospital Regional de Santa Maria"], "Hospital Regional de Santa Maria"),
    ("Hospital Regional de Samambaia (HRSam)", "Hospital", ["HRSam", "Hospital Regional de Samambaia"], "Hospital Regional de Samambaia"),
    ("Hospital Regional de Brazlândia (HRBz)", "Hospital", ["HRBz", "Hospital Regional de Brazlândia"], "Hospital Regional de Brazlândia"),
    ("Hospital Regional do Paranoá (HRPa)", "Hospital", ["HRPa", "Hospital Regional do Paranoá"], "Hospital Regional do Paranoá"),
    ("Hospital da Criança de Brasília", "Hospital", ["Hospital da Criança", "HCB"], "Hospital da Criança de Brasília José Alencar"),
    ("Hospital Universitário de Brasília (HUB)", "Hospital", ["HUB", "Hospital Universitário de Brasília"], "Hospital Universitário de Brasília"),
    ("Hospital São Vicente de Paulo (HSVP)", "Hospital", ["HSVP", "Hospital São Vicente de Paulo"], "Hospital São Vicente de Paulo, Taguatinga"),
    ("Hospital Regional Leste", "Hospital", ["Hospital Regional Leste"], "Hospital Regional Leste, Paranoá"),
    # Hospitais privados
    ("Hospital Santa Marta", "Hospital", ["Santa Marta"], "Hospital Santa Marta, Taguatinga"),
    ("Hospital Anchieta", "Hospital", ["Hospital Anchieta"], "Hospital Anchieta, Taguatinga"),
    ("Hospital Santa Lúcia", "Hospital", ["Santa Lúcia"], "Hospital Santa Lúcia, Brasília"),
    ("Hospital Brasília", "Hospital", ["Hospital Brasília"], "Hospital Brasília, Lago Sul"),
    ("Hospital Home", "Hospital", ["Hospital Home"], "Hospital Home, Brasília"),
    ("Hospital Daher", "Hospital", ["Hospital Daher"], "Hospital Daher, Lago Sul"),
    # UPAs
    ("UPA Ceilândia", "UPA", ["UPA de Ceilândia", "UPA Ceilândia", "UPA da Ceilândia"], "UPA Ceilândia"),
    ("UPA Samambaia", "UPA", ["UPA de Samambaia", "UPA Samambaia"], "UPA Samambaia"),
    ("UPA Núcleo Bandeirante", "UPA", ["UPA do Núcleo Bandeirante", "UPA Núcleo Bandeirante"], "UPA Núcleo Bandeirante"),
    ("UPA Recanto das Emas", "UPA", ["UPA do Recanto das Emas", "UPA Recanto"], "UPA Recanto das Emas"),
    ("UPA São Sebastião", "UPA", ["UPA de São Sebastião", "UPA São Sebastião"], "UPA São Sebastião"),
    ("UPA Sobradinho", "UPA", ["UPA de Sobradinho", "UPA Sobradinho"], "UPA Sobradinho"),
    ("UPA Santa Maria", "UPA", ["UPA de Santa Maria", "UPA Santa Maria"], "UPA Santa Maria Distrito Federal"),
    ("UPA Gama", "UPA", ["UPA do Gama", "UPA Gama"], "UPA Gama Distrito Federal"),
    ("UPA Planaltina", "UPA", ["UPA de Planaltina", "UPA Planaltina"], "UPA Planaltina Distrito Federal"),
    ("UPA Paranoá", "UPA", ["UPA do Paranoá", "UPA Paranoá"], "UPA Paranoá"),
    ("UPA Riacho Fundo II", "UPA", ["UPA do Riacho Fundo", "UPA Riacho Fundo"], "UPA Riacho Fundo II"),
    ("UPA Brazlândia", "UPA", ["UPA de Brazlândia", "UPA Brazlândia"], "UPA Brazlândia"),
    ("UPA Vicente Pires", "UPA", ["UPA de Vicente Pires", "UPA Vicente Pires"], "UPA Vicente Pires"),
    ("UPA do Guará (obra)", "UPA", ["UPA do Guará", "UPA Guará"], "QI 23, Guará II, Distrito Federal"),
    # Órgãos
    ("CLDF", "Órgão", ["CLDF", "Câmara Legislativa"], "Câmara Legislativa do Distrito Federal"),
    ("Palácio do Buriti (GDF)", "Órgão", ["Buriti", "Palácio do Buriti"], "Palácio do Buriti"),
    ("Secretaria de Saúde (SES-DF)", "Órgão", ["SES-DF", "Secretaria de Saúde"], "Secretaria de Estado de Saúde do Distrito Federal"),
    ("TCDF", "Órgão", ["TCDF", "Tribunal de Contas do DF"], "Tribunal de Contas do Distrito Federal"),
    ("MPDFT", "Órgão", ["MPDFT", "Ministério Público do DF"], "Ministério Público do Distrito Federal e Territórios"),
    ("Administração Regional do Guará", "Órgão", ["Administração Regional do Guará", "Administração do Guará"], "Administração Regional do Guará"),
]


def nominatim(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q + ", Brasil", "format": "json", "limit": 3, "countrycodes": "br"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        for res in json.loads(r.read()):
            lat, lon = float(res["lat"]), float(res["lon"])
            if LAT[0] <= lat <= LAT[1] and LON[0] <= lon <= LON[1]:
                return round(lat, 5), round(lon, 5)
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    atual = {l["nome"]: l for l in json.loads(ARQ.read_text(encoding="utf-8"))} if ARQ.exists() else {}
    saida, falhas = [], []
    for nome, tipo, apelidos, consulta in LUGARES:
        antigo = atual.get(nome)
        if antigo and antigo.get("lat"):
            saida.append({**antigo, "tipo": tipo, "apelidos": apelidos})
            continue
        try:
            ll = nominatim(consulta)
        except Exception as e:  # noqa: BLE001
            ll, consulta = None, f"{consulta} ({type(e).__name__})"
        time.sleep(1.1)
        if not ll:
            falhas.append(consulta)
        saida.append({"nome": nome, "tipo": tipo, "apelidos": apelidos, "lat": ll[0] if ll else None, "lon": ll[1] if ll else None})
        print(("OK  " if ll else "--  ") + nome, ll or "")
    ARQ.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{sum(1 for s in saida if s['lat'])}/{len(saida)} com coordenadas. Sem resultado: {falhas}")


if __name__ == "__main__":
    main()

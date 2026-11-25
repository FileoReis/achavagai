from urllib.parse import parse_qs, urlsplit

from main import _montar_urls_busca_manual


def test_indeed_cria_uma_url_por_termo():
    urls = _montar_urls_busca_manual("indeed", ["CPD", "Motorista", "Informática"], "Rio de Janeiro")
    assert len(urls) == 3
    assert [termo for termo, _ in urls] == ["CPD", "Motorista", "Informática"]
    primeiro = parse_qs(urlsplit(urls[0][1]).query)
    assert primeiro["q"] == ["CPD"]
    assert primeiro["l"] == ["Rio de Janeiro"]


def test_linkedin_cria_uma_url_por_termo():
    urls = _montar_urls_busca_manual("linkedin", ["CPD", "Motorista"], "Rio de Janeiro")
    assert len(urls) == 2
    ultimo = parse_qs(urlsplit(urls[-1][1]).query)
    assert ultimo["keywords"] == ["Motorista"]
    assert ultimo["location"] == ["Rio de Janeiro"]

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import img2pdf
from PIL import Image
from pypdf import PdfWriter

import pdf_ocr_converter as mod


def _criar_png_bytes(cor=(255, 255, 255), tamanho=(40, 40)) -> bytes:
  buf = BytesIO()
  Image.new("RGB", tamanho, color=cor).save(buf, format="PNG")
  return buf.getvalue()


def _criar_pdf_em_branco_bytes() -> bytes:
  writer = PdfWriter()
  writer.add_blank_page(width=200, height=200)
  buf = BytesIO()
  writer.write(buf)
  return buf.getvalue()


def _criar_pdf_imagem_bytes() -> bytes:
  return img2pdf.convert(_criar_png_bytes())


def test_utilitarios_basicos_e_pisa(tmp_path: Path, monkeypatch):
  html = '<p>Oi</p><img src=""><img src="data:image/png;base64,AA==">'
  limpo = mod._remover_imgs_sem_src(html)
  assert 'src=""' not in limpo
  assert 'src="data:image/png;base64,AA=="' in limpo

  dest = BytesIO()
  res = mod._executar_pisa_sem_aviso_css("<p>Teste</p>", dest)
  assert not res.err
  assert dest.getvalue().startswith(b"%PDF")

  arq = tmp_path / "saida.pdf"
  assert not mod.existe_arquivo(arq)
  assert mod._resolver_destino(arq) == arq

  arq.write_bytes(b"%PDF-1.4")
  assert mod.existe_arquivo(arq)

  respostas = iter(["x", "n"])
  monkeypatch.setattr("builtins.input", lambda _: next(respostas))
  assert mod._resolver_destino(arq) == tmp_path / "saida_v1.pdf"

  monkeypatch.setattr("builtins.input", lambda _: "s")
  assert mod._resolver_destino(arq) == arq


def test_confirmar_e_salvar(tmp_path: Path, monkeypatch):
  alvo = tmp_path / "doc.pdf"
  saida = mod._confirmar_e_salvar({}, None, alvo, confirmar=False)
  assert "pdf_gerado" not in saida

  monkeypatch.setattr("builtins.input", lambda _: "n")
  saida = mod._confirmar_e_salvar({}, b"%PDF", alvo, confirmar=True)
  assert not alvo.exists()

  saida = mod._confirmar_e_salvar({}, b"%PDF", alvo, confirmar=False)
  assert alvo.exists()
  assert saida["pdf_gerado"] == str(alvo)


def test_analise_pdf_e_corrompido(tmp_path: Path):
  pdf_branco = tmp_path / "branco.pdf"
  pdf_branco.write_bytes(_criar_pdf_em_branco_bytes())

  total, pags, texto = mod._analisar_pdf(pdf_branco)
  assert total == 0
  assert texto == ""
  assert pags[0]["status"] == "em_branco"
  assert mod.extrair_texto_pdf(pdf_branco) == ""
  assert mod._chars_pdf(pdf_branco)[0] == 0

  corrompido = tmp_path / "quebrado.pdf"
  corrompido.write_bytes(b"nao-eh-pdf")
  r, dados, dest = mod._preparar_pdf(corrompido, tmp_path / "out.pdf", "por", 30)
  assert r["tipo"] == "pdf_invalido_ou_corrompido"
  assert dados is None
  assert dest is None


def test_imagem_para_pdf_valida_e_invalida(tmp_path: Path, monkeypatch):
  img_ok = tmp_path / "ok.png"
  img_ok.write_bytes(_criar_png_bytes())
  pdf_bytes, err = mod._imagem_para_pdf_bytes(img_ok)
  assert err is None
  assert pdf_bytes is not None and pdf_bytes.startswith(b"%PDF")

  img_inexistente = tmp_path / "nao_existe.webp"
  pdf_none, err_msg = mod._imagem_para_pdf_bytes(img_inexistente)
  assert pdf_none is None
  assert "arquivo_nao_encontrado" in (err_msg or "")

  img_vazia = tmp_path / "vazia.webp"
  img_vazia.write_bytes(b"")
  pdf_none, err_msg = mod._imagem_para_pdf_bytes(img_vazia)
  assert pdf_none is None
  assert "arquivo_vazio" in (err_msg or "")

  img_corrompida = tmp_path / "foto_teste.webp"
  img_corrompida.write_bytes(b"bytes-invalidos-webp")
  monkeypatch.setattr(mod, "_converter_imagem_cli_para_png_memoria", lambda *_: None)
  pdf_none, err_msg = mod._imagem_para_pdf_bytes(img_corrompida)
  assert pdf_none is None
  assert "UnidentifiedImageError" in (err_msg or "")


def test_tabelas_pdfplumber_e_formatacao():
  tabela_falsa = [
      ["id", "nome_cliente", "data"],
      ["1", "Fabio", "2026-11-21"],
  ]
  fake_page = MagicMock()
  fake_page.find_tables.return_value = [object()]
  fake_page.extract_tables.return_value = [tabela_falsa]

  fake_pdf = MagicMock()
  fake_pdf.pages = [fake_page]
  fake_cm = MagicMock()
  fake_cm.__enter__.return_value = fake_pdf
  fake_cm.__exit__.return_value = False

  with patch.object(mod.pdfplumber, "open", return_value=fake_cm):
    amostras = mod._extrair_tabelas_pdf_sample(BytesIO(b"%PDF"))

  assert len(amostras) == 1
  assert amostras[0][0] == ["id", "nome_cliente", "data"]
  linha_fmt = mod._formatar_linha_tabela(amostras[0][1])
  assert linha_fmt == '[1, "Fabio", 2026-11-21]'


def test_word_e_emf_fallback(tmp_path: Path, monkeypatch):
  doc_antigo = tmp_path / "antigo.doc"
  doc_antigo.write_bytes(b"dummy")
  info, dados, alvo = mod._preparar_word_para_pdf(doc_antigo, tmp_path / "out.pdf", 30)
  assert info["motivo"] == "formato_doc_nao_suportado"
  assert dados is None and alvo is None

  monkeypatch.setattr(mod, "_converter_emf_para_png_memoria", lambda _: _criar_png_bytes())
  fake_img = SimpleNamespace(
      content_type="image/x-emf",
      open=lambda: BytesIO(b"emf-bytes"),
  )
  res_img = mod._tratar_imagem_word(fake_img)
  assert isinstance(res_img, dict)
  assert res_img["src"].startswith("data:image/png;base64,")


def test_processar_arquivo_fluxo_completo(tmp_path: Path, monkeypatch):
  inexistente = mod.processar_arquivo(tmp_path / "fantasma.pdf")
  assert inexistente["tipo"] == "inexistente"

  outro = tmp_path / "notas.txt"
  outro.write_text("conteudo", encoding="utf-8")
  res_outro = mod.processar_arquivo(outro)
  assert res_outro["tipo"] == "outro"

  img_scan = tmp_path / "foto_teste.webp"
  img_scan.write_bytes(_criar_png_bytes())
  monkeypatch.setattr("builtins.input", lambda _: "s")
  res_img = mod.processar_arquivo(img_scan)
  assert res_img["tipo"] == "imagem_sem_texto"
  assert (tmp_path / "foto_teste_scan.pdf").exists()
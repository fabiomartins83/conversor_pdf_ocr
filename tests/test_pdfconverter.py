from pathlib import Path

import pdf_ocr_converter as mod


def test_existe_arquivo(tmp_path: Path):
  arq = tmp_path / "exemplo.txt"
  arq.write_text("conteudo", encoding="utf-8")
  assert mod.existe_arquivo(arq) is True
  assert mod.existe_arquivo(tmp_path / "nao_existe.txt") is False


def test_processar_arquivo_inexistente(tmp_path: Path, capsys):
  res = mod.processar_arquivo(tmp_path / "inexistente.pdf")
  assert res["tipo"] == "inexistente"
  assert "não existe" in capsys.readouterr().out

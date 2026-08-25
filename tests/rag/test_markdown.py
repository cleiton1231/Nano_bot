"""Unit tests for nanobot.rag.markdown."""

import unittest
from pathlib import Path
from nanobot.rag.markdown import (
    MarkdownParser,
    ParsedNote,
    Chunk,
    compute_checksum,
    is_sync_conflict_file,
    sanitize_wikilinks,
)


class TestSyncthingConflictFilter(unittest.TestCase):
    def test_sync_conflict_file_detected(self):
        self.assertTrue(is_sync_conflict_file("calculo.sync-conflict-20260824-153000-ABCDEF.md"))
        self.assertTrue(is_sync_conflict_file("notas/calculo.sync-conflict-20260824-153000-ABCDEF.md"))
        self.assertTrue(is_sync_conflict_file(Path("sub/dir/aula.sync-conflict-20260101-120000-XYZ123.md")))

    def test_normal_file_not_flagged(self):
        self.assertFalse(is_sync_conflict_file("calculo.md"))
        self.assertFalse(is_sync_conflict_file("notas/algebra_linear.md"))
        self.assertFalse(is_sync_conflict_file(Path("faculdade/sistemas_operacionais/processos.md")))


class TestWikilinksSanitization(unittest.TestCase):
    def test_sanitize_wikilinks_with_alias(self):
        text = "Estude [[Calculo 1|Cálculo Diferencial]] e [[Algebra Linear|Álgebra]]."
        expected = "Estude Cálculo Diferencial e Álgebra."
        self.assertEqual(sanitize_wikilinks(text), expected)

    def test_sanitize_wikilinks_without_alias(self):
        text = "Veja a nota [[Limites e Derivadas]] para mais detalhes."
        expected = "Veja a nota Limites e Derivadas para mais detalhes."
        self.assertEqual(sanitize_wikilinks(text), expected)

    def test_sanitize_wikilinks_mixed_and_multiline(self):
        text = "Linha 1 [[Nota A|Alias A]]\nLinha 2 [[Nota B]] texto final."
        expected = "Linha 1 Alias A\nLinha 2 Nota B texto final."
        self.assertEqual(sanitize_wikilinks(text), expected)


class TestChecksumComputation(unittest.TestCase):
    def test_sha256_checksum(self):
        content = "conteúdo de teste para cálculo de checksum"
        checksum = compute_checksum(content)
        self.assertEqual(len(checksum), 64)
        self.assertEqual(compute_checksum(content), checksum)
        self.assertNotEqual(compute_checksum(content + " extra"), checksum)


class TestMarkdownParser(unittest.TestCase):
    def setUp(self):
        # Deterministic mock tokenizer (1 word = 1 token for simple testing)
        self.parser = MarkdownParser(
            tokenize_fn=lambda s: len(s.split()),
            chunk_max_tokens=20,
        )

    def test_extract_frontmatter_standard_yaml(self):
        content = """---
title: Teorema Fundamental do Cálculo
date: 2026-08-25
tags: [calculo, analise]
discipline: calculo_1
---
# Teorema Fundamental
Corpo da nota aqui.
"""
        meta, body = self.parser.extract_frontmatter(content)
        self.assertEqual(meta.get("title"), "Teorema Fundamental do Cálculo")
        self.assertEqual(meta.get("discipline"), "calculo_1")
        self.assertEqual(meta.get("tags"), ["calculo", "analise"])
        self.assertIn("# Teorema Fundamental", body)
        self.assertNotIn("---", body)

    def test_extract_frontmatter_missing_or_malformed(self):
        # No frontmatter
        content = "# Apenas Título H1\nCorpo sem metadados."
        meta, body = self.parser.extract_frontmatter(content)
        self.assertEqual(meta, {})
        self.assertEqual(body, content)

        # Malformed YAML
        bad_yaml = "---\ntitle: [unclosed list\n---\n# Título\nCorpo"
        meta, body = self.parser.extract_frontmatter(bad_yaml)
        self.assertEqual(meta, {})
        self.assertIn("# Título", body)

    def test_extract_title_fallback_hierarchy(self):
        # 1. YAML title wins
        self.assertEqual(
            self.parser.extract_title({"title": "Título YAML"}, "# Título H1\nTexto", "arquivo"),
            "Título YAML",
        )
        # 2. First H1 heading if no YAML title
        self.assertEqual(
            self.parser.extract_title({}, "# Título em H1\nTexto", "arquivo"),
            "Título em H1",
        )
        # 3. Filename stem fallback (preserves original casing/acronyms without forced title-casing)
        self.assertEqual(
            self.parser.extract_title({}, "Sem cabeçalho aqui", "limites_e_continuidade"),
            "limites e continuidade",
        )
        self.assertEqual(
            self.parser.extract_title({}, "Sem cabeçalho aqui", "oauth2_api_flow"),
            "oauth2 api flow",
        )

    def test_short_note_produces_single_chunk(self):
        content = """---
title: Nota Curta
---
# Introdução
Este é um texto curto com menos de vinte palavras no total.
"""
        note, chunks = self.parser.parse_note(
            path="calculo/curta.md",
            content=content,
            folder="calculo",
        )
        self.assertEqual(note.title, "Nota Curta")
        self.assertEqual(note.folder, "calculo")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertIn("Este é um texto curto", chunks[0].content)

    def test_long_note_splits_by_headings_with_breadcrumbs(self):
        # Long note exceeding 20 tokens, divided into sections
        content = """# Cálculo 1

## Limites
Definição de limites através de vizinhanças e limites laterais com propriedades operatórias fundamentais.

## Derivadas
Conceito geométrico da reta tangente e taxa de variação instantânea aplicada a funções polinomiais e trigonométricas.
"""
        note, chunks = self.parser.parse_note(
            path="calculo/longa.md",
            content=content,
            folder="calculo",
        )
        self.assertGreaterEqual(len(chunks), 2)
        # Verify headings & breadcrumbs in chunks
        headings = [c.heading for c in chunks if c.heading]
        self.assertTrue(any("Limites" in h for h in headings))
        self.assertTrue(any("Derivadas" in h for h in headings))
        # Ensure chunk content preserves breadcrumb header context
        self.assertTrue(any("[Cálculo 1 > Limites]" in c.content or "Limites" in c.content for c in chunks))

    def test_oversized_single_section_splits_by_paragraphs(self):
        # Section with no subheadings but multiple paragraphs exceeding max_tokens
        p1 = "Parágrafo um com texto curto."
        p2 = "Parágrafo dois continuando a explicação."
        content = f"# Seção Única Gigante\n\n{p1}\n\n{p2}"

        parser = MarkdownParser(
            tokenize_fn=lambda s: len(s.split()),
            chunk_max_tokens=10,  # Small threshold to force paragraph split
        )
        note, chunks = parser.parse_note(
            path="geral/gigante.md",
            content=content,
            folder="geral",
        )
        self.assertGreater(len(chunks), 1)
    def test_code_block_comments_not_treated_as_headings(self):
        content = """# Programação em Python

## Exemplo de Código
Aqui está um código de exemplo:

```python
# Este é um comentário dentro do bloco de código
def calcular_limite(x):
    # Outro comentário interno
    return x ** 2
```

## Conclusão
Fim da explicação técnica.
"""
        note, chunks = self.parser.parse_note(
            path="computacao/python.md",
            content=content,
            folder="computacao",
        )
        headings = [c.heading for c in chunks if c.heading]
        self.assertIn("Exemplo de Código", headings)
        self.assertIn("Conclusão", headings)
        # Verify code comments are NOT in headings list
        self.assertFalse(any("Este é um comentário" in h for h in headings))
        self.assertFalse(any("Outro comentário" in h for h in headings))

    def test_crlf_windows_newlines_handled(self):
        p1 = "Parágrafo um com texto curto."
        p2 = "Parágrafo dois continuando a explicação."
        crlf_content = f"# Seção Windows\r\n\r\n{p1}\r\n\r\n{p2}"

        parser = MarkdownParser(
            tokenize_fn=lambda s: len(s.split()),
            chunk_max_tokens=10,
        )
        note, chunks = parser.parse_note(
            path="windows/crlf.md",
            content=crlf_content,
            folder="windows",
        )
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertNotIn("\r", chunk.content)

    def test_empty_note_returns_no_chunks(self):
        note, chunks = self.parser.parse_note(
            path="geral/vazio.md",
            content="   \n\n   ",
            folder="geral",
        )
        self.assertEqual(chunks, [])

    def test_frontmatter_without_trailing_newline_or_empty(self):
        # Empty frontmatter
        meta_empty, body_empty = self.parser.extract_frontmatter("---\n---\n# Título\nCorpo")
        self.assertEqual(meta_empty, {})
        self.assertIn("# Título", body_empty)
        self.assertNotIn("---", body_empty)

        # Frontmatter without trailing newline
        meta_notrail, body_notrail = self.parser.extract_frontmatter("---\ntitle: Sem Trailing\n---")
        self.assertEqual(meta_notrail.get("title"), "Sem Trailing")
        self.assertEqual(body_notrail, "")

    def test_obsidian_image_embed_sanitized(self):
        text = "Veja a figura ![[grafico_seno.png|300]] para visualizar o comportamento da função."
        sanitized = sanitize_wikilinks(text)
        self.assertNotIn("!300", sanitized)
        self.assertNotIn("![[", sanitized)


if __name__ == "__main__":
    unittest.main()

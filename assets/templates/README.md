# Templates visuais

Template padrao do sistema:

```text
assets/templates/default_event_card.png
```

Esse template e usado quando a Loja ainda nao trouxe/configurou seu proprio padrao visual.
Ele funciona como fallback institucional do Bode Andarilho e nao altera callbacks,
confirmacoes, cancelamentos, links, captions ou botoes inline do Telegram.

## Recomendacao do arquivo base

- formato: PNG
- proporcao vertical
- largura ideal: 1080 px ou mais
- area central livre para texto
- evitar texto fixo no centro da arte

## Como o card padrao e montado

O renderizador `src/render_cards.py` usa o pergaminho como fundo e desenha os dados da sessao em blocos fixos:

1. Topo esquerdo: selo da potencia (`assets/potencias/`) e complemento, quando houver.
2. Topo direito: carimbo do grau (`assets/stamps/`).
3. Centro superior: data, dia da semana e hora, com a hora em destaque visual.
4. Corpo: grau discreto, secao LOJA, secao SESSAO e secao ORDEM DO DIA / OBSERVACOES.
5. Rodape: frase institucional curta.

O texto "Nova Sessao" nao e renderizado no template padrao.
O rito nao aparece no topo; ele aparece somente dentro da secao SESSAO.

## Marca d'agua opcional

Se existir o arquivo abaixo, ele sera aplicado discretamente ao fundo:

```text
assets/branding/bode_andarilho_watermark.png
```

Formato ideal: PNG com fundo transparente, preferencialmente quadrado ou vertical,
entre 800 e 1200 px, em traco/gravura. O renderizador reduz opacidade e tenta
remover fundo claro conectado as bordas para integrar a imagem ao pergaminho.

## Como editar no futuro

Para ajustar apenas a arte de fundo, substitua `default_event_card.png` mantendo
proporcao vertical e area central limpa.

Para ajustar hierarquia, espacamentos, cores, divisores ou posicionamento de selos,
edite somente a funcao de template padrao em `src/render_cards.py`.

Para alterar selos sem mexer no codigo:

- grau: substituir arquivos em `assets/stamps/aprendiz.png`, `companheiro.png`, `mestre.png`
- potencia: substituir arquivos em `assets/potencias/gob.png`, `cmsb.png`, `comab.png`
- marca d'agua: substituir `assets/branding/bode_andarilho_watermark.png`

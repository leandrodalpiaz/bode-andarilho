# Branding visual

Arquivos opcionais de identidade visual usados pelo renderizador de cards.

## Marca d'agua

Arquivo reconhecido automaticamente:

```text
assets/branding/bode_andarilho_watermark.png
```

Uso atual:

- aplicado somente no template padrao do sistema;
- baixa opacidade;
- tom sepia;
- fundo claro removido quando possivel;
- posicionado no centro-direita/terco medio do card;
- nao interfere em botoes, links ou fluxo do Telegram.

Formato recomendado:

- PNG;
- fundo transparente;
- 800x800 a 1200x1200 px;
- desenho em traco/gravura;
- sem texto obrigatorio, para nao competir com os dados da sessao.

## Diploma digital

Templates oficiais:

```text
assets/branding/diploma_vertical_p1.png
assets/branding/diploma_vertical_p2.png
```

Uso atual:

- `diploma_vertical_p1.png` e a capa do diploma;
- `diploma_vertical_p2.png` e o quadro de conquistas;
- o render final sempre sai em 1080x1920 para carrossel vertical do Telegram;
- os dados e conquistas sao desenhados por `src/render_diploma.py`.

## Publicidade do diploma

Asset opcional reconhecido:

```text
assets/branding/sponsor_sindoficios.png
```

Uso atual:

- se o arquivo existir, ele aparece no rodape da pagina 2 do diploma;
- se nao existir, o sistema renderiza a peca de exemplo `Sua imagem aqui`;
- a tela admin `Publicidade/Apoiadores` mostra qual peca esta ativa.

Formato recomendado:

- PNG;
- fundo transparente;
- marca horizontal ou compacta;
- texto curto;
- legivel em largura aproximada de 170 px dentro do diploma.

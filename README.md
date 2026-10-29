# Prospecção B2B — Seguro Garantia

Aplicação em Python que **busca licitações e contratos públicos**, filtra os que
têm relação com **garantia contratual** (Lei 14.133/2021, arts. 96 a 102),
**enriquece os contatos das empresas vencedoras** e gera **um único arquivo
Excel/CSV** pronto para prospecção comercial.

O resultado responde a três perguntas de uma vez:

1. **Quem ganhou** a licitação/contrato (CNPJ e razão social)?
2. **Qual é o dinheiro envolvido** (valor do contrato e valor estimado da garantia)?
3. **Como falar com essa empresa** (sócios, telefones, celular/WhatsApp, e-mail)?

---

## 1. Pré-requisitos

- Python 3.10 ou superior (testado no 3.12).
- Conexão com a internet.

## 2. Instalação

Abra o terminal **dentro da pasta do projeto**:

```bash
cd "seguro-garantia-b2b"
pip install -r requirements.txt
```

> Dica: para não mexer no Python do sistema, crie um ambiente virtual.
> ```bash
> sudo apt install python3.12-venv   # só na primeira vez
> python3 -m venv .venv
> source .venv/bin/activate
> pip install -r requirements.txt
> ```

## 3. Configuração (opcional)

Tudo funciona sem configurar nada, usando valores padrão. Para mudar o
comportamento de forma permanente, copie o arquivo de exemplo:

```bash
cp .env.example .env
```

Depois edite o `.env`. Os parâmetros principais:

| Variável | Padrão | O que faz |
| --- | --- | --- |
| `DIAS_RETROATIVOS` | `30` | Busca eventos dos últimos X dias |
| `PALAVRAS_CHAVE_GARANTIA` | lista | Termos que caracterizam garantia (separados por `\|`) |
| `FILTRO_GARANTIA_ESTRITO` | `false` | `true` = mantém só registros que citam garantia |
| `VALOR_MINIMO` | `0` | Ignora contratos abaixo desse valor (R$) |
| `PERCENTUAL_GARANTIA` | `0.05` | Percentual usado para estimar a garantia (5%) |
| `UFS` | vazio | Ex.: `SP,RJ,MG` (vazio = Brasil inteiro) |
| `DIRETORIO_SAIDA` | `./saida` | Onde a planilha é salva |
| `ENRIQUECER_CNPJ` | `true` | Busca sócios/telefone/e-mail do CNPJ |
| `ENRIQUECER_WEB` | `false` | Busca contatos no Google/site (mais lento) |

Existem muitos outros parâmetros; veja os comentários do `.env.example`.

---

## 4. Como usar — Interface gráfica (mais fácil)

Recomendado para quem não quer lidar com linha de comando:

```bash
streamlit run app.py
```

O navegador abre sozinho. Na barra lateral esquerda você ajusta a janela de
dias, o valor mínimo, as UFs, liga/desliga o enriquecimento, etc. Depois:

1. Clique em **▶ Gerar carteira**.
2. Acompanhe a barra de progresso.
3. Veja a prévia da tabela.
4. Clique em **⬇️ Baixar Excel** (ou CSV).

O arquivo também fica salvo na pasta indicada em *Diretório de saída*.

---

## 5. Como usar — Linha de comando (CLI)

### Primeira execução (recomendado, rápido)

Teste com uma janela pequena antes de rodar o mês inteiro:

```bash
python3 -m seguro_garantia --dias 5 --limite 20 --saida ./saida
```

- `--dias 5` → olha os últimos 5 dias.
- `--limite 20` → para depois de 20 registros (útil para testar).
- No fim, ele imprime onde o arquivo foi salvo.

### Uso do dia a dia

```bash
# Últimos 30 dias, contratos acima de R$ 500 mil, Brasil inteiro
python3 -m seguro_garantia --dias 30 --valor-minimo 500000

# Só São Paulo e Rio de Janeiro
python3 -m seguro_garantia --ufs SP,RJ

# Incluir busca de contatos na internet (mais lento)
python3 -m seguro_garantia --web --web-max 50
```

Ou use o atalho:

```bash
./rodar.sh --dias 30 --valor-minimo 500000
```

### Principais opções

| Opção | Efeito |
| --- | --- |
| `--dias N` | janela de busca em dias |
| `--valor-minimo R$` | ignora contratos abaixo desse valor |
| `--ufs SP,RJ` | filtra por estado |
| `--sem-editais` | não busca editais abertos (só contratos) |
| `--sem-enriquecimento` | não consulta o CNPJ (mais rápido) |
| `--web` | busca e-mail/celular/WhatsApp na internet |
| `--filtro-estrito` | só registros que citam garantia no texto |
| `--ler-pdf` | lê o PDF do edital procurando a cláusula (lento) |
| `--limite N` | para depois de N registros (testes) |
| `--saida PASTA` | pasta onde salvar o arquivo |
| `-v` | mostra log detalhado do que está acontecendo |

Veja todas com:

```bash
python3 -m seguro_garantia --help
```

---

## 6. Onde ficam os arquivos gerados

Na pasta definida em `DIRETORIO_SAIDA` (padrão `./saida`), com data e hora no nome:

```
saida/prospeccao_seguro_garantia_AAAAMMDD_HHMM.xlsx
saida/prospeccao_seguro_garantia_AAAAMMDD_HHMM.csv
```

- O **Excel** tem duas abas: `Prospeccao` (a carteira) e `Parametros` (o que foi usado na busca).
- O **CSV** usa separador `;` e codificação UTF-8 com BOM (abre certo no Excel pt-BR).

Também são criadas pastas de **cache** (`.cache_cnpj/` e `.cache_web/`): elas
guardam as consultas já feitas, então rodar de novo é muito mais rápido.

---

## 7. Entendendo a planilha (as 17 colunas)

| # | Coluna | O que significa |
| --- | --- | --- |
| 1 | `Fonte_Origem` | PNCP, Compras.gov, e-Negócios SP, etc. |
| 2 | `Tipo_Registro` | `Licitação Nova`, `Contrato Homologado` ou `Termo Aditado` |
| 3 | `Data_Publicacao_Homologacao` | Data do evento (DD/MM/AAAA) |
| 4 | `Estado_UF` | UF do órgão |
| 5 | `Cidade_Orgao` | Município do órgão |
| 6 | `Orgao_Licitante` | Prefeitura/Banco/Ministério/Estatal que contratou |
| 7 | `Objeto_Contratado` | Descrição do serviço/obra/engenharia |
| 8 | `Valor_Contrato` | Valor homologado em R$ |
| 9 | `Valor_Garantia_Estimado` | Valor estimado da garantia (padrão 5%) |
| 10 | `Link_Edital_Contrato` | Link para o edital/contrato (clique no Excel) |
| 11 | `CNPJ_Vencedor` | CNPJ da empresa ganhadora |
| 12 | `Razao_Social_Vencedora` | Razão social / nome fantasia |
| 13 | `Socios_Administradores` | Sócios/administradores do QSA (para abordagem) |
| 14 | `Telefone_Receita` | Telefone do cadastro público |
| 15 | `Celular_WhatsApp_Encontrado` | Celular/WhatsApp localizado na busca |
| 16 | `Email_Contato` | E-mails encontrados |
| 17 | `Cidade_Empresa` | Cidade/UF sede da empresa |

**Uso no contato:** cite as colunas 6–7 (`Orgao_Licitante`, `Objeto_Contratado`)
e a data (coluna 3) — é o conjunto que permite o vencedor identificar de qual
edital/contrato estamos falando.

**Prioridade de abordagem:** a planilha já vem ordenada da maior garantia
estimada (coluna 9) para a menor — comece pelas primeiras linhas.

---

## 8. Quanto tempo demora?

O PNCP publica **dezenas de milhares** de contratos por dia e aplica
**rate-limit** (bloqueio temporário) nas consultas. Por isso:

| Cenário | Tempo aproximado |
| --- | --- |
| `--dias 5 --limite 20` (teste) | menos de 1 minuto |
| `--dias 7`, Brasil inteiro | 15–25 min |
| `--dias 30`, Brasil inteiro | mais de 1 hora |

Dicas para acelerar: use `--ufs` (restringe por estado) e janelas menores.
O aplicativo já espera e tenta de novo automaticamente quando o PNCP bloqueia.

---

## 9. Solução de problemas

**"Preciso instalar algo" / `ModuleNotFoundError: No module named 'pandas'`**
→ Rode `pip install -r requirements.txt` (e ative o `.venv`, se criou um).

**Demora muito e o log mostra "HTTP 429"**
→ É o rate-limit do PNCP. É normal; o app espera e continua. Para ir mais
rápido, reduza `--dias` ou filtre por `--ufs SP`.

**Algumas empresas ficam com "Não localizado"**
→ Pode ser que a fonte pública (BrasilAPI) esteja instável no momento. Rode de
novo mais tarde: o cache evita repetir consultas bem-sucedidas. Para um fallback
extra, ligue `USAR_RECEITAWS=true` no `.env`.

**O enriquecimento web não achou contato de algumas empresas**
→ Isso é esperado: é uma busca *best-effort* em fontes abertas. Empresas sem
site público frequentemente não expõem e-mail/WhatsApp. O telefone do cadastro
público (coluna 13) costuma vir na maioria dos casos.

**Quero testar sem esperar muito**
→ Use `--limite 10 --max-paginas 1`.

---

## 10. Aviso de conformidade (LGPD)

Os dados de sócios e contatos vêm de **cadastros públicos** (Receita Federal e
sites das próprias empresas). Use-os apenas para contato comercial B2B,
identifique-se no primeiro contato e não monte listas para disparo em massa. Para
uso em volume, considere bases licenciadas.

---

## 11. Estrutura do projeto

```
seguro-garantia-b2b/
├── app.py                      # interface Streamlit
├── rodar.sh                    # atalho de linha de comando
├── requirements.txt            # dependências
├── .env.example                # modelo de configuração
└── seguro_garantia/
    ├── config.py               # lê .env / parâmetros
    ├── http_client.py          # requisições com retry e rate-limit
    ├── models.py               # estruturas de dados
    ├── filters.py              # filtro de garantia + cálculo
    ├── exporter.py             # gera Excel/CSV (17 colunas)
    ├── pdf_text.py             # lê PDF de edital (opcional)
    ├── pipeline.py             # orquestra tudo
    ├── cli.py                  # linha de comando
    ├── sources/                # fontes (PNCP, Compras.gov.br, e-Negócios SP, bancos/estaduais)
    └── enrich/                 # enriquecimento (CNPJ e web)
```

## 12. Publicar como site (link público)

Para usar a interface de qualquer lugar (celular, outro computador) sem instalar
nada, use o túnel do Cloudflare:

```bash
./publicar.sh                      # abre o app e mostra um link https://....trycloudflare.com
APP_SENHA=minhasenha ./publicar.sh # exige senha (recomendado)
```

- O link aparece no terminal e também fica salvo em `/tmp/seguro_garantia_url.txt`.
- **O link muda** a cada vez que o túnel é reiniciado e **só funciona enquanto
  este computador estiver ligado** e com internet.
- `Ctrl+C` encerra o acesso público (a interface local continua em
  `http://localhost:8501`).
- Para desligar a senha, basta rodar `./publicar.sh` sem `APP_SENHA`.

Para um endereço fixo e sempre disponível seria necessário hospedar o app fora
deste computador (ex.: Streamlit Community Cloud, Render ou um VPS).

---

## 13. Adicionar um novo portal (avançado)

Crie uma subclasse de `FonteBase` em `seguro_garantia/sources/`, implemente
`coletar()` devolvendo `RegistroLicitacao` e registre-a em
`sources/__init__.py` (função `montar_fontes`). Todo o restante (filtro,
enriquecimento e exportação) passa a funcionar para a nova fonte
automaticamente.

### Fontes com suporte a `Fonte_Origem`

| Fonte | Estado |
| --- | --- |
| PNCP (contratos, editais, aditivos) | Implementado |
| Compras.gov.br | Implementado |
| e-Negócios SP (busca por CNPJ) | Implementado |
| Licitações-E (BB), CAIXA, BNDES, Petronect | Estrutura (stub) |
| BEC/SP, ComprasRS, Compras Públicas, BLL Compras | Estrutura (stub) |

Os stubs avisam claramente no log quando habilitados, para não confundir
"sem resultados" com "fonte não implementada".

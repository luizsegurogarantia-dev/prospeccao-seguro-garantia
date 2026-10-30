# Prospecção B2B — Seguro Garantia

Aplicação em Python que **busca licitações e contratos públicos**, filtra os que
têm relação com **garantia contratual** (Lei 14.133/2021, arts. 96 a 102),
**enriquece os contatos das empresas vencedoras** e gera **um único arquivo
Excel/CSV** pronto para prospecção comercial.

O resultado responde a quatro perguntas de uma vez:

1. **Quem ganhou** a licitação/contrato (CNPJ e razão social)?
2. **Qual é o dinheiro envolvido** (valor do contrato e valor estimado da garantia)?
3. **Como falar com essa empresa** (sócios, telefones, celular/WhatsApp, e-mail)?
4. **A empresa está apta e o edital aceita seguro?** (dossiê cadastral, sanções
   CEIS/CNEP e a cláusula de garantia extraída do texto do edital)

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
| `DIAS_RETROATIVOS` | `30` | Janela em dias corridos, incluindo hoje (30 = hoje + 29 anteriores) |
| `DATA_REFERENCIA` | hoje | Data final da janela, em `DD/MM/AAAA` |
| `PALAVRAS_CHAVE_GARANTIA` | lista | Termos que caracterizam garantia (separados por `\|`) |
| `FILTRO_GARANTIA_ESTRITO` | `false` | `true` = mantém só registros que citam garantia |
| `INCLUIR_EDITAIS_SEM_VENCEDOR` | `false` | `true` = inclui editais ainda sem CNPJ vencedor |
| `COLETAR_LINKS_DOCUMENTOS` | `true` | Busca links de edital/ata/resultado/contrato no PNCP |
| `LINKS_MAX_REGISTROS` | `50` | Quantos registros (maiores valores) têm links buscados; `0` = sem limite |
| `VALOR_MINIMO` | `0` | Ignora contratos abaixo desse valor (R$) |
| `PERCENTUAL_GARANTIA` | `0.05` | Percentual usado para estimar a garantia (5%) |
| `UFS` | vazio | Ex.: `SP,RJ,MG` (vazio = Brasil inteiro) |
| `DIRETORIO_SAIDA` | `./saida` | Onde a planilha e o `ultima_execucao.json` são salvos |
| `REGISTRAR_ULTIMA_EXECUCAO` | `true` | Grava o resumo da última execução em JSON |
| `ENRIQUECER_CNPJ` | `true` | Busca sócios/telefone/e-mail do CNPJ |
| `ENRIQUECER_WEB` | `true` | Busca contatos no Google/site (mais lento) |
| `ENRIQUECER_SANCOES` | `true` | Consulta CEIS/CNEP (exige `TRANSPARENCIA_API_KEY`) |
| `TRANSPARENCIA_API_KEY` | vazio | Chave gratuita do Portal da Transparência |
| `LER_ANEXOS_PDF` | `false` | Lê o edital e extrai a cláusula de garantia |
| `LER_PDF_MAX_REGISTROS` | `30` | Quantos contratos (maiores valores) têm PDF lido |

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
3. Use o **Painel de oportunidades** para buscar e filtrar por data, UF, órgão,
   setor, exigência de garantia, prioridade, faixa de valor e score.
4. Ordene por resultado mais recente, maior valor, maior garantia, maior score
   ou prioridade comercial.
5. Baixe o **recorte filtrado** em CSV/Excel ou os **arquivos completos**.
6. Confira a **última execução** (janela, totais, status e falhas parciais).

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
| `--dias N` | janela em dias corridos, incluindo hoje |
| `--data-referencia DD/MM/AAAA` | fixa a data final da janela |
| `--valor-minimo R$` | ignora contratos abaixo desse valor |
| `--ufs SP,RJ` | filtra por estado |
| `--sem-editais` | não busca editais abertos (só contratos) |
| `--incluir-editais-sem-vencedor` | inclui editais ainda sem CNPJ vencedor |
| `--sem-links` | não busca links de edital/ata/resultado/contrato |
| `--links-max N` | limita quantos registros têm links buscados (`0` = sem limite) |
| `--sem-enriquecimento` | não consulta o CNPJ (mais rápido) |
| `--web` | busca e-mail/celular/WhatsApp na internet |
| `--filtro-estrito` | só registros que citam garantia no texto |
| `--ler-pdf` | lê o PDF do edital procurando a cláusula (lento) |
| `--limite N` | para depois de N registros (testes) |
| `--saida PASTA` | pasta onde salvar o arquivo |
| `--sem-ultima-execucao` | não grava o `ultima_execucao.json` |
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
- O **`ultima_execucao.json`** registra data/hora, status (`sucesso` ou `parcial`),
  janela, totais, fontes usadas, falhas e caminhos dos arquivos. Ele é gravado
  de forma atômica e exibido no painel.

Também são criadas pastas de **cache** (`.cache_cnpj/`, `.cache_web/` e `.cache_sancoes/`): elas
guardam as consultas já feitas, então rodar de novo é muito mais rápido.

---

## 7. Entendendo a planilha (as 51 colunas)

### Identificação, datas e valores

| # | Coluna | O que significa |
| --- | --- | --- |
| 1 | `Fonte_Origem` | PNCP, Compras.gov.br, e-Negócios SP, etc. |
| 2 | `Tipo_Registro` | `Licitação Nova`, `Contrato Homologado` ou `Termo Aditado` |
| 3 | `Data_Publicacao_Homologacao` | Data de publicação/homologação (DD/MM/AAAA) |
| 4 | `Data_Resultado` | Data do resultado usada para ordenar e filtrar |
| 5 | `Estado_UF` | UF do órgão |
| 6 | `Cidade_Orgao` | Município do órgão |
| 7 | `Orgao_Licitante` | Prefeitura/Banco/Ministério/Estatal que contratou |
| 8 | `Objeto_Contratado` | Descrição do serviço/obra/engenharia |
| 9 | `Valor_Contrato` | Valor homologado em R$ |
| 10 | `Valor_Garantia_Estimado` | Valor estimado da garantia (padrão 5% ou % do edital) |
| 11 | `Link_Edital_Contrato` | Link principal do processo |
| 12 | `CNPJ_Vencedor` | CNPJ da empresa ganhadora, formatado |
| 13 | `CNPJ_Valido` | `Sim`, `Não` ou `Não informado` (dígitos verificadores) |
| 14 | `Razao_Social_Vencedora` | Razão social / nome fantasia |
| 15 | `Socios_Administradores` | QSA (até 12), com qualificação e data de entrada |
| 16 | `Telefone_Receita` | Telefone institucional do cadastro público |
| 17 | `Celular_WhatsApp_Encontrado` | Celular/WhatsApp localizado na busca |
| 18 | `Email_Contato` | Até 3 e-mails válidos (sintaxe + MX do domínio) |
| 19 | `Cidade_Empresa` | Endereço completo da sede |
| 20 | `Setor_Atividade` | Setor aproximado (CNAE e, na falta, objeto) |

### Dossiê da empresa

| # | Coluna | O que significa |
| --- | --- | --- |
| 21 | `Perfil_Empresa` | Resumo de uma linha: porte, capital, idade, Simples/MEI |
| 22 | `Porte_Empresa` | MEI, Microempresa, EPP ou Demais |
| 23 | `Capital_Social` | Capital social declarado (R$) |
| 24 | `Data_Abertura` | Data de início de atividade |
| 25 | `Idade_Empresa` | Anos de atividade (empresa nova costuma ser recusada) |
| 26 | `Natureza_Juridica` | Define quem assina e quem pode outorgar |
| 27 | `Simples_Nacional` | Sim / Não / Não localizado |
| 28 | `CNAE_Principal` | Ramo principal da empresa |
| 29 | `Sancoes` | `LIMPA`, punições CEIS/CNEP ou `Não verificado` |

### Processo, prazos e vigência

| # | Coluna | O que significa |
| --- | --- | --- |
| 30 | `Numero_Processo` | Processo administrativo (ex.: `PR 123/2026`) |
| 31 | `Numero_Edital_Contrato` | Número do edital ou do contrato |
| 32 | `Data_Assinatura_Contrato` | Data de assinatura, quando publicada |
| 33 | `Prazo_Execucao` | Prazo do texto; sem texto, `N dias (vigência)` como estimativa explícita |
| 34 | `Vigencia_Contratual` | Intervalo `DD/MM/AAAA a DD/MM/AAAA (N dias)` |

### Exigência de garantia

| # | Coluna | O que significa |
| --- | --- | --- |
| 35 | `Garantia_Status` | `Confirmada`, `Provável`, `Não encontrada` ou `Não verificada` |
| 36 | `Garantia_Justificativa` | Por que o status foi atribuído |
| 37 | `Garantia_Evidencias` | Trechos do texto que comprovam a exigência |
| 38 | `Garantia_Percentual_Edital` | Percentual exigido (ex.: `10%`) |
| 39 | `Prazo_Apresentacao_Garantia` | Prazo para apresentar (ex.: `10 dias`) |
| 40 | `Modalidade_Garantia_Aceita` | Seguro garantia, fiança, caução, título |
| 41 | `Vigencia_Garantia` | Vigência exigida (ex.: `12 meses`) |

Regras do status, sem presumir exigência:

- **Confirmada** — o texto lido traz modalidade e percentual/valor, ou menção
  expressa à garantia de execução.
- **Provável** — o texto (ou o objeto) cita garantia/caução, mas faltam
  elementos para confirmar; requer conferência manual.
- **Não encontrada** — o texto foi analisado e não menciona garantia.
- **Não verificada** — não houve leitura do edital/contrato.

As colunas 38–41 ficam vazias quando não houve leitura e recebem
`Não identificado` quando houve leitura sem a cláusula correspondente.

### Links, fontes e qualificação comercial

| # | Coluna | O que significa |
| --- | --- | --- |
| 42 | `Link_Edital` | Link direto do edital |
| 43 | `Link_Resultado` | Link do resultado/homologação/adjudicação |
| 44 | `Link_Contrato` | Link do contrato |
| 45 | `Link_Ata` | Link da ata, quando existir |
| 46 | `Fonte_Dados` | Lista rotulada das fontes/links usados |
| 47 | `Score_Confianca` | 0–100: qualidade e completude dos dados |
| 48 | `Prioridade_Comercial` | `Alta`, `Média` ou `Baixa` |
| 49 | `Pendencias` | Dados ausentes/inconsistências para conferência manual |
| 50 | `Site_Empresa` | Site oficial localizado na busca |
| 51 | `Outros_Emails` | E-mails adicionais (até 10 no total) |

**Uso no contato:** cite `Orgao_Licitante`, `Objeto_Contratado` e
`Data_Resultado` — é o conjunto que permite ao vencedor identificar de qual
edital/contrato estamos falando. Se `Garantia_Percentual_Edital` estiver
preenchida, use o número exato: *"o contrato exige 10% em 10 dias — consigo
cotar hoje"*.

**Prioridade de abordagem:** a planilha já vem ordenada pelo resultado mais
recente (coluna 4) e, no empate, pela maior garantia estimada (coluna 10).
No painel, ordene por prioridade comercial, score, valor ou garantia. Descarte
ou deixe para depois quem estiver com sanção ativa na coluna 29 — a prioridade
cai automaticamente para `Baixa` nesse caso.

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
público (coluna 16) costuma vir na maioria dos casos.

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
├── app.py                      # interface Streamlit (painel pesquisável)
├── rodar.sh                    # atalho de linha de comando
├── requirements.txt            # dependências
├── requirements-dev.txt        # dependências de teste
├── pytest.ini                  # configuração do pytest
├── .env.example                # modelo de configuração
├── tests/                      # testes automatizados
└── seguro_garantia/
    ├── config.py               # lê .env / parâmetros (janela inclusiva)
    ├── validacao.py            # CNPJ, datas e chave de deduplicação
    ├── oportunidade.py         # garantia, score, prioridade e pendências
    ├── execucao.py             # grava/lê ultima_execucao.json
    ├── http_client.py          # requisições com retry e rate-limit
    ├── models.py               # estruturas de dados e mescla de duplicados
    ├── filters.py              # filtro de garantia + cálculo
    ├── exporter.py             # gera Excel/CSV (51 colunas)
    ├── pdf_text.py             # lê PDF de edital (opcional)
    ├── pipeline.py             # orquestra tudo
    ├── cli.py                  # linha de comando
    ├── sources/                # fontes (PNCP, Compras.gov.br, e-Negócios SP, bancos/estaduais)
    └── enrich/                 # enriquecimento (CNPJ, web e sanções)
```

## 12. Publicar como site (link público)

**Link oficial (sempre no ar, sem precisar do computador ligado):**
<https://prospeccao-seguro-garantia.streamlit.app>

Ele roda no Streamlit Community Cloud, a partir do repositório no GitHub. Para
atualizar o site, basta um `git push` (veja `DEPLOY.md`).

### Alternativa local (link temporário)

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

---

## 14. Testes automatizados

A suíte cobre janela de datas inclusiva, validação de CNPJ, extração da
cláusula e do prazo, classificação da garantia, deduplicação/mescla, retries e
rate-limit, falha de fonte e exportação Excel/CSV.

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes usam apenas dados sintéticos e não fazem chamadas de rede. A suíte
roda também no Python 3.14 usado pelo Streamlit Community Cloud.

### Limitações conhecidas

- A leitura da cláusula de garantia depende do PDF/texto disponível; sem
  leitura, o status fica `Não verificada` (nunca é presumido).
- Portais estaduais e de bancos marcados como *stub* ainda não são coletados.
- O enriquecimento web é *best-effort*: empresas sem site público podem ficar
  sem e-mail/WhatsApp.
- A janela do PNCP é aplicada sobre a data de publicação/resultado; eventuais
  divergências de fuso ou atraso de publicação podem exigir nova execução.
- Dados de contato são públicos e devem ser usados apenas para contato
  comercial B2B, conforme a LGPD.

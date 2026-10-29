# Publicar no Streamlit Community Cloud

**App no ar:** https://prospeccao-seguro-garantia.streamlit.app
**Repositório:** https://github.com/luizsegurogarantia-dev/prospeccao-seguro-garantia

Guia rápido para colocar a interface num link fixo (ex.:
`https://prospeccao-seguro-garantia.streamlit.app`), funcionando mesmo com o
computador desligado.

## 1. Criar o repositório no GitHub

1. Acesse <https://github.com/signup> e crie a conta (se ainda não tiver).
2. Confirme o e-mail.
3. Crie um repositório **privado** chamado `prospeccao-seguro-garantia`
   (<https://github.com/new>). Não marque README, .gitignore nem licença.

## 2. Enviar o código

Com o `gh` já autenticado neste computador:

```bash
cd "~/Documentos/Default Project/seguro-garantia-b2b"
git init
git add .
git commit -m "Prospecção Seguro Garantia - versão Streamlit"
gh repo create prospeccao-seguro-garantia --private --source=. --push
```

## 3. Criar o app no Streamlit Cloud

1. Acesse <https://share.streamlit.io> e entre com a conta do GitHub.
2. Autorize o acesso ao repositório privado quando pedir.
3. Clique em **New app** e preencha:
   - **Repository:** `SEU-USUARIO/prospeccao-seguro-garantia`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Em **Advanced settings → Secrets**, cole:

   ```toml
   APP_SENHA = "escolha-uma-senha-forte"
   ```

5. Clique em **Deploy**. Em 2 a 4 minutos o link fica pronto.

## 4. O que esperar

- **O link é permanente** e funciona com o computador desligado.
- A pasta `saida/` e os caches (`.cache_cnpj`, `.cache_web`) são **temporários**:
  somem quando o serviço reinicia. O download do Excel continua funcionando na
  mesma execução.
- Buscas muito longas (Brasil inteiro, 30 dias) podem ser interrompidas pelo
  limite de recursos. Prefira `UFs = SP` e janelas de 7 dias.
- A primeira execução depois de um período parado demora ~1 min (o app "acorda").

## 5. Atualizar o site depois

```bash
git add .
git commit -m "ajuste"
git push
```

O Streamlit Cloud reimplanta sozinho a cada `push` na branch `main`.

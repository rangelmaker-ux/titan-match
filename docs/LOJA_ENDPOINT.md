# Titan Match na Titan Loja

O Titan Match usa o **mesmo sistema de chaves dos outros apps Titan**. Não há endpoint próprio: o produto
`match` está em `TODOS_APPS` da loja (fora do Pacote, como o Titan Editor).

## Licença (plugin → loja) — `src/titan_match/licenca.py`

| Quando | Chamada | Resposta |
|---|---|---|
| Ativar (botão 🔑) | `POST /api/ativar {chave, produto:"match", dispositivo}` | `{ok, valida_ate, atualizacoes, perfil_pendente}`; 403 chave inválida/de outro app; 409 ativa em outro computador |
| A cada 3 dias | `POST /api/licenca {hash: sha256(CHAVE), produto:"match", dispositivo}` | `{ok, valida_ate}`; 403 bloqueada; 409 liberada deste computador |

- `dispositivo` = `match-win-<MachineGuid>` / `match-mac-<IOPlatformUUID>`. O computador guarda só o hash da chave.
- 1 chave = 1 computador. A troca de computador é feita pelo suporte no painel da loja (liberar ativação).
- Licença anual vencida: o plugin continua funcionando, mas sem novas versões depois de vencimento + 7 dias,
  igual ao Titan Color. Sem internet, o plugin funciona por até 14 dias desde a última revalidação.
- A exigência da chave é ligada em `ENFORCE_LICENSE` (hoje `False`). Ligue quando o produto estiver à venda.

## Download do instalador — bucket R2 privado `titan-match-instaladores`

| Objeto | Conteúdo |
|---|---|
| `latest.json` | `{"versao", "windows": {"arquivo", "sha256", "bytes"}}` (depois também `mac`) |
| `windows/Titan-Match-Windows-<versão>.zip` | instalador Windows com o Python embutido |

O fluxo é o mesmo dos outros apps: o cliente recebe o link da sua área por e-mail. A área chama `/api/baixar`, que
confere a chave e redireciona para `/api/r2` (link assinado, válido por 10 minutos). `/api/r2` lê o `latest.json`
e entrega o arquivo do bucket.

Para publicar uma versão nova do instalador, use o wrangler logado na conta:
```
wrangler r2 object put titan-match-instaladores/windows/Titan-Match-Windows-X.Y.Z.zip --file dist/... --remote
wrangler r2 object put titan-match-instaladores/latest.json --file latest.json --remote
```
As atualizações do plugin continuam no GitHub Releases (`Titan-Match-Update.zip`).

## Para começar a vender

1. Supabase (SQL Editor): rodar `supabase/06_titan_match.sql` do repositório `titan-loja`.
2. Stripe: rodar `STRIPE_SECRET_KEY=sk_live_... node tools/criar_match_stripe.js --yes` (R$ 97/ano) e depois o
   `update produtos set stripe_product_id = ...` que o script imprime.
3. Loja: tirar `embreve: true` do Titan Match em `app.js` e publicar (`npm run deploy`).
4. Plugin: `ENFORCE_LICENSE = True`, subir a versão e publicar a Release no GitHub.

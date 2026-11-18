# Titan Loja — endpoint de licença do Titan Match

O plugin já está pronto para falar com este endpoint (`src/titan_match/licenca.py`).
Ele segue o mesmo padrão do Titan Color (`/api/color-pacote`: chave + dispositivo).

## Requisição

`POST https://titan-loja.pages.dev/api/match-licenca`
`Content-Type: application/json; charset=utf-8`

```json
{
  "acao": "ativar",
  "chave": "CHAVE-DO-CLIENTE",
  "dispositivo": "match-win-<MachineGuid>",
  "produto": "titan-match",
  "versao": "0.2.0"
}
```

- `acao`: `"ativar"` (primeira vez, ou depois de trocar de computador) ou `"verificar"` (revalidação automática a cada 3 dias).
- `dispositivo`: `match-win-<MachineGuid>` no Windows e `match-mac-<IOPlatformUUID>` no macOS.

## Resposta de sucesso (HTTP 200)

```json
{ "ok": true, "nome": "Nome do cliente", "expira_em": null }
```

- `expira_em`: `null` para licença vitalícia, ou um timestamp Unix (segundos) para assinatura.

## Resposta de erro (HTTP 4xx)

```json
{ "ok": false, "erro": "Chave inválida." }
```

O texto de `erro` aparece para o cliente. Por isso precisa ser em português e claro, por exemplo:
"Chave inválida.", "Chave revogada.", "Limite de computadores atingido (2).".

## Regras sugeridas na loja

1. A chave precisa pertencer ao produto `titan-match`.
2. Limite de dispositivos por chave (o Titan Color usa um dispositivo por chave): na `ativar`, registrar o
   `dispositivo`; recusar se passar do limite.
3. Na `verificar`, aceitar só se o `dispositivo` já estiver registrado para a chave.
4. Para revogar (reembolso), basta a loja passar a responder `ok: false` na `verificar`. O plugin bloqueia na
   revalidação seguinte.

## Comportamento do plugin

- Sem internet: continua funcionando por até 14 dias desde a última verificação bem-sucedida.
- Ligar a exigência: em `licenca.py`, `ENFORCE_LICENSE = True`. Fazer isso **só depois** que o endpoint estiver
  respondendo, e publicar como uma atualização.

## Download do instalador (R2)

Os instaladores ficam no bucket **privado** `titan-match-instaladores`, que não tem acesso público:

| Objeto | Conteúdo |
|---|---|
| `latest.json` | `{"versao", "windows": {"arquivo", "sha256", "bytes"}}`; depois entra também `mac_arm64` / `mac_x86_64` |
| `windows/Titan-Match-Windows-<versão>.zip` | instalador Windows com o Python embutido |

A loja entrega o arquivo só para quem comprou, igual ao `color-pacote`: uma Pages Function com o binding R2
`TITAN_MATCH` → `titan-match-instaladores`. A function confere a compra e a chave, lê `latest.json` e devolve o
arquivo por stream (`env.TITAN_MATCH.get(arquivo)`), ou então uma URL assinada de curta duração.

Para publicar uma versão nova, use o wrangler logado na conta:
```
wrangler r2 object put titan-match-instaladores/windows/Titan-Match-Windows-X.Y.Z.zip --file dist/... --remote
wrangler r2 object put titan-match-instaladores/latest.json --file latest.json --remote
```
As atualizações do plugin continuam no GitHub Releases (`Titan-Match-Update.zip`, pequeno). O R2 é só para o
instalador completo.

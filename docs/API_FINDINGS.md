# API de scripting do Resolve: o que existe de fato

Conferido em 18/11/2026 nesta máquina: **DaVinci Resolve Studio 21.1.2.10** (Windows 11),
`README.md` (31 ago 2026), `CHANGELOG.md` (22 out 2026) e `DaVinciResolveScript.pyi` em
`C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting`.
Também conferido ao vivo: primeiro só com leitura no projeto do usuário e depois com escrita real
num **projeto de teste** separado ("Titan Match TESTE …", com um still sintético em S-Log3).

## Métodos de `Graph` (lista real devolvida por `dir()`)

`ApplyArriCdlLut, ApplyGradeFromDRX, GetLUT, GetNodeCacheMode, GetNodeColor, GetNodeLabel,
GetNumNodes, GetToolsInNode, ResetAllGrades, SetLUT, SetNodeCacheMode, SetNodeColor,
SetNodeEnabled, SetNodeLabel`

| Pergunta | Resposta | Fonte |
|---|---|---|
| `SetNumNodes` existe? | **Não** | .pyi + `dir()` ao vivo |
| `AddNode` / `InsertNode` / conectar nós? | **Não existe nenhum método que crie ou ligue nós** | .pyi + `dir()` |
| `SetCDL` age em qual nó? | `TimelineItem.SetCDL({'NodeIndex', 'Slope', 'Offset', 'Power', 'Saturation'})`, índice 1-based | .pyi linha 2991, README linha 25 |
| Existe `GetCDL`? | **Não**: não dá para ler o CDL de volta | .pyi |
| `SetLUT` | `Graph.SetLUT(nodeIndex, path)`; o caminho precisa já ter sido descoberto pelo Resolve (`Project.RefreshLUTList`) | .pyi / README |
| Rótulos | `SetNodeLabel` / `SetNodeColor` (novos na 21.1.2) | CHANGELOG 21.1.2 |
| Topologia (série × paralelo) | **Não exposta**: a API não informa as conexões | .pyi |
| `ApplyGradeFromDRX` | **Substitui o grafo inteiro**; o objeto Graph antigo fica inválido | README "Graph information" |
| Versões de cor | `AddVersion`, `LoadVersionByName`, `GetCurrentVersion`, `DeleteVersionByName` | .pyi |
| Exportar frame | `TimelineItem.ExportFrame` e `MediaPoolItem.ExportFrame` (novos na 21.1.2) | CHANGELOG |
| `ExportFrame`: frame com ou sem grade? | **Sem grade nos dois.** No projeto de teste, com o grade visível no viewer, `TimelineItem.ExportFrame`, `Timeline.ExportFrame`, um still exportado em PNG e `TimelineItem.ExportLUT` devolveram a imagem **sem** o grade. Isso continuou igual depois de `SaveProject`. O `TimelineItem` só muda o enquadramento para a resolução da timeline. *(Uma conclusão anterior, "TimelineItem = com grade", estava errada: a diferença medida vinha do enquadramento.)* | teste real |
| `MediaPoolItem.ExportFrame` em still | só aceita `frameOffset` 0 (o still tem 1 frame) | teste real |
| `GetToolsInNode` | devolve `None` tanto para nó vazio novo quanto para alguns nós com OFX (ex.: "To LogC"), então `None` é ambíguo | teste real |
| `SetLUT` | **falha** com LUT em `%APPDATA%\...\Support\LUT` e funciona na pasta mestre `C:\ProgramData\...\Support\LUT` após `RefreshLUTList()`. `GetLUT` devolve o caminho relativo com `\` | teste real |
| `SetCDL` / `SetNodeLabel` / `SetNodeColor` / `SetNodeEnabled` | funcionam. O nó passa a listar `Primary Balance` / `Saturation, Hue & Lum Mix` | teste real |
| `GrabStill` + `ExportStills(..., "drx")` | funciona (gera um .drx de cerca de 36 KB) | teste real |
| `AddVersion` + `LoadVersionByName` + `ApplyGradeFromDRX` | funciona; **os labels do template são preservados**; a versão original continua listada | teste real |

## Consequência para o Titan Match

A API **não consegue criar a árvore de 10 nós em série** nem anexar nós depois do
último nó do usuário. Contorno implementado:

1. **Template de nós rotulados.** `prepare-template` rotula 10 nós vazios que o usuário
   criou em série (Alt+S) num clipe de teste, captura um still e exporta um `.drx`.
2. **Modo "preencher bloco" (padrão).** O usuário anexa o template depois do último nó
   (Gallery > botão direito no still > *Append Node Graph*, um clique). O Titan acha
   os 10 labels em ordem e escreve **só neles**: `SetCDL`, `SetLUT`, `SetNodeLabel`,
   `SetNodeColor`, `SetNodeEnabled`. Depois relê o grafo e confirma que a quantidade de
   nós e os nós fora do bloco não mudaram.
3. **Modo "nova versão local".** `AddVersion` + `LoadVersionByName` + `ApplyGradeFromDRX(template)`
   numa versão nova. A versão original do usuário continua intacta e dá para voltar a ela.
   Esse modo **não** encadeia os nós do usuário (o DRX substitui o grafo dessa versão).

Input e Output CST são **LUTs .cube gerados pelo próprio Titan** a partir das mesmas
funções usadas na análise (o OFX Color Space Transform não é configurável pela API).

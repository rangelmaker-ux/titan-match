# Titan Match: relatório de engenharia, Fase 1 (Windows) MVP v0.1.0

Data: 18/11/2026. Ambiente: Windows 11 Pro, **DaVinci Resolve Studio 21.1.2.10** (confirmado
por `GetProductName()` e `GetVersionString()`), Python 3.12.8, numpy 2.5, Pillow 13, Tkinter 8.6.
PySide6 não está instalado, então a UI foi feita em Tkinter.

## Implementado

- **Árvore de 10 nós, uma responsabilidade por nó**, com labels automáticos `01 - Input CST` …
  `10 - Output CST` e cor por função (`nodes.py`). Cada nó de correção só mexe nos parâmetros
  da sua função (por exemplo, o WB só usa offset, o Gamma só usa power e a Saturação só usa sat).
- **Input/Output CST** como LUTs .cube 33³ gerados pelas mesmas funções da análise (`profiles.py`, `lut.py`).
  Profiles: Sony S-Log3/SG3.Cine, Panasonic V-Log, Canon C-Log3, RED Log3G10/RWG, ARRI LogC3 EI800/AWG3,
  Blackmagic Film Gen5, DJI D-Log/D-Gamut e Rec.709 G2.4. Espaço de trabalho: DWG/DI.
  Saída: Rec.709 G2.4 com ombro suave invertível.
- **Ordem do pipeline garantida**: o footage passa pelo Input CST antes de qualquer estatística, e a
  referência vai ao mesmo espaço pelo inverso exato do Output CST (`engine.analyze`).
- **Estatísticas** (`stats.py`): histograma RGB (trabalho e display), média e desvio Lab por zona tonal
  (percentil de luma 0–25/25–75/75–100 %), hue × croma em 12 setores, CCT aparente (McCamy),
  tint (a* dos médios), slope de contraste p90−p10 e percentis de luma.
- **Matching estatístico plugável** (`matching/base.py`: `Matcher`, `register`, `get_matcher`).
  `StatisticalZoneLabMatcher` calcula cada nó sobre o resultado simulado dos nós anteriores.
  `MatchResult.validate()` **recusa** valores sem origem registrada.
- **Mapeamento com origem de cada número** (`mapping.py`): WB por mínimos quadrados nos eixos temp/tint;
  exposição e contraste por p10/p50/p90; Lift, Gamma e Gain por médias de zona com pivôs; Color Balance
  pelo Δa*/b* Lab (acoplado à saturação num ponto fixo); Saturação por bisseção do croma Lab. Os limites
  de segurança ficam registrados quando atuam.
- **Dry-run obrigatório** (`report.py`, UI e CLI): mostra CDL, LUT, fórmula, medidas e a conferência
  simulada. Antes de qualquer escrita é preciso aprovar numa caixa de confirmação (UI) ou digitar
  `APLICAR` (CLI). Em código, `fill_block`/`apply_as_new_version`/`prepare_template` levantam
  `ApprovalRequired` sem `approved=True`.
- **Proteção do grade do usuário** (`resolve_bridge.py`): escreve só nos 10 nós do bloco Titan
  encontrado por label e ordem. Nós Titan que já têm conteúdo só são sobrescritos com uma
  confirmação extra. Depois da escrita, o grafo é relido e é erro se a contagem de nós ou qualquer
  nó fora do bloco mudar. Também avisa sobre nós do usuário antes ou depois do bloco.
- **Conferência**: simulada (histograma e ΔLab antes/depois) no dry-run. Depois da escrita há releitura de
  labels, LUTs e contagem de nós. A conferência de pixels pela API foi bloqueada (ver Bloqueado, item 2), então
  a UI/CLI pedem conferência visual no viewer.
- LUTs gravados na pasta mestre `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT\Titan Match`
  (a única em que o `SetLUT` funcionou), seguidos de `RefreshLUTList()`.
- UI Tkinter (seletor de referência, dropdown de profile, flag de film emulation, "Gerar Grade",
  preview antes/depois/referência, aplicar, salvar JSON), CLI, lançador do menu Scripts e instalador.

## Testado

| O quê | Como | Resultado |
|---|---|---|
| Suíte completa | `pytest`, sem Resolve | **109 passed** (22 profiles de câmera) |
| Logs adicionados em 18/11 (S-Log2, C-Log, C-Log2, F-Log, F-Log2, N-Log, LogC4, Apple Log, L-Log, Protune) e gamuts (S-Gamut3, Venice, Rec.2020/F-Gamut/N-Gamut, F-Gamut C, AWG4, Protune Native) | comparação com colour-science | passam. O gamut L-Log = Rec.2020 é suposição (a colour-science não tem L-Gamut) |
| Curvas S-Log3, V-Log, C-Log3, LogC3, Log3G10, D-Log, BMD Gen5 e DI; primárias e matrizes dos 8 gamuts; Lab | comparação com colour-science 0.4.7 | passam. **Achou e corrigiu um bug real**: a conversão legal→full indevida no C-Log3 |
| Input CST leva o cinza 18 % ao DI de 0,18 em todos os profiles | sintético | passa |
| Output CST × inverso (round-trip) | 2000 amostras | erro < 1e-6 |
| LUT .cube contra a função direta | interpolação trilinear | erro máximo < 0,01 |
| Cada mapeamento move a zona certa na direção certa | sintético | passa |
| Match ponta a ponta com look conhecido (WB quente + contraste + sat 1,3), 8 profiles | sintético | distância de histograma **0,091 → 0,019** (−79 %); ΔLab dos médios **[−6,0, −16,6, −23,1] → [−3,0, −2,5, +1,6]** |
| Referência igual ao footage | sintético | todos os CDLs ficam perto da identidade |
| Interface plugável | matcher dummy registrado em teste | passa |
| Travas de segurança | Resolve falso: sem aprovação, sem bloco, sobrescrita do bloco, nós do usuário intactos, índices do SetCDL | passa |
| UI | smoke test Tkinter (modo arquivo) | passa |
| **Resolve real, somente leitura** (projeto do usuário) | conexão, `inspect` (22 nós), `MediaPoolItem.ExportFrame`, dry-run, `check_block` | funcionou. Os 22 nós do usuário foram relidos iguais antes e depois. Sem bloco Titan, a escrita fica bloqueada |
| **Resolve real, ESCRITA** (projeto separado "Titan Match TESTE 20261118-020059", still sintético S-Log3) | 10 nós em série criados com Alt+S (controle de tela) → `prepare-template` → `fill_block` → `apply_as_new_version` | **As 40 chamadas retornaram True** (`SetNodeLabel`, `SetNodeColor`, `SetLUT`, `SetCDL`, `SetNodeEnabled`). Os labels e os LUTs relidos conferem e a contagem de nós não mudou (10→10). O `.drx` foi exportado (36 KB). A nova versão foi criada, a "Version 1" foi preservada e **os labels sobreviveram ao `ApplyGradeFromDRX`**. No viewer: nós 01–10 rotulados e coloridos em série, LUT nos nós 01 e 10, 09 desabilitado, imagem graduada com cores coerentes com a simulação (conferência **visual**) |
| Projeto do usuário | `SaveProject` antes da troca; `LoadProject("project")` no fim | restaurado ("project" ativo) |

Três bugs foram encontrados e corrigidos durante o teste real:

1. `SetLUT` falhava com LUTs em `%APPDATA%`. Agora os LUTs vão para a pasta mestre `C:\ProgramData\...\LUT\Titan Match`.
2. O still na Media Pool só tem o frame 0. Agora há um fallback de `frameOffset`.
3. O Resolve devolve `GetToolsInNode()==None` para nó vazio. A regra de "nó vazio" foi corrigida.

## Bloqueado (limitação da API do Resolve 21.1.2)

1. **Criar nós ou anexar depois do último nó**: não existe `AddNode`, `InsertNode` nem `SetNumNodes`. Contorno:
   - o template .drx, anexado manualmente uma vez por clipe (*Append Node Graph*); ou
   - o modo nova versão (testado).

   No teste, os 10 nós iniciais foram criados por controle de tela (Alt+S), não pela API.
2. **Conferir pixels graduados pela API**: `TimelineItem.ExportFrame`, `Timeline.ExportFrame`, still exportado em PNG
   e `TimelineItem.ExportLUT` devolveram a imagem **sem** o grade, mesmo com o grade visível no viewer e depois de
   `SaveProject`. A conferência do histograma final contra a referência só existe **na simulação**. No Resolve, a
   conferência é visual, e a UI/CLI avisam isso.
3. **Topologia série/paralelo**: a API não expõe as conexões. O teste confirmou a série só visualmente.
4. **Color Space Transform OFX, Film Grain e Halation**: OFX não é configurável pela API. Os CSTs viram LUTs e o nó 09
   fica neutro.
5. **Saturação por faixa de luminância**: exige curva Lum vs Sat, que a API não escreve. Só a saturação global é aplicada.
6. **Hue shift de verdade (rotação)**: o CDL não rotaciona hue. É aproximado no eixo a*/b*.
7. **Ler o CDL de volta**: não existe `GetCDL`.

## Não verificado

- **Se a matemática de CDL do Resolve é igual à do simulador** (clamp, saturação com luma Rec.709). Pela tela, o
  resultado parece coerente, mas a comparação numérica foi bloqueada pelo item 2 acima.
- O fluxo *Append Node Graph* (UI) num clipe que já tem nós do usuário seguido de `fill_block`. A lógica foi testada
  só com o Resolve falso.
- A UI e a CLI de ponta a ponta contra o Resolve real. O teste real usou as mesmas funções do adaptador, pelo script
  `tools/live_test.py`.
- Se é preciso estar na página Color para a escrita (o teste foi feito na página Color).
- Se gravar em `C:\ProgramData\...\LUT` funciona em máquinas sem permissão de escrita lá (existe fallback para `%APPDATA%`,
  mas lá o `SetLUT` falha).
- As constantes de câmera contra footage real de cada câmera (conferidas só contra colour-science). O LogC3 é só EI 800.
- A qualidade do match em material real de câmera log.
- O `install_windows.ps1` não foi executado como script; os passos dele foram rodados à mão. O lançador foi
  instalado e **funciona**: o item "Titan Match" aparece em Workspace > Scripts na página Color e abre a janela
  (conferido em 18/11/2026).

## Deixado no sistema pelo teste

- O projeto **"Titan Match TESTE 20261118-020059"** foi **apagado** a pedido do usuário (`DeleteProject` retornou True e ele
  não aparece mais na lista). Junto com ele foram os stills da Gallery do projeto de teste.
- Os LUTs em `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT\Titan Match\` e uma cópia em
  `%APPDATA%\...\Support\LUT\Titan Match\` (esta não é usada).
- O template exportado em `tools/_live/templates/TitanMatch_Template_1.1.1.drx`.

## Atualização 18/11/2026: árvores variáveis e correções da janela

**Implementado e testado no Resolve real (projeto de teste "Titan Match TESTE 20261118-024150"):**
- **Árvore Cinema** com 15 índices: 01 Input CST → NR → 02…08 → SKIN (qualifier de pele) → [GLOW ∥ HALATION ∥ GRAIN] → mixer → 10 Output CST.
  Foi exportada como `templates/TitanMatch_cinema.drx`. Aplicada numa versão nova, deu 52 chamadas sem erro, e o
  qualifier, o NR e os OFX Glow/Halation/Film Grain **sobreviveram** ao `.drx`. Conferido também no viewer.
- **Medido:** o Parallel Mixer **ocupa um índice de nó** (`GetToolsInNode` = `['Parallel Mixer']`). No manifesto ele é a role
  `mixer` (estrutural), que o plugin nunca escreve.
- **Escolha automática da árvore** pela análise (pele, ruído, grão, glow, halation), nós extras ligados ou desligados com
  a medida registrada, **força do match**, **proteção e separação de pele**, **barra de progresso** e **Restaurar original**.

**Bugs encontrados pelo usuário e corrigidos:**
- Um método da janela chamado `_options` sobrescrevia um método interno do Tkinter. Com isso, **todas** as caixas de
  diálogo (confirmar Aplicar, Criar template, erros) quebravam em silêncio, e a impressão era de que nada acontecia.
  Agora há um teste que impede essa colisão.
- Erros da thread de análise não apareciam, porque a variável `e` já não existia quando a janela ia mostrar a
  mensagem. Agora os erros aparecem na janela e ficam no log `%LOCALAPPDATA%\TitanMatch\Logs\titan_match.log`.
- A análise levava cerca de 40 s; agora leva cerca de 5 s (amostra de 60 mil pixels, análise a 640 px e bisseção da
  saturação numa amostra fixa).

**Não verificado / limitações:**
- As intensidades de Glow, Halation, Grain e NR são as do template. A API só liga ou desliga esses nós. No teste
  sintético o Halation padrão ficou forte.
- A chave de pele do template é genérica (Hue 26 ±14, suavização 8, Sat 10–65, Lum 15–90). A simulação usa a máscara
  Lab do Titan, que é uma aproximação.
- Os limiares de NR, grão, glow e halation são heurísticos.
- O painel de ajustes ao vivo ("Node on the Go") ainda não foi feito.

## Atualização 18/11/2026 (2): neblina/fumaça, Aplicar direto, barra de status

- **Nó HAZE** (OFX **Cinematic Haze**, ResolveFX Light, confirmado em `GetEffectsList`) na árvore Cinema, em
  série depois de 08 - Saturação: 01→NR→02…08→HAZE→SKIN→[GLOW∥HALATION∥GRAIN]→mixer→10 (16 índices). `.drx`
  reexportado e aplicado no projeto de teste: 55 chamadas sem erro e o OFX preservado.
- **Medido:** ao inserir um nó, o Resolve **renumera** os nós pela ordem do grafo. O plugin sempre identifica
  os nós pelo **label**. Alt+S num nó com várias saídas cria um ramo novo em vez de inserir em série.
- **Detecção de névoa** (heurística, `features.haze_measure`): dark channel (He et al., 2009) normalizado pela luz
  da névoa, que é o índice de névoa. O modo automático liga se o índice da referência for ≥ 0,18 e a luz da névoa
  estiver entre 0,15 e 0,85, para não confundir com parede ou lâmpada estourada. Com imagens reais: floresta com
  névoa → liga (densidade sugerida ≈ 31 %); cena de terror sem névoa → não liga.
  **Limitação:** imagem lavada ou parede clara podem parecer névoa. Por isso há o controle manual
  **Neblina/fumaça: Auto / Ligada / Desligada**. A intensidade do Cinematic Haze é ajustada no nó, porque a API
  não ajusta parâmetros de OFX.
- **Aplicar sem confirmação** (pedido do usuário): clicar já é a aprovação, e o dry-run continua nos Logs.
  Restaurar continua pedindo confirmação. **Não testado com clique no Resolve** nesta rodada.
- Barra de progresso: roxa trabalhando, verde ao terminar, vermelha em erro (conferido na janela).

## Atualização 18/11/2026 (3): pele

**Implementado e testado (fora do Resolve):**
- **Identificador de pessoas:** detecção de rosto com as cascatas de Haar do OpenCV (`opencv-python-headless<5`).
  A cor da pele é aprendida no centro do rosto e procurada no corpo da pessoa, mais parecida com o rosto do que
  com o fundo e com abertura morfológica. No frame real do C1905 (pessoa na sala): 1 rosto e 5,9 % de pele (rosto
  e braços), com parede e cortina de fora. Sem rosto, usa a faixa fixa de pele em Lab.
- **Pele com ambiência parcial e viva:** o tom alvo mistura X % da cor do ambiente com (1−X) % da pele original;
  controle "Pele no ambiente: 20/35/60 %". O tom fica limitado a ±20° da linha de tom de pele (55° Lab) e o croma
  tem um mínimo natural. O nó SKIN recebe offset (tom) e saturação (vida). Simulação com máscara de borda suave.
- Indicador na janela: "👤 N pessoa(s) — pele protegida".

**Medido no Resolve (projeto de teste) — BLOQUEADO / não resolvido:**
- A chave de pele (Qualifier HSL) **não separa pele** em footage dessaturado. No frame do C1905, o conta-gotas
  mediu saturação da pele de 0–2,5 % depois do Input CST (DWG/DI) e de 0–3,5 % na imagem original (antes do CST).
  Parede e camisa ficam na mesma faixa.
- Nós fora do caminho até a saída **não são processados**: a chave de um ramo lateral não chega ao SKIN, que
  recebe uma chave cheia, ou seja, a correção vai para a tela inteira.
- Ligar a saída de chave de um nó à entrada de chave do SKIN funciona (`GetToolsInNode` mostra "External Key"),
  mas depende de uma chave boa na origem.
- Com isso, o template atual (SKIN KEY logo após o Input CST) fica inerte nesse tipo de footage: o SKIN quase não
  age. O plano e os Logs avisam. A pré-visualização "Depois (simulado)" mostra a pele protegida, o que pode
  divergir do Resolve.
- Achado de UI: o botão de bypass do viewer estava ligado durante parte dos testes, o que mostrava a imagem sem grade.

## Atualização 18/11/2026 (4): pele com um clique — testado no Resolve

- A árvore Cinema voltou a ter a chave **no próprio nó SKIN**: o SKIN KEY separado foi removido e o `.drx`
  reexportado.
- **Aplicar:** o nó SKIN é escrito com a correção calculada, mas fica **desligado** se ainda não tiver chave. Sem
  chave, o Resolve aplicaria a correção na tela inteira (medido: Key = quadro inteiro).
- **Ativar pele** (`ResolveBridge.enable_skin`): liga o SKIN só se `GetToolsInNode` mostrar uma chave
  (Qualifier, Window ou **AI Magic Mask**; "External Key" não conta, porque o rótulo fica mesmo sem ligação).
- **Testado no Resolve, frame real C1905 com referência azul:**
  - conta-gotas do Qualifier no nó SKIN: saturação medida 0–2,9 % e chave = quadro inteiro, ou seja, **não
    funciona** em footage flat;
  - **AI Magic Mask 2, um ponto no rosto**: rosto com pele natural e viva, ambiente azul. **Funciona.**
    A API reporta "AI Magic Mask" e o "Ativar pele" ligou o nó.
- `ExportFrame` agora tenta de novo até 3 vezes ("Failed to render frame" logo após trocar de timeline).
- **Não verificado:** tracking do Magic Mask em clipes de vídeo com movimento (o teste foi num still). Os braços
  só entram com cliques adicionais.

## Atualização 18/11/2026 (5): instaladores, atualização automática, licença e cor da névoa

**Implementado**
- Instalador Windows (`tools/build_windows.ps1` → `dist/Titan-Match-Windows-<v>.zip`) com Python 3.12 embutido.
- Instalador macOS: `tools/build_mac.sh` (Python portátil python-build-standalone com Tkinter, arm64 ou x86_64),
  `installer/mac/Instalar_Titan_Match.command`, lançador `installer/mac/Titan Match.py`, `.gitattributes` com LF.
- Atualização por GitHub Releases (`update.py`, repositório `rangelmaker-ux/titan-match`) e licença da Titan Loja
  (`licenca.py`, `ENFORCE_LICENSE=False` até a loja ter `/api/match-licenca` — ver `docs/LOJA_ENDPOINT.md`).
- Cor automática da névoa: `features.haze_tint` usa a cor da luz atmosférica da referência; quando ela é neutra
  (fumaça branca), puxa para a tonalidade dos médios-altos do grade. Vira um Offset de média zero (só tinge, não
  levanta o preto), proporcional à densidade, com teto de 0,03 por canal, escrito no nó HAZE via SetCDL. Pode ser
  desligada pela opção "cor auto" ao lado de Neblina. Origem registrada no dry-run.

**Testado**: 143 testes (3 novos de cor da névoa); motor de ponta a ponta com névoa azulada → Offset para o azul;
build e instalação silenciosa no Windows; sintaxe dos scripts de Mac (`bash -n`).

**Não verificado**: instalador macOS num Mac real; se o Offset no nó HAZE fica antes ou depois do OFX Cinematic Haze
no processamento do Resolve (tinge a imagem do nó de qualquer forma, mas não a cor interna do efeito, que a API
não ajusta).

**Bloqueado**: publicação no GitHub (precisa do seu login); endpoint da licença na Titan Loja.

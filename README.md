# Titan Match

Color matching por referência para **DaVinci Resolve Studio** (família Titan: Titan Cut,
Titan Sounds, Titan Titles). Você escolhe uma imagem de referência (JPEG/PNG) e o profile
de câmera do material. O Titan Match analisa a referência e gera uma **árvore de 10 nós em
série**, cada um com uma única função e rótulo automático:

```
01 - Input CST → 02 - White Balance → 03 - Exposure & Contraste → 04 - Shadows (Lift)
→ 05 - Midtones (Gamma) → 06 - Highlights (Gain) → 07 - Color Balance → 08 - Saturacao
→ 09 - Look / Film Emulation → 10 - Output CST
```

Fase 1: Windows. Fase 2 (macOS) só começa depois que a Fase 1 for aprovada.

## Câmeras / logs suportados (passo 1 da janela)

| Marca | Log / Gamut |
|---|---|
| Sony | S-Log3/S-Gamut3.Cine · S-Log3/S-Gamut3 · S-Log3/Venice S-Gamut3.Cine · S-Log2/S-Gamut |
| Canon | C-Log3 · C-Log2 · C-Log (Cinema Gamut) · C-Log/BT.709 |
| Panasonic Lumix | V-Log / V-Log L / V-Gamut |
| Fujifilm | F-Log · F-Log2 (F-Gamut) · F-Log2 C (F-Gamut C) |
| Nikon | N-Log / N-Gamut |
| DJI | D-Log / D-Gamut |
| GoPro | Protune Flat / Protune Native |
| Apple | Apple Log / Rec.2020 |
| Leica | L-Log / Rec.2020 (gamut não verificado) |
| Blackmagic | Film Gen 5 / BMD Wide Gamut |
| ARRI | LogC3 (EI 800) / AWG3 · LogC4 / AWG4 |
| RED | Log3G10 / REDWideGamutRGB |
| Outros | Rec.709 Gamma 2.4 (sem log) |

As curvas e os gamuts são conferidos nos testes contra a biblioteca colour-science. O DJI D-Log M não está
incluído porque a fórmula dele não é pública. Use **Pré-visualizar CST** para conferir se o log escolhido está certo
antes de analisar. A última escolha fica salva.

## Como funciona

1. O footage passa pelo **Input CST** (profile → DaVinci Wide Gamut/Intermediate) **antes**
   de qualquer comparação. A referência vai para o mesmo espaço pelo inverso exato do Output CST.
2. Estatísticas de cada imagem: histograma RGB; média e desvio em Lab por zona tonal
   (sombras, médios e altas por percentil de luma); hue × croma; temperatura aparente
   (McCamy); slope de contraste (p90−p10).
3. Matching estatístico (plugável, `titan_match/matching/`). Cada nó é calculado sobre o
   resultado simulado dos nós anteriores e **cada número guarda a fórmula e as medidas de origem**.
4. **Dry-run obrigatório**: os valores aparecem para aprovação e nada é escrito antes.
5. Escrita via API (`SetCDL`/`SetLUT`/`SetNodeLabel`) só no bloco Titan, seguida de releitura do
   grafo e conferência do histograma com o frame graduado real.

> A API do Resolve **não cria nós** (ver [docs/API_FINDINGS.md](docs/API_FINDINGS.md)). Por isso
> o bloco de 10 nós vem de um template que você anexa uma única vez por clipe.

## Instalação

```bash
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

Requisitos: Resolve **Studio**, com *Preferences > System > General > External scripting = Local*,
e Python 3.10 ou superior.

## Uso

1. **Template (uma vez só):** num clipe de teste, crie 10 nós vazios em série (Alt+S) e rode
   `python -m titan_match prepare-template --out templates`. Isso gera
   `templates/TitanMatch_Template*.drx` e um still "Titan Match Template" na Gallery.
2. Em cada clipe: Gallery > botão direito no still > **Append Node Graph** (anexa depois do seu último nó).
3. Workspace > Scripts > Color > **Titan Match** → escolha a referência e o profile → **Gerar Grade**
   → revise o dry-run e o preview → **Aplicar no Resolve…** → confirme.

Linha de comando:

```bash
python -m titan_match analyze --reference ref.jpg --frame frame.png --profile sony_slog3
```

```bash
python -m titan_match resolve-inspect
```

```bash
python -m titan_match resolve-match --reference ref.jpg --profile sony_slog3 --apply fill_block
```

## Testes

```bash
python -m pip install -e .[dev]
```

```bash
python -m pytest -q
```

Os testes rodam sem o Resolve (imagens sintéticas e um Resolve falso). As curvas e os gamuts
são conferidos contra a biblioteca colour-science.

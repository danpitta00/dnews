# D.News

Painel de radar de comunicação do mandato da deputada distrital Dayse Amarilio (PSB-DF). Roda local em `http://localhost:8790`, só com Python (biblioteca padrão), sem dependências além de `pypdf` para ler a Ordem do Dia da CLDF.

## O que tem
- **Radar diário**: notícias e documentos do dia por pilar (Saúde, Guará, Mulheres, Transversais, Política e orçamento), com status da equipe (feito, descartado, encaminhado).
- **Hot Map**: pautas quentes por lugar do DF (Leaflet + `lugares_df.json`).
- **Trilhas**: fios de cobrança e fiscalização acompanhados no Google News.
- **Alertas**: sino e sirene no painel (nada é enviado para fora da máquina).
- **Exportar p/ WhatsApp**: monta a mensagem dos hot points para os grupos das coordenações (só abre o WhatsApp ou copia o texto; quem envia é a pessoa).
- **Agenda legislativa**: CLDF (Ordem do Dia em PDF, agenda do site, API do PLe), Câmara (dados abertos) e Senado (plenário e comissões), filtrada pelas pautas de `agenda_config.json`, em formato de calendário semanal.

## Arquivos
| Arquivo | Papel |
|---|---|
| `server.py` | servidor HTTP e API (`/api/dias`, `/api/agenda`, ...) |
| `static/` | interface (index.html, app.js, app.css) |
| `coletor.py` + `fontes.json` | coleta de notícias (Google News, portais do DF, YouTube) |
| `varredura.py` | varredura de hora em hora: coleta, alertas e trilhas |
| `alertas.py` + `alertas.json` | fila de alertas do painel |
| `trilhas.py` + `trilhas.json` | trilhas de notícia |
| `hotmap.py`, `gerar_lugares.py`, `lugares_df.json` | Hot Map |
| `agenda.py` + `agenda_config.json` | radar da agenda legislativa (palavras-chave editáveis) |
| `tarefas_agendadas/` | cópia dos prompts das rotinas agendadas do Claude que alimentam o painel |

## Como rodar
O código espera os dados em `..\rotinas\` (pasta irmã, fora do repositório).

```bat
INICIAR_DNEWS.bat
```

Agenda legislativa manual: `python -I agenda.py --rodada manha` (ou `tarde`).

## Regras
Somente fontes públicas e somente leitura. Nenhuma credencial fica no código.

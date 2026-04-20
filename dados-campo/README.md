# Dados de Campo — SPARTA AGENTE IA

Pasta sincronizada automaticamente pelo cliente Nextcloud.

Os arquivos `sparta_dados_*.zip` são gerados pelo botão **"Exportar p/ Dev"**
dentro do painel de Backup da aplicação instalada em campo.

## Conteúdo dos ZIPs

| Arquivo | Descrição |
|---|---|
| `analises.json` | Todas as análises da IA (alertas, riscos, confiança) |
| `feedbacks.json` | Feedbacks do operador sobre as análises |
| `exemplos_fewshot.json` | Exemplos promovidos para treinamento few-shot |
| `perguntas_ia.json` | Perguntas geradas automaticamente e respostas |
| `export_meta.json` | Metadados: data, modo (incremental/completo), contagens |

## Modos de exportação

- **Incremental** — somente registros novos desde o último envio (padrão)
- **Completo** — todo o banco de dados (use para primeira importação)

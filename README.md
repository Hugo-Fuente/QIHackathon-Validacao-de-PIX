# Motor Antifraude Pix

**Integrantes:** Hugo Gomes · Leandro Apolinário Leite · Mateus Carósio  
**Data:** 17/10/2026  
**Versão das regras:** 4

## Como o motor de decisão funciona

O motor recebe um pedido de Pix, compara com o histórico local do pagador, do destinatário e do dispositivo e devolve a decisão (`approved`, `two_factor_required` ou `rejected`) antes de o dinheiro sair, em poucos segundos e sem consulta externa. Cada regra é uma função pura: recebe o evento e o histórico e devolve pontos e o motivo observado. O motor soma os pontos, aplica tetos por família e mapeia o total em um status. Cada regra acionada fica gravada para auditoria.

Passo a passo de um `POST /pix/transaction`:

1. Valida e normaliza o evento (documentos só com dígitos, datas em UTC) e calcula o `payload_hash`.
2. Abre uma transação PostgreSQL e trava o `id`, o pagador e a conta destino com `pg_advisory_xact_lock`.
3. Se o `id` já existe: mesmo hash devolve a análise gravada (`200`); hash diferente devolve `409`.
4. Carrega o histórico local (janelas relativas à `transaction_date` do evento) e junta o `context` do EPP, quando houver.
5. Executa as regras em ordem fixa, aplica os tetos, soma e define o `status`.
6. Grava evento, análise e regras acionadas na mesma transação e devolve `201`.

Há dois conjuntos de regras:

- **Núcleo Pix (R1–R12):** sempre avaliado, para qualquer pedido de Pix.
- **Contexto EPP (R13–R27):** só quando o chamador, a conta compartilhada de EPP, envia o bloco opcional `context` (sócio autor, saldo livre, limites, mudanças de controle). Nesse caso, algumas regras do núcleo são ajustadas ou substituídas. Sem `context`, valem exatamente as regras do núcleo.

## Regras

Os parâmetros são pontos de partida, calibrados com os cenários de teste. Cada linha explica o porquê da regra e de cada número escolhido.

### Núcleo Pix (R1–R12)

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **R1 — Limite** | O valor do Pix é alto. | `amount` ≥ R$ 5.000. **+2** | Valor alto aumenta a exposição, mas não prova fraude: com 2 pontos, sozinho leva só a 2FA. R$ 5.000 é um piso inicial acima do Pix comum de uso alto (aluguel, parcela). |
| **R2 — Velocity** | Rajada de Pix do mesmo pagador. | ≥ 5 Pix em 60 s, contando o atual e qualquer status. **+2** | Uma pessoa raramente faz 5 Pix em um minuto; um script faz. Conta qualquer status porque as tentativas rejeitadas são justamente o sinal da rajada. |
| **R3 — Montante acumulado** | Valor fatiado para escapar do limite individual. | Soma do pagador em 10 min ≥ R$ 10.000, com ≥ 2 Pix na janela. **+2** | R$ 10.000 é o dobro do piso do R1: quem fatia precisa ultrapassar bastante o limite individual. Exigir 2 Pix evita contar duas vezes um único Pix grande, que o R1 já cobre. 10 min é curto o bastante para ser uma sequência única. |
| **R4 — Desvio de perfil** | O valor é incompatível com o padrão do pagador. | `amount` ≥ 5× a mediana dos últimos 20 Pix não rejeitados; histórico ≥ 5 Pix; `amount` ≥ R$ 500. **+2** | A mediana resiste a valores atípicos (a média seria puxada por um Pix grande antigo). 20 Pix dão um perfil recente; 5× evita a oscilação normal; o piso de R$ 500 evita disparar em valores pequenos; o histórico mínimo evita inventar perfil de cliente novo. |
| **R5 — Contraparte nova** | O pagador nunca pagou essa conta destino. | Nenhum Pix anterior para a conta; histórico ≥ 3 Pix; `amount` ≥ R$ 1.000. **+1** | Destinatário novo é contexto, não motivo isolado (o aluguel do novo locador é legítimo). O histórico mínimo impede que o primeiro Pix de todo cliente pontue; o piso evita ruído em valores baixos. |
| **R6 — Destino recém-aberto** | A conta destino foi aberta há pouco. | Conta destino com ≤ 30 dias na `transaction_date` (tempo decorrido) e `amount` ≥ R$ 1.000. Se o R8 disparar, vale a soma da janela dele. Sem `opening_date` do destino, não pontua. **+2** | Contas recentes concentram risco de conta de passagem. 30 dias evita a fronteira apertada de 7 dias. O piso de R$ 1.000 é o mesmo teto por Pix do R8; por isso, quando há fracionamento, o R6 olha a soma e não cada Pix. |
| **R7 — Dispositivo novo** | O pagador usa um aparelho que nunca usou. | `device_id` fora dos últimos 20 Pix não rejeitados do pagador; histórico ≥ 3 Pix; `amount` ≥ R$ 500. **+2** | Trocar de aparelho é legítimo, por isso só pontua com perfil existente (3 Pix bastam para haver um aparelho habitual) e valor relevante. 20 Pix é a mesma janela do R4. |
| **R8 — Fracionamento** | Valor dividido em vários Pix pequenos para a mesma conta. | ≥ 3 Pix do pagador para a mesma conta destino em 5 min, cada um < R$ 1.000, com soma ≥ R$ 2.000. **+2** | Pega quem fica abaixo do piso de R$ 1.000 do R5 e do R6. Três Pix e soma de R$ 2.000 diferenciam fracionamento de dois pagamentos legítimos seguidos. |
| **R9 — Destino concentrador** | A conta destino recebe de muitos pagadores em pouco tempo. | Conta destino recebeu de ≥ 5 pagadores distintos em 60 min, soma ≥ R$ 10.000, contando o Pix atual. Não vale para destinatário CNPJ com conta aberta há > 30 dias. **+3** | Padrão de conta de passagem. 5 pagadores distintos em uma hora é incomum fora do comércio; o piso de R$ 10.000 evita pontuar vaquinhas pequenas. Vale 3 porque envolve várias vítimas, mas ainda leva só a 2FA se estiver sozinha. A exceção protege comerciantes legítimos. |
| **R10 — Pagador recente** | A conta pagadora é nova. | Conta pagadora com ≤ 30 dias e `amount` ≥ R$ 2.000. **+1** | A idade da conta é um sinal complementar, nunca decisivo. 30 dias acompanha o R6; o piso é maior (R$ 2.000) porque conta nova sozinha não é suspeita. |
| **R11 — Deslocamento impossível** | Dois Pix do mesmo pagador em lugares incompatíveis. | Geolocalização nos dois Pix; anterior há ≤ 60 min; distância ≥ 50 km; velocidade implícita > 900 km/h. **+3** | Sugere sessão usada de outro lugar. 900 km/h é a ordem de um voo comercial; 50 km filtra ruído de GPS; 60 min mantém a comparação em Pix consecutivos. Sem geolocalização, não pontua. |
| **R12 — Dispositivo compartilhado** | Um mesmo aparelho serve a várias titularidades. | Mesmo `device_id` usado por ≥ 3 documentos de pagadores distintos em 24 h. **+2** | Sugere fazenda de contas. 3 documentos deixa de fora um aparelho dividido por duas pessoas (casal, família); 24 h cobre o uso coordenado de um dia. |

### Ajustes do núcleo quando há `context` (EPP)

| Regra | No EPP | Por quê |
|---|---|---|
| **R1** | **Não avalia.** | O limite do sócio e a regra de aprovação já controlam o valor, e pagar fornecedor acima de R$ 5.000 é rotina de empresa. R4, R13 e R20 cobrem o desvio. |
| **R2, R3, R5** | Iguais; pedido `scheduled` não pontua. | A folha em lote é uma rajada legítima, já aprovada; fornecedor novo é rotina (o R23 trata o caso da responsabilidade). |
| **R4** | **Adaptada:** mediana e histórico mínimo por `responsibility_id` do pedido, quando houver. | Folha e despesa pequena não dividem a mesma mediana. |
| **R6, R8** | Iguais. | Conta de passagem e fracionamento são risco para qualquer pagador; fugir do limite do sócio também é fracionar. |
| **R7** | **Não avalia** (vale o R17). | Conta compartilhada tem vários sócios, cada um com seus aparelhos; o histórico por conta geraria falso positivo. |
| **R9** | **Não avalia** (vale o R26). | Os "pagadores distintos" do EPP são empresas; o R26 é a mesma regra com janela de 24 h. |
| **R10** | **Não avalia** (vale o R24). | A idade da conta pagadora é a ativação, e o R24 já a mede. |
| **R11** | **Não avalia** (vale o R18). | Dois sócios em cidades diferentes são normais; só faz sentido por autor. |
| **R12** | **Adaptada:** ≥ 3 `author_id` distintos, de empresas diferentes, em 24 h. | Sócios da mesma empresa no computador do escritório, ou um sócio com várias empresas, não são fazenda de aparelhos. |

### Contexto EPP (R13–R27)

O "autor" é o sócio que criou o pedido; "recorrente" é a contraparte já paga ≥ 3 vezes pela empresa.

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **R13 — Valor colado no limite** | O autor testa o controle repetindo valores logo abaixo dele. | ≥ 3 pedidos do autor em 24 h, cada um entre 90% e 99,9% do menor valor entre o limite do autor e o gatilho de aprovação; não conta recorrente. **+2** | Quem testa o controle repete valores logo abaixo dele; 3 repetições separam teste de coincidência; mensalidade fixa não é teste. |
| **R14 — Recriação após recusa** | O autor refaz um pedido que outro sócio recusou. | Mesma contraparte; valor entre 80% e 120% do recusado; recusa por outro sócio em ≤ 24 h; cancelamento pelo autor não conta. **+2** | A recusa é um sinal de controle interno que o Pix de varejo não tem; a faixa de ±20% pega o valor ajustado para tentar de novo. |
| **R15 — Aprovação disfarçada** | O voto não vem de uma pessoa distinta do autor. | Evento `vote`: mesmo `device_id` do autor do pedido, ou mesmo IP e voto em < 10 s da criação. **+3** | O quórum exige pessoas distintas, e o EPP só barra o autor votando em si. IP sozinho é fraco (mesmo escritório); por isso exige o voto quase imediato. |
| **R16 — Afrouxamento de controle seguido de uso** | Controles são afrouxados pouco antes de o pedido sair. | Em ≤ 24 h depois de elevar limite, criar permissão, afrouxar regra de aprovação ou definir substituto, o pedido só passa por causa disso; ignora empresa com < 7 dias de conta. **+3** | Mexer nos controles pouco antes de usar é o padrão de abuso de um sistema de controles configuráveis; a empresa nova ainda está configurando tudo. |
| **R17 — Dispositivo novo do sócio** | O R7 aplicado ao histórico do autor. | `device_id` fora dos últimos 20 pedidos não rejeitados do autor; histórico ≥ 3; valor ≥ R$ 500. **+2** | Numa conta compartilhada, cada sócio tem seus aparelhos. Parâmetros iguais aos do R7. |
| **R18 — Deslocamento e IP do sócio** | O R11 por autor, com fallback por IP. | Janela ≤ 12 h; sem geolocalização, país do IP (base local) diferente do último IP do autor. **+3** | Sessão usada de outro lugar; a janela maior que a do R11 cobre voos longos. |
| **R19 — Horário atípico** | Pedido fora do horário habitual do autor. | Pedido imediato criado entre 0h e 5h (fuso do Brasil), valor ≥ R$ 1.000, autor com ≥ 10 operações e nenhuma nesse horário. **+1** | Usa a hora de criação, nunca a da execução, para não punir pagamento agendado; as 10 operações garantem que há hábito para comparar. |
| **R20 — Esvaziamento** | Saída que drena o saldo livre. | Saída paga com saldo livre de valor ≥ 70% do saldo livre e ≥ R$ 5.000; pagamento coberto por reserva de responsabilidade não conta. **+2** | Folha e imposto saem de reserva por desenho; saldo livre drenado é o sinal. O piso evita pontuar empresas com saldo pequeno. |
| **R21 — Liberação de reserva seguida de saída** | O dinheiro reservado é liberado e sai logo depois. | Liberação ou transferência entre reservas e, em ≤ 30 min, saída do autor ≥ 80% do liberado para contraparte nova. **+3** | Tira da empresa o dinheiro de impostos ou folha; a janela curta liga a saída à liberação. |
| **R22 — Destino é sócio** | O dinheiro vai para o CPF de um sócio. | Contraparte com o CPF de um sócio, valor ≥ R$ 2.000; não vale para recorrente com valor ±20% (pró-labore). **+1** | O dinheiro é da empresa, não dos sócios; isolada pesa pouco e soma com R13, R15 ou R20. |
| **R23 — Contraparte nova para a responsabilidade** | Responsabilidade previsível paga um destino fora do padrão. | Responsabilidade com ≥ 5 pagamentos e ≤ 3 contrapartes em 90 dias recebe pedido de contraparte nunca paga por ela, valor ≥ R$ 1.000. **+1** | Impostos e folha pagam sempre os mesmos destinos. Não soma com o R5: o mesmo fato não conta duas vezes. |
| **R24 — Conta recém-ativada com saída grande** | Conta nova movimenta muito. | Ativada há ≤ 30 dias: saída externa ≥ R$ 5.000 vale 1; ≥ R$ 20.000 vale 2. **+1 ou +2** | Usa a ativação, não o cadastro, pois a conta só movimenta depois da aprovação do back-office; os dois degraus pesam mais o valor maior. |
| **R25 — Passagem entrada → saída** | Dinheiro entra e sai quase de imediato. | Entradas externas ≥ R$ 10.000 em 24 h e saída ≥ 80% delas em ≤ 2 h para contraparte nova, em empresa ativa há ≤ 90 dias ou só com pagadores novos. **+3** | Conta de passagem. É a de maior risco de falso positivo: calibrar primeiro. |
| **R26 — Destinatário em rede** | O mesmo destinatário recebe de várias empresas. | Mesmo documento de contraparte com pedidos de ≥ 4 empresas em 24 h, soma ≥ R$ 10.000, contando o atual; não vale se for recorrente para a empresa atual. **+3** | Só a plataforma enxerga várias empresas. Revisar a base legal (LGPD) e consultar por hash do documento. |
| **R27 — Sócio de muitas empresas novas** | Um CPF abre muitas empresas em pouco tempo. | Mesmo CPF sócio de ≥ 3 empresas cadastradas em 30 dias. **0** | Apenas alerta ao back-office na aprovação de `EM_APROVACAO`; não altera o status. |

## Como as regras viram decisão

**Ordem.** As regras aplicáveis são executadas em ordem fixa (R1 a R27), sem interromper na primeira que dispara. A ordem só deixa estável a lista de motivos. Cada regra acionada gera um `RULE_HIT` com os pontos antes do teto.

**Tetos por família.** O mesmo ato não deve contar várias vezes:

- Valor: R1 + R3 + R4 somam no máximo **3**.
- Controles internos (EPP): R13 + R14 + R16 somam no máximo **3**.
- Sessão do sócio (EPP): R17 + R18 + R19 somam no máximo **4**.

**Faixas.** O `risk_score` é a soma depois dos tetos:

| Pontos | Status |
|---|---|
| 0–1 | `approved` |
| 2–4 | `two_factor_required` |
| ≥ 5 | `rejected` |

**Quando pede 2FA.** Com 2 a 4 pontos há dúvida, mas não risco claro: o cliente confirma que é ele mesmo e a transação segue. Um único sinal moderado (valor alto, destino recém-aberto, destino concentrador, dispositivo novo) leva a 2FA, nunca a `rejected`. Como valor alto soma no máximo 3, reprovar exige pelo menos 2 pontos vindos de outros sinais. Sinais de sessão do sócio, sozinhos, também nunca reprovam.

**Exceções e histórico.**

- Se o documento do pagador for igual ao do destinatário, R5, R6 e R9 não pontuam.
- Pedido executado pelo agendador (`origin` = `scheduled`) não pontua R2, R3, R5 nem R17 a R19: o lote da folha não deve ser rejeitado por rajada e contraparte nova, e o aparelho de quem agendou não existe na execução.
- O histórico de confiança (R4, R5, R7, R17) exclui apenas Pix `rejected`. O motor não recebe o resultado do 2FA, e contar só os `approved` faria o cliente do aluguel cair em 2FA todo mês.
- O histórico de rajada e concentração (R2, R3, R8, R9, R11, R12) considera qualquer status, porque tentativas rejeitadas também revelam o padrão.
- No EPP, `two_factor_required` pode virar segundo fator do autor ou aprovação adicional de outro sócio, e `rejected` em um voto significa que o voto não conta. Quem aplica a decisão é o chamador.

**Exemplos.**

- Cliente com mediana de R$ 200 que paga R$ 6.000 pela primeira vez a um locador, no aparelho de sempre: R1 (2) + R4 (2), limitados a 3 pela família de valor, mais R5 (1) = 4. Recebe 2FA.
- Sessão sequestrada de um sócio, com aparelho nunca visto (R17, 2), às 2h10 (R19, 1) e saída de 87% do saldo livre (R20, 2): 5 pontos. É rejeitada.
- Pix do payload de exemplo do desafio (R$ 1.500, conta destino aberta 7 dias antes, pagador sem histórico): só o R6 dispara, 2 pontos, `two_factor_required`.

## API

### `POST /pix/transaction`

Valida, analisa e registra um evento Pix, retornando a decisão. É idempotente pelo `id` do evento.

**Campos de entrada:**

- `id`: identificador único do evento (o Pix ou, no EPP, o voto).
- `amount`: valor em centavos, inteiro positivo.
- `transaction_date`: data e hora com fuso.
- `source_account`: agência, número, data de abertura e `owner.document_number` (CPF ou CNPJ) do pagador.
- `destination_account`: participante (ISPB), agência, número, data de abertura e `owner.document_number` do destinatário. No EPP, a data de abertura é opcional.
- `source`: `device_id`, `channel`, `ip` e `geolocation` (latitude e longitude, opcional).
- `context` (opcional, enviado pelo EPP): `event` (`request`, `vote` ou `execution`), `origin` (`immediate` ou `scheduled`), `company_id`, `author_id`, `responsibility_id` e os fatos que só o EPP conhece (saldo livre, limites, ativação da conta, mudanças de controle, liberação de reserva, documentos dos sócios).

**Resposta** (`key`, `status`, `metadata`): `metadata` traz `risk_score`, `reasons` (as regras acionadas com pontos e valores observados) e `rules_version`.

**Status:**

- `201`: análise criada.
- `200`: mesmo `id` e mesmo payload; devolve a análise já gravada, sem reprocessar.
- `400`: corpo ilegível ou JSON malformado.
- `409`: mesmo `id` enviado com payload diferente.
- `422`: campo ausente ou de tipo errado, `amount` não inteiro ou ≤ 0, data sem fuso, documento sem 11 ou 14 dígitos, latitude ou longitude fora da faixa, `context` com `event` inválido ou sem `author_id`.
- `500`: falha interna; tudo é revertido e o reenvio é seguro.

### `GET /pix/transaction/{id}`

Consulta a análise registrada para o `id` do evento (não o `key`). Somente leitura.

- `200`: `key`, `status` e `metadata` da análise.
- `404`: não existe análise para o `id` informado.

## Banco de dados

O sistema usa PostgreSQL e mantém o evento, a análise e as regras acionadas.

### `PIX_TRANSACTION`

Armazena o evento recebido: `id` (chave primária e idempotência), `payload_hash`, valor em centavos, data da transação em UTC, dados normalizados do pagador e do destinatário (documento só com dígitos, conta, data de abertura), `destination_account_key` (participante, agência e conta), dispositivo, canal, IP, geolocalização opcional, campos do EPP (`event_type`, `origin`, `company_id`, `author_id`, `responsibility_id`), o `context` em `jsonb` para reproduzir a decisão, o payload original e a data de recebimento. Índices por documento do pagador, conta destino, documento do destinatário, dispositivo e autor, sempre com `transaction_date`, apoiam as consultas de histórico.

### `FRAUD_ANALYSIS`

Uma única análise por evento: `key` (UUID), `transaction_id` (referência única ao evento), `status`, `risk_score`, `rules_version` e `analyzed_at`.

### `RULE_HIT`

Cada regra acionada: identificador, chave da análise, código da regra (R1–R27), pontos antes do teto e detalhe dos valores observados e parâmetros usados.

Relacionamentos: cada `PIX_TRANSACTION` recebe uma `FRAUD_ANALYSIS`; uma análise tem zero ou várias entradas em `RULE_HIT`.

## Idempotência e concorrência

O motor calcula `payload_hash` (SHA-256) sobre o payload normalizado. O mesmo `id` com o mesmo hash retorna a decisão existente; o mesmo `id` com hash diferente retorna `409`.

Durante a análise, uma transação PostgreSQL usa `pg_advisory_xact_lock` sobre três chaves, sempre na mesma ordem (`id`, pagador, conta destino) para evitar deadlock. Isso serializa requisições do mesmo pagador: uma rajada paralela passa uma de cada vez, cada requisição enxerga o que as anteriores gravaram e o R2 consegue disparar. As janelas de 24 h (R12 e R26) ficam sem trava, porque uma corrida de milissegundos quase não muda esses sinais. Restrições `UNIQUE` em `id` e `transaction_id` são a última barreira contra análises duplicadas.

As janelas históricas usam a `transaction_date` do evento, consideram registros com data menor ou igual a ela e excluem o próprio evento. O evento, a análise e as regras acionadas são gravados na mesma transação, evitando registros parciais.

## Como rodar e testar

Requisitos: Docker e Docker Compose. O projeto parte do Base Service (Python, FastAPI, PostgreSQL), com as camadas rota, serviço e repositório.

```bash
# sobe a API e o PostgreSQL
docker compose up --build
```

A documentação interativa da API fica em `http://localhost:8000/docs`.

Exemplo de requisição (payload do desafio):

```bash
curl -X POST http://localhost:8000/pix/transaction \
  -H "Content-Type: application/json" \
  -d '{
    "id": "pix-000123",
    "amount": 150000,
    "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {
      "branch": "0001", "account_number": "88213",
      "opening_date": "2025-03-02T10:00:00-03:00",
      "owner": { "document_number": "123.456.789-09" }
    },
    "destination_account": {
      "participant": "60701190", "branch": "3675", "account_number": "10442",
      "opening_date": "2026-10-10T09:00:00-03:00",
      "owner": { "document_number": "987.654.321-00" }
    },
    "source": {
      "device_id": "dvc-9f2c71a8", "channel": "app", "ip": "198.51.100.23",
      "geolocation": { "latitude": -23.56, "longitude": -46.65 }
    }
  }'
```

Com o banco vazio, a resposta é `201` com `status` `two_factor_required` e `risk_score` 2 (só o R6 dispara). Repetir o mesmo corpo devolve `200` com a mesma análise; mudar qualquer campo mantendo o `id` devolve `409`. Para consultar:

```bash
curl http://localhost:8000/pix/transaction/pix-000123
```

Testes:

```bash
docker compose run --rm api pytest
```

Cada regra é uma função pura (evento e histórico entram, pontos e motivo saem), então os testes unitários das regras e da combinação (tetos e faixas) rodam sem banco. Os testes de integração usam o PostgreSQL e conferem idempotência (`200` e `409`), `404` no GET e a rajada paralela do mesmo pagador.

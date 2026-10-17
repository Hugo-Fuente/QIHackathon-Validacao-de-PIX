# Motor Antifraude Pix

**Integrantes:** Hugo Gomes · Leandro Apolinário Leite · Mateus Carósio  
**Data:** 17/10/2026  
**Versão das regras:** 5

## Como o motor de decisão funciona

O motor recebe um pedido de Pix, compara com o histórico local do pagador, do destinatário e do dispositivo e devolve a decisão (`approved`, `two_factor_required` ou `rejected`) antes de o dinheiro sair, em poucos segundos e sem consulta externa. Cada regra é uma função pura: recebe o evento e o histórico e devolve pontos e o motivo observado. O motor soma os pontos, aplica tetos por família e mapeia o total em um status. Cada regra acionada fica gravada para auditoria.

Passo a passo de um `POST /pix/transaction`:

1. Valida e normaliza o evento (documentos só com dígitos, datas em UTC) e calcula o `payload_hash`.
2. Abre uma transação PostgreSQL e trava o `id`, o pagador e a conta destino com `pg_advisory_xact_lock`.
3. Se o `id` já existe: mesmo hash devolve a análise gravada (`200`); hash diferente devolve `409`.
4. Carrega o histórico local (janelas relativas à `transaction_date` do evento) e junta o `context` do EPP, quando houver.
5. Roda a checagem de integridade C1 (só EPP), executa as regras em ordem fixa, aplica os tetos, soma e define o `status`.
6. Grava evento, análise e regras acionadas na mesma transação e devolve `201`.

Há três blocos de lógica:

- **Núcleo Pix (R1–R12, R28, R29):** sempre avaliado, para qualquer pedido de Pix.
- **Contexto EPP (R13–R27, R30–R32):** só quando o chamador é uma conta compartilhada de empresa de pequeno porte (EPP), em que vários sócios criam e aprovam pedidos, e envia o bloco opcional `context` (sócio autor, saldo livre, limites, mudanças de controle). Nesse caso, algumas regras do núcleo são ajustadas ou substituídas. Sem `context`, valem exatamente as regras do núcleo.
- **Checagem de integridade C1 (EPP):** não pontua; garante que o que foi aprovado é o que está sendo executado.

O contrato do desafio não muda: o payload de exemplo, sem `context`, é aceito e analisado só pelo núcleo. O `context` é uma extensão opcional da entrada, e a saída continua sendo `key`, `status` e `metadata`.

A versão 5 nasceu de uma revisão de brechas da versão 4: cenários em que o motor deixava passar fraude (sócios coniventes, esvaziamento em fatias, fracionamento por documento, agendamento como atalho, conta nova sem histórico). O que cada brecha mudou está na seção [Brechas analisadas e como a v5 responde](#brechas-analisadas-e-como-a-v5-responde). O que ficou de fora de propósito está em [Limitações conhecidas e roadmap](#limitações-conhecidas-e-roadmap-não-implementado-na-v5).

## Regras

Os parâmetros são pontos de partida, calibrados com os cenários de teste. Cada linha explica o porquê da regra e de cada número escolhido. Regras marcadas com **(v5)** são novas ou foram revisadas nesta versão.

### Núcleo Pix (R1–R12, R28, R29)

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
| **R10 — Pagador recente (v5)** | A conta pagadora é nova. | Conta pagadora com ≤ 30 dias e `amount` ≥ R$ 2.000. **+1**; **+2** se o pagador tem menos de 3 Pix no histórico. | A idade da conta é um sinal complementar. Na v4 valia sempre 1, mas conta nova também não tem histórico mínimo, e sem ele R4, R5 e R7 não avaliam: o primeiro Pix de R$ 4.900 de uma conta de 10 dias saía `approved`. Sem perfil nenhum, o R10 é a única proteção, por isso pesa 2 e leva a 2FA. O piso de R$ 2.000 continua porque conta nova, sozinha, não é suspeita. |
| **R11 — Deslocamento impossível** | Dois Pix do mesmo pagador em lugares incompatíveis. | Geolocalização nos dois Pix; anterior há ≤ 60 min; distância ≥ 50 km; velocidade implícita > 900 km/h. **+3** | Sugere sessão usada de outro lugar. 900 km/h é a ordem de um voo comercial; 50 km filtra ruído de GPS; 60 min mantém a comparação em Pix consecutivos. Sem geolocalização, não pontua. |
| **R12 — Dispositivo compartilhado** | Um mesmo aparelho serve a várias titularidades. | Mesmo `device_id` usado por ≥ 3 documentos de pagadores distintos em 24 h. **+2** | Sugere fazenda de contas. 3 documentos deixa de fora um aparelho dividido por duas pessoas (casal, família); 24 h cobre o uso coordenado de um dia. |
| **R28 — Valor colado no piso (v5)** | O pagador repete valores logo abaixo do piso do R1 para escapar dele. | ≥ 3 Pix do pagador em 24 h (contando o atual, qualquer status), cada um entre R$ 4.500 e R$ 4.999,99 (90% a 99,99% do piso do R1). **+2** | O R1 é um degrau: R$ 4.999 vale 0 e R$ 5.000 vale 2, e quem conhece o piso fica logo abaixo. Um Pix assim é normal; três no mesmo dia são teste do controle. É a mesma ideia do R13 no EPP. Entra na família de valor. |
| **R29 — Fracionamento por documento (v5)** | O valor é dividido em vários Pix para o mesmo destinatário, mesmo em contas diferentes e acima de R$ 1.000. | ≥ 4 Pix do pagador para o mesmo documento destino (qualquer conta) em 60 min, contando o atual, soma ≥ R$ 5.000, sem teto por Pix. Não vale para destinatário recorrente (≥ 3 Pix anteriores ao início da janela). **+2** | O R8 só vê a mesma conta, em 5 min e com cada Pix < R$ 1.000; seis Pix de R$ 1.499 passavam por R2, R3 e R8. 4 Pix em 1 h separam fracionamento de duas ou três compras seguidas; R$ 5.000 é o piso do R1, então dividir para fugir dele é o caso. R8 e R29 compartilham teto, para o mesmo ato não contar duas vezes. |

### Ajustes do núcleo quando há `context` (EPP)

| Regra | No EPP | Por quê |
|---|---|---|
| **R1** | **Não avalia.** | O limite do sócio e a regra de aprovação já controlam o valor, e pagar fornecedor acima de R$ 5.000 é rotina de empresa. R4, R13 e R20 cobrem o desvio. |
| **R2, R3, R5** | Iguais; execução `scheduled` não pontua. | A folha em lote é uma rajada legítima, já aprovada; fornecedor novo é rotina (o R23 trata o caso da responsabilidade). |
| **R4** | **Adaptada:** mediana e histórico mínimo por `responsibility_id` do pedido, quando houver. | Folha e despesa pequena não dividem a mesma mediana. |
| **R6, R8, R29** | Iguais. | Conta de passagem e fracionamento são risco para qualquer pagador; fugir do limite do sócio também é fracionar. |
| **R7** | **Não avalia** (vale o R17). | Conta compartilhada tem vários sócios, cada um com seus aparelhos; o histórico por conta geraria falso positivo. |
| **R9** | **Não avalia** (vale o R26). | Os "pagadores distintos" do EPP são empresas; o R26 é a mesma regra com janela de 24 h. |
| **R10** | **Não avalia** (vale o R24). | A idade da conta pagadora é a ativação, e o R24 já a mede. |
| **R11** | **Não avalia** (vale o R18). | Dois sócios em cidades diferentes são normais; só faz sentido por autor. |
| **R12** | **Adaptada:** ≥ 3 `author_id` distintos, de empresas diferentes, em 24 h. | Sócios da mesma empresa no computador do escritório, ou um sócio com várias empresas, não são fazenda de aparelhos. |
| **R28** | **Não avalia** (vale o R13). | O R1 não existe no EPP, então não há piso para colar; o teto que importa é o do sócio, que o R13 mede. |

### Contexto EPP (R13–R27, R30–R32)

O "autor" é o sócio que criou o pedido; "recorrente" é a contraparte já paga ≥ 3 vezes pela empresa.

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **R13 — Valor colado no limite** | O autor testa o controle repetindo valores logo abaixo dele. | ≥ 3 pedidos do autor em 24 h, cada um entre 90% e 99,9% do menor valor entre o limite do autor e o gatilho de aprovação; não conta recorrente. **+2** | Quem testa o controle repete valores logo abaixo dele; 3 repetições separam teste de coincidência; mensalidade fixa não é teste. |
| **R14 — Recriação após recusa** | O autor refaz um pedido que outro sócio recusou. | Mesma contraparte; valor entre 80% e 120% do recusado; recusa por outro sócio em ≤ 24 h; cancelamento pelo autor não conta. **+2** | A recusa é um sinal de controle interno que o Pix de varejo não tem; a faixa de ±20% pega o valor ajustado para tentar de novo. |
| **R15 — Aprovação disfarçada** | O voto não vem de uma pessoa distinta do autor. | Evento `vote`: mesmo `device_id` do autor do pedido, ou mesmo IP e voto em < 10 s da criação. **+3** | O quórum exige pessoas distintas, e o EPP só barra o autor votando em si. IP sozinho é fraco (mesmo escritório); por isso exige o voto quase imediato. |
| **R16 — Afrouxamento de controle seguido de uso (v5)** | Controles são afrouxados pouco antes de o pedido sair. | Em ≤ 24 h depois de elevar limite, criar permissão, afrouxar regra de aprovação, definir substituto, **remover ou incluir sócio ou reduzir o quórum**, o pedido só passa por causa disso; ignora empresa com < 7 dias de conta. **+3** | Mexer nos controles pouco antes de usar é o padrão de abuso de um sistema de controles configuráveis. A v5 inclui mudança de quadro e de quórum: tirar um sócio ou baixar o quórum de 4 para 3 é o passo que antecede o desvio entre sócios coniventes. A empresa nova ainda está configurando tudo. |
| **R17 — Dispositivo novo do sócio** | O R7 aplicado ao histórico do autor. | `device_id` fora dos últimos 20 pedidos não rejeitados do autor; histórico ≥ 3; valor ≥ R$ 500. **+2** | Numa conta compartilhada, cada sócio tem seus aparelhos. Parâmetros iguais aos do R7. |
| **R18 — Deslocamento e IP do sócio** | O R11 por autor, com fallback por IP. | Janela ≤ 12 h; sem geolocalização, país do IP (base local) diferente do último IP do autor. **+3** | Sessão usada de outro lugar; a janela maior que a do R11 cobre voos longos. |
| **R19 — Horário atípico** | Pedido fora do horário habitual do autor. | Pedido imediato criado entre 0h e 5h (fuso do Brasil), valor ≥ R$ 1.000, autor com ≥ 10 operações e nenhuma nesse horário. **+1** | Usa a hora de criação, nunca a da execução, para não punir pagamento agendado; as 10 operações garantem que há hábito para comparar. |
| **R20 — Esvaziamento (v5)** | Saídas que drenam o saldo livre, de uma vez ou em fatias. | Saídas pagas com saldo livre nas últimas 24 h, contando a atual, somam ≥ 70% do saldo livre anterior à primeira delas (saldo livre antes deste pedido + saídas livres anteriores da janela) e ≥ R$ 5.000; pagamento coberto por reserva de responsabilidade não conta. **+2** | Folha e imposto saem de reserva por desenho; saldo livre drenado é o sinal. Medir só por evento deixava passar três saídas de 60% do saldo restante (cerca de 94% drenado sem acionar nada); acumulado em 24 h, a segunda saída (84%) já dispara. O piso evita pontuar empresas com saldo pequeno. |
| **R21 — Liberação de reserva seguida de saída** | O dinheiro reservado é liberado e sai logo depois. | Liberação ou transferência entre reservas e, em ≤ 30 min, saída do autor ≥ 80% do liberado para contraparte nova. **+3** | Tira da empresa o dinheiro de impostos ou folha; a janela curta liga a saída à liberação. |
| **R22 — Destino é sócio** | O dinheiro vai para o CPF de um sócio. | Contraparte com o CPF de um sócio, valor ≥ R$ 2.000; não vale para recorrente com valor ±20% (pró-labore). **+1** | O dinheiro é da empresa, não dos sócios; isolada pesa pouco e soma com R13, R15 ou R20. |
| **R23 — Contraparte nova para a responsabilidade** | Responsabilidade previsível paga um destino fora do padrão. | Responsabilidade com ≥ 5 pagamentos e ≤ 3 contrapartes em 90 dias recebe pedido de contraparte nunca paga por ela, valor ≥ R$ 1.000. **+1** | Impostos e folha pagam sempre os mesmos destinos. Não soma com o R5: o mesmo fato não conta duas vezes. |
| **R24 — Conta recém-ativada com saída grande** | Conta nova movimenta muito. | Ativada há ≤ 30 dias: saída externa ≥ R$ 5.000 vale 1; ≥ R$ 20.000 vale 2. **+1 ou +2** | Usa a ativação, não o cadastro, pois a conta só movimenta depois da aprovação do back-office; os dois degraus pesam mais o valor maior. |
| **R25 — Passagem entrada → saída** | Dinheiro entra e sai quase de imediato. | Entradas externas ≥ R$ 10.000 em 24 h e saída ≥ 80% delas em ≤ 2 h para contraparte nova, em empresa ativa há ≤ 90 dias ou só com pagadores novos. **+3** | Conta de passagem. É a de maior risco de falso positivo: calibrar primeiro. |
| **R26 — Destinatário em rede** | O mesmo destinatário recebe de várias empresas. | Mesmo documento de contraparte com pedidos de ≥ 4 empresas em 24 h, soma ≥ R$ 10.000, contando o atual; não vale se for recorrente para a empresa atual. **+3** | Só a plataforma enxerga várias empresas. Revisar a base legal (LGPD) e consultar por hash do documento. |
| **R27 — Sócio de muitas empresas (alerta)** | Um mesmo CPF de sócio aparece em muitas empresas da plataforma em pouco tempo. | Mesmo CPF de sócio (`context.partner_documents`) em ≥ 3 `company_id` distintos com eventos nos últimos 30 dias, contando o atual. **0** | Só alerta: aparece em `reasons` para o back-office e não altera o status. Usa a atividade que o motor viu, não o cadastro, porque onboarding e cadastro de contas ficam fora do escopo. |
| **R30 — Saída da empresa fora do padrão (v5)** | Os sócios, somados, tiram da empresa muito mais do que ela costuma movimentar, cada um dentro do seu limite. | Saídas livres da empresa em 24 h (contando a atual; exclui pagamento coberto por reserva e execução `scheduled`) ≥ 3× a média diária dos 30 dias anteriores à janela e ≥ R$ 10.000; empresa ativada há ≥ 30 dias e com ≥ 10 saídas no período. **+2** | R13, R14 e R17–R19 olham um autor por vez, e o R3 só olha 10 min: quatro sócios abaixo do próprio limite passavam. É o único sinal que não depende de quem pede. 3× filtra a oscilação de fim de mês; o piso evita empresa pequena; sem 30 dias de histórico não há média confiável. |
| **R31 — Destino ligado a sócio (v5)** | O dinheiro vai para empresa ou pessoa ligada a um sócio, além do CPF dele (R22). | Contraparte é CNPJ do qual um sócio da empresa também é sócio, ou CPF de sócio de outra empresa da plataforma (`context.destination_partner_documents`, quando a plataforma conhece a contraparte); valor ≥ R$ 2.000; não vale para recorrente com valor ±20%. **+2** | Desviar para a segunda empresa do mesmo sócio contorna o R22, que só compara CPF. Pesa mais que o R22 (+1) porque exige vínculo comprovado, não coincidência. R22 e R31 são o mesmo fato e compartilham teto. |
| **R32 — Credencial trocada seguida de saída (v5)** | O autor troca senha, e-mail, telefone ou 2FA e logo depois tira dinheiro. | Em ≤ 24 h depois de `context.credential_changed_at` do autor, pedido imediato ≥ R$ 2.000; ignora autor com credencial criada há < 7 dias. **+2** (família de sessão, teto 4) | É o precursor clássico de tomada de conta e não era visto: o R16 olha controles da empresa, não credenciais do sócio. 24 h acompanha o R16; o piso é baixo porque o sinal é forte, e o teto de sessão impede que reprove sozinho. |

### Checagem de integridade (C1, EPP)

| Checagem | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **C1 — Pedido ≠ voto ≠ execução (v5)** | O que foi aprovado precisa ser o que está sendo executado. | Em `vote` e `execution`, `context.request_id` e `context.request_hash` são obrigatórios (`422` se faltarem). Se o pedido não existe, está `rejected`, ou o `request_hash` difere do gravado no evento `request`, o status é `rejected` e o `RULE_HIT` `C1` grava 0 pontos e o motivo. | Nada amarrava o voto ou a execução ao conteúdo do pedido: valor ou destino podiam ser editados depois da aprovação. Não é pontuação, é consistência: um hash diferente não tem versão "meio suspeita". As demais regras seguem rodando, só para registrar os motivos. |

## Como as regras viram decisão

**Ordem.** A C1 roda primeiro (só em `vote` e `execution`) e, se acionada, força `rejected`. As regras aplicáveis são executadas em ordem fixa (R1 a R32), sem interromper na primeira que dispara. A ordem só deixa estável a lista de motivos. Cada regra acionada gera um `RULE_HIT` com os pontos antes do teto.

**Tetos por família.** O mesmo ato não deve contar várias vezes:

- Valor: R1 + R3 + R4 + R28 somam no máximo **3**.
- Fracionamento: R8 + R29 somam no máximo **2**.
- Controles internos (EPP): R13 + R14 + R16 somam no máximo **3**.
- Sessão do sócio (EPP): R17 + R18 + R19 + R32 somam no máximo **4**.
- Destino ligado a sócio (EPP): R22 + R31 somam no máximo **2**.

**Faixas.** O `risk_score` é a soma depois dos tetos:

| Pontos | Status |
|---|---|
| 0–1 | `approved` |
| 2–4 | `two_factor_required` |
| ≥ 5 | `rejected` |

**Quando pede 2FA.** Com 2 a 4 pontos há dúvida, mas não risco claro: o cliente confirma que é ele mesmo e a transação segue. Um único sinal moderado (valor alto, destino recém-aberto, destino concentrador, dispositivo novo) leva a 2FA, nunca a `rejected`. Como valor alto soma no máximo 3, reprovar exige pelo menos 2 pontos vindos de outros sinais. Sinais de sessão do sócio, sozinhos, também nunca reprovam.

**Exceções e histórico.**

- Se o documento do pagador for igual ao do destinatário, R5, R6 e R9 não pontuam.
- **Pagamento programado (v5).** A isenção vale só para a **execução** (`context.event` = `execution` e `origin` = `scheduled`): ela não pontua R2, R3, R5 nem R17 a R19, porque o lote da folha não deve ser rejeitado por rajada e contraparte nova, e o aparelho de quem agendou não existe na execução. O **pedido que cria o agendamento** (`event` = `request`) é avaliado com todas as regras. Sem isso, quem agenda um pagamento futuro a uma contraparte nova, de um aparelho novo, passava limpo. Na execução continuam valendo a C1 e as regras de estado da conta (R16, R20, R21, R24, R25).
- O histórico de confiança (R4, R5, R7, R17) exclui apenas Pix `rejected`. O motor não recebe o resultado do 2FA, e contar só os `approved` faria o cliente do aluguel cair em 2FA todo mês.
- O histórico de rajada e concentração (R2, R3, R8, R9, R11, R12, R28, R29) considera qualquer status, porque tentativas rejeitadas também revelam o padrão.

**Quem aplica a decisão.** O motor só decide e sugere; quem aplica é o chamador. No EPP, `two_factor_required` pode virar segundo fator do autor ou aprovação adicional de outro sócio, e `rejected` em um voto significa que o voto não conta. Em evento EPP com status diferente de `approved`, se alguma entre R16, R20, R21, R22, R30, R31 e R32 for acionada, `metadata.recommended_actions` traz `notify_all_partners`: o EPP deve avisar todos os sócios, inclusive os que não votaram, antes de liberar o dinheiro.

**Motivos.** `metadata.reasons` traz regra, pontos e valores observados, para auditoria. O chamador não deve exibir esse detalhe ao cliente final (mensagem genérica), porque os parâmetros revelados ensinam como ficar abaixo deles.

**Exemplos.**

- Cliente com mediana de R$ 200 que paga R$ 6.000 pela primeira vez a um locador, no aparelho de sempre: R1 (2) + R4 (2), limitados a 3 pela família de valor, mais R5 (1) = 4. Recebe 2FA.
- Sessão sequestrada de um sócio, com aparelho nunca visto (R17, 2), às 2h10 (R19, 1) e saída de 87% do saldo livre (R20, 2): 5 pontos. É rejeitada.
- Pix do payload de exemplo do desafio (R$ 1.500, conta destino aberta 7 dias antes, pagador sem histórico): só o R6 dispara, 2 pontos, `two_factor_required`.
- Conta de 10 dias, primeiro Pix de R$ 4.900 para uma conta antiga: R1 não dispara (abaixo de R$ 5.000), R4, R5 e R7 não avaliam (sem histórico), R10 vale 2 por falta de perfil: 2FA. Na v4 valia 1 e saía `approved`.
- Empresa com 4 sócios, saída de R$ 40.000 (mais de 3× a média diária) para um CNPJ de outro sócio: R30 (2) + R31 (2) = 4, `two_factor_required` com `notify_all_partners`. Se o quórum foi reduzido 6 h antes, o R16 soma 3 e o total é 7: `rejected`.

## Brechas analisadas e como a v5 responde

A versão 4 foi revisada procurando cenários em que o motor deixava passar fraude. Cada brecha abaixo virou uma regra, uma revisão ou uma limitação documentada.

| Cenário de risco | Como passava na v4 | O que a v5 faz |
|---|---|---|
| Sócios coniventes (3 de 4) aprovam saídas de aparelhos distintos | R15 não dispara (são pessoas distintas); R13, R14 e R17–R19 olham um autor por vez; R22 só compara CPF | **R30** (volume da empresa), **R31** (destino ligado a sócio), **R16** revisada (mudança de quadro e quórum), **R32** (credencial trocada) e `notify_all_partners` |
| Esvaziar o saldo livre em fatias | R20 media cada saída isolada: três saídas de 60% drenavam cerca de 94% | **R20** acumulado em 24 h |
| Dividir o valor entre contas do mesmo titular, com Pix acima de R$ 1.000 | R8 exige mesma conta, 5 min e Pix < R$ 1.000 | **R29** por documento, 60 min, sem teto por Pix |
| Ficar logo abaixo do piso de R$ 5.000 | R1 é um degrau: R$ 4.999 vale 0 | **R28** (3 Pix colados em 24 h) |
| Conta nova, sem histórico | R4, R5 e R7 desligam; só o R10 (1 ponto) | **R10** vale 2 sem perfil |
| Agendamento como atalho | Isenção do `scheduled` ambígua: criar o agendamento poderia escapar | Isenção só na execução; a criação é avaliada por completo |
| Editar valor ou destino depois da aprovação | Nada ligava voto e execução ao pedido | **C1** com `request_hash` |
| Tomada de conta por troca de credenciais | Não era um sinal | **R32** |

**O que o motor não resolve sozinho.** Três sócios com credenciais válidas, votando em quórum válido, não são identificáveis só por regras: o motor enxerga mudança de comportamento (R30, R31, R16), não intenção. A proteção do sócio de fora é de produto: notificar todos os sócios, manter uma janela curta de contestação e registrar entrega e leitura da notificação. O motor contribui com a sugestão `notify_all_partners`. Se esse sócio responde ou não perante a lei é questão de jurídico e compliance.

## Limitações conhecidas e roadmap (não implementado na v5)

Itens abaixo são decisões de escopo, não esquecimentos: custam tabela nova, endpoint novo ou dado que o chamador ainda não envia. Nenhum deles está ativo, e nenhuma regra desta seção pontua.

**Princípio para lavagem de dinheiro:** padrões de AML entram como **alerta de 0 ponto para a fila do back-office**, como o R27 já faz. O falso positivo não trava o cliente, o `RULE_HIT` com 0 pontos não exige schema novo, e a decisão de comunicar ao COAF é do compliance. Bloqueio em tempo real fica só para quando a soma de pontos chega a 5.

| Alerta (0 pt) | Lógica proposta | Por quê |
|---|---|---|
| **A1 — Giro de 7 dias** | Entradas externas ≥ R$ 20.000 em 7 dias e saídas ≥ 90% delas | O R25 só pega passagem em 2 h; lavagem real espalha a saída em dias |
| **A2 — Ciclo** | O destino pagou a origem nos 7 dias anteriores, com valor entre 80% e 120% do atual (A→B→A) | Movimento circular entre contas da plataforma; consulta local de 2 saltos |
| **A3 — Fan-out** | ≥ 5 contrapartes novas distintas da empresa em 24 h | R5 e R23 olham uma contraparte por vez |
| **A4 — Porte incompatível** | Volume de 30 dias > 3× o faturamento mensal declarado (`context.declared_monthly_revenue`) | Volume incompatível com o cadastro; o dado só é lido, o onboarding segue fora do escopo |
| **A5 — Conta dormente** | ≥ 90 dias sem movimento e saída ≥ R$ 5.000 | O R24 só cobre conta nova |
| **A6 — Quórum seletivo** | ≥ 3 pedidos ≥ R$ 5.000 em 30 dias aprovados sem voto nem ciência do mesmo sócio ativo | Sinal de que um sócio está sendo deixado de fora |

Outros itens do roadmap:

- **Lista local de partes sinalizadas (`flagged_party`):** documentos e contas confirmados como mula ou fraude, alimentados pelo back-office; match gera `rejected`. É o bloqueio categórico que o desenho já prevê, e exige uma tabela e um jeito de popular.
- **Retorno de resultado:** o motor não sabe o resultado do 2FA nem se um Pix virou devolução. Um endpoint de resultado alimentaria o histórico e a lista acima.
- **Quarto lock por documento destino (EPP):** o R26 é por documento, mas o lock é por conta destino; quatro empresas pagando o mesmo documento, em contas diferentes e em paralelo, não se enxergam. O custo é serializar pagamentos a um CNPJ muito pagador, então precisa de medição.
- **Validação do relógio:** as janelas usam a `transaction_date` do chamador; data retroativa ou fora de ordem tira o evento das janelas dos outros. O motor confia no chamador.
- **Rampa longa de valor:** a mediana do R4 resiste até cerca de 10 passos de aumento gradual; uma rampa mais longa e lenta passa.
- **Engenharia social:** o sócio verdadeiro, no aparelho verdadeiro, induzido a pagar. Nenhuma regra pega bem; a mitigação é de produto (aviso para contraparte nova de valor alto).
- **Machine learning:** continua fora, por falta de dados rotulados. As regras gravadas por evento são a base auditável para isso.

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
- `context` (opcional, enviado pelo EPP): `event` (`request`, `vote` ou `execution`), `origin` (`immediate` ou `scheduled`), `company_id`, `author_id`, `responsibility_id` e os fatos que só o EPP conhece (saldo livre, limites, ativação da conta, mudanças de controle, liberação de reserva, documentos dos sócios). **Novos na v5:** `request_id` e `request_hash` (obrigatórios em `vote` e `execution`), `credential_changed_at` (do autor, opcional) e `destination_partner_documents` (opcional).

**Resposta** (`key`, `status`, `metadata`): `metadata` traz `risk_score`, `reasons` (as regras acionadas com pontos e valores observados), `rules_version` e `recommended_actions` (lista, pode ser vazia).

**Status:**

- `201`: análise criada.
- `200`: mesmo `id` e mesmo payload; devolve a análise já gravada, sem reprocessar.
- `400`: corpo ilegível ou JSON malformado.
- `409`: mesmo `id` enviado com payload diferente.
- `422`: campo ausente ou de tipo errado, `amount` não inteiro ou ≤ 0, data sem fuso, documento sem 11 ou 14 dígitos, latitude ou longitude fora da faixa, `context` com `event` inválido ou sem `author_id`, ou `vote`/`execution` sem `request_id` e `request_hash`.
- `500`: falha interna; tudo é revertido e o reenvio é seguro.

### `GET /pix/transaction/{id}`

Consulta a análise registrada para o `id` do evento (não o `key`). Somente leitura.

- `200`: `key`, `status` e `metadata` da análise.
- `404`: não existe análise para o `id` informado.

## Banco de dados

O sistema usa PostgreSQL e mantém o evento, a análise e as regras acionadas.

### `PIX_TRANSACTION`

Armazena o evento recebido: `id` (chave primária e idempotência), `payload_hash`, valor em centavos, data da transação em UTC, dados normalizados do pagador e do destinatário (documento só com dígitos, conta, data de abertura), `destination_account_key` (participante, agência e conta), dispositivo, canal, IP, geolocalização opcional, campos do EPP (`event_type`, `origin`, `company_id`, `author_id`, `responsibility_id`), o `context` em `jsonb` para reproduzir a decisão, o payload original e a data de recebimento. Índices por documento do pagador, conta destino, documento do destinatário, dispositivo e autor, sempre com `transaction_date`, apoiam as consultas de histórico.

Requisições recusadas na validação (`400` ou `422`) não viram evento nem análise; todo evento válido fica gravado e consultável pelo `GET`.

**Novos na v5:** colunas `request_id` e `request_hash` (para a C1, com índice em `request_id`) e índice por `company_id` com `transaction_date` (para R20 acumulado e R30).

### `FRAUD_ANALYSIS`

Uma única análise por evento: `key` (UUID), `transaction_id` (referência única ao evento), `status`, `risk_score`, `rules_version` e `analyzed_at`.

### `RULE_HIT`

Cada regra acionada: identificador, chave da análise, código da regra (R1–R32 e C1), pontos antes do teto e detalhe dos valores observados e parâmetros usados.

Relacionamentos: cada `PIX_TRANSACTION` recebe uma `FRAUD_ANALYSIS`; uma análise tem zero ou várias entradas em `RULE_HIT`.

## Idempotência e concorrência

O motor calcula `payload_hash` (SHA-256) sobre o payload normalizado. O mesmo `id` com o mesmo hash retorna a decisão existente; o mesmo `id` com hash diferente retorna `409`.

Durante a análise, uma transação PostgreSQL usa `pg_advisory_xact_lock` sobre três chaves, sempre na mesma ordem (`id`, pagador, conta destino) para evitar deadlock. Isso serializa requisições do mesmo pagador: uma rajada paralela passa uma de cada vez, cada requisição enxerga o que as anteriores gravaram e o R2 consegue disparar. No EPP, o pagador é a conta da empresa, então R20 acumulado e R30 também leem um histórico consistente. As janelas de 24 h por documento ou dispositivo (R12 e R26) ficam sem trava, porque uma corrida de milissegundos quase não muda esses sinais; a exceção deliberada, entre empresas diferentes, está no roadmap. Restrições `UNIQUE` em `id` e `transaction_id` são a última barreira contra análises duplicadas.

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

### Cenários de aceitação

Cada linha vira um teste de integração; a coluna "Pontos" é o resultado esperado depois dos tetos, assumindo que nenhuma outra regra dispara.

| # | Cenário | Regras | Pontos | Status |
|---|---|---|---|---|
| 1 | Payload do desafio (R$ 1.500, destino aberto há 7 dias, sem histórico) | R6 | 2 | `two_factor_required` |
| 2 | Mediana de R$ 200 paga R$ 6.000 a um locador novo | R1 + R4 (teto 3) + R5 | 4 | `two_factor_required` |
| 3 | Sessão sequestrada de sócio: aparelho novo, 2h10, saída de 87% do saldo livre | R17 + R19 + R20 | 5 | `rejected` |
| 4 | Conta de 10 dias, primeiro Pix de R$ 4.900 para conta antiga | R10 (sem perfil) | 2 | `two_factor_required` |
| 5 | Perfil alto (mediana R$ 4.000), 3º Pix entre R$ 4.500 e R$ 4.999 em 24 h para contraparte conhecida | R28 | 2 | `two_factor_required` |
| 6 | 4º Pix de R$ 1.499 ao mesmo documento, em contas diferentes, em 12 min | R29 (+ R5 se a conta for nova) | 2 a 3 | `two_factor_required` |
| 7 | EPP: 1ª saída de 60% do saldo livre; depois 2ª de 60% do saldo restante em 24 h | 1ª: nenhuma; 2ª: R20 (84% acumulado) | 0; 2 | `approved`; `two_factor_required` |
| 8 | EPP, 4 sócios: saída de R$ 40.000 (> 3× a média diária) para CNPJ de outro sócio | R30 + R31 | 4 | `two_factor_required`, com `notify_all_partners` |
| 9 | Cenário 8, 6 h depois de reduzir o quórum | R30 + R31 + R16 | 7 | `rejected` |
| 10 | EPP: credencial trocada há 3 h, aparelho novo, saída de R$ 8.000 (75% do saldo livre) | R32 + R17 (teto sessão 4) + R20 | 6 | `rejected` |
| 11 | `execution` com `request_hash` diferente do pedido aprovado | C1 | n/a | `rejected` |
| 12 | `request` que cria agendamento (aparelho e contraparte novos); depois a `execution` na data com o mesmo hash | `request`: R5 + R17; `execution`: isenta | 3; 0 | `two_factor_required`; `approved` |

**Casos de borda a testar em cada regra nova ou revisada:** R28 com 2 vs 3 Pix e R$ 4.499,99 vs R$ 4.500 vs R$ 5.000; R29 com 3 vs 4 Pix, soma R$ 4.999 vs R$ 5.000 e destinatário recorrente; R10 com 2 vs 3 Pix de histórico; R20 em 69% vs 70% acumulados e pagamento coberto por reserva; R30 com 2,9× vs 3× e empresa com 29 vs 30 dias; R31 com recorrente ±20%; R32 com 23 h vs 25 h depois da troca; C1 com pedido ausente, `rejected` e hash diferente.

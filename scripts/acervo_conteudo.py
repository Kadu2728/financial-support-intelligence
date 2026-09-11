"""Conteúdo do acervo sintético de demonstração.

Atenção: material Fictício, criado para demonstrar o sistema. O "Banco Exemplo S.A."
não existe. Prazos, valores, códigos e procedimentos aqui são inventados e Não devem
ser usados como referência real.

Os documentos citam normas reais pelo número — como todo procedimento interno faz —
mas o texto é o procedimento interno fictício, nunca o conteúdo da norma.

O conteúdo foi escrito para exercitar o pipeline de RAG:

- **Hierarquia numerada** (1, 1.1, 1.1.1) alimenta o `section_path`, que vira a citação
  exibida. Sem ela, o chunker não tem o que detectar.
- **Valores, prazos e códigos exatos** (D+1, R$ 5.000,00, COD-2041) exercitam a perna
  lexical da busca híbrida, onde embeddings falham.
- **Vocabulário repetido entre documentos** (cadastro, titularidade, contestação) cria
  ambiguidade real: recuperar a seção certa exige mais que casar palavras.
- **Referências cruzadas** entre documentos produzem perguntas cuja resposta vive em
  dois lugares, exercitando o top-K e a deduplicação por seção.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Secao:
    numero: str
    titulo: str
    paragrafos: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Documento:
    arquivo: str
    titulo: str
    categoria: str
    descricao: str
    formato: str  # pdf | docx | md | txt
    codigo: str
    versao: str
    secoes: list[Secao]


INSTITUICAO = "Banco Exemplo S.A."
AVISO = (
    "Documento fictício, gerado para demonstração técnica do Financial Support "
    "Intelligence. O Banco Exemplo S.A. não existe. Prazos, valores e procedimentos "
    "descritos são inventados e não constituem orientação real."
)


MANUAL_CADASTRO = Documento(
    arquivo="manual-cadastro-pessoa-fisica.pdf",
    titulo="Manual de Cadastro de Pessoa Física",
    categoria="Cadastro",
    descricao="Abertura, manutenção e atualização cadastral de clientes pessoa física.",
    formato="pdf",
    codigo="MAN-CAD-001",
    versao="4.2",
    secoes=[
        Secao("1", "Objetivo e abrangência", [
            "Este manual estabelece os procedimentos de abertura, manutenção e atualização "
            "do cadastro de clientes pessoa física no Banco Exemplo S.A. Aplica-se a todos "
            "os canais de atendimento: agências, central telefônica, aplicativo e portal web.",
            "O cumprimento integral destes procedimentos é obrigatório. Divergências "
            "identificadas em auditoria interna são tratadas conforme a Politica de "
            "Conformidade (POL-PLD-004).",
        ]),
        Secao("2", "Documentação exigida na abertura", [
            "A abertura de conta exige a apresentação de documento de identificação com "
            "foto, comprovante de inscrição no CPF e comprovante de residência emitido nos "
            "últimos 90 dias.",
        ]),
        Secao("2.1", "Documentos de identificação aceitos", [
            "São aceitos: Carteira de Identidade (RG), Carteira Nacional de Habilitação "
            "(CNH), Carteira de Trabalho e Previdência Social (CTPS), passaporte válido e "
            "carteiras funcionais com fé pública.",
            "Documentos com validade expirada não são aceitos, com exceção do RG, que não "
            "possui prazo de validade legal. A CNH vencida ha mais de 30 dias deve ser "
            "recusada e o cliente orientado a apresentar documento alternativo.",
        ]),
        Secao("2.2", "Comprovante de residência", [
            "O comprovante deve estar em nome do titular e ter sido emitido nos últimos 90 "
            "dias. São aceitas contas de água, luz, gás, telefone fixo, internet banda larga "
            "e fatura de cartão de crédito de outra instituição.",
            "Quando o comprovante estiver em nome de terceiro, exige-se declaração de "
            "residência assinada pelo titular do comprovante, acompanhada de cópia do "
            "documento de identificação deste. O formulário padrão e o FOR-CAD-017.",
        ]),
        Secao("3", "Atualização cadastral", [
            "A atualização cadastral é o procedimento de revisão e confirmação periódica dos "
            "dados do cliente. E obrigatória e sua ausência sujeita a conta a restrições "
            "operacionais.",
        ]),
        Secao("3.1", "Periodicidade", [
            "A atualização é exigida a cada 24 meses para clientes de perfil padrão e a cada "
            "12 meses para clientes classificados como de risco elevado pela área de "
            "Prevenção a Lavagem de Dinheiro.",
            "O sistema emite alerta automático 60 dias antes do vencimento do prazo. O "
            "alerta aparece na tela de atendimento com o código COD-2041.",
        ]),
        Secao("3.2", "Procedimento de atualização cadastral", [
            "O procedimento de atualização cadastral segue seis etapas obrigatórias, nesta "
            "ordem:",
            "Etapa 1 — Identificação positiva do cliente. Confirmar nome completo, CPF, data "
            "de nascimento e nome da mãe. Em atendimento telefônico, aplicar tambem duas "
            "perguntas de segurança do cadastro.",
            "Etapa 2 — Apresentação dos dados vigentes. Ler ao cliente os dados registrados "
            "e solicitar confirmação item a item.",
            "Etapa 3 — Coleta das alterações. Registrar as divergências apontadas pelo "
            "cliente no formulário FOR-CAD-003.",
            "Etapa 4 — Validação documental. Toda alteração de endereço, renda ou estado "
            "civil exige documento comprobatório. Alteração de telefone e e-mail não exige "
            "documento, mas exige confirmação por código enviado ao canal informado.",
            "Etapa 5 — Registro no sistema. Lancar as alterações na transação CAD-ATU e "
            "anexar as imagens dos documentos. O prazo de anexação é de 2 dias úteis a "
            "contar do atendimento.",
            "Etapa 6 — Confirmação ao cliente. Informar o protocolo e o prazo de efetivação, "
            "que é de até 5 dias úteis.",
        ]),
        Secao("3.3", "Atualização por canal digital", [
            "O cliente pode realizar a atualização pelo aplicativo, desde que não haja "
            "alteração de nome, CPF ou data de nascimento. Essas três informações so podem "
            "ser alteradas presencialmente, mediante apresentação dos documentos originais.",
            "A atualização digital exige autenticação por biometria facial. Três tentativas "
            "sem sucesso bloqueiam o canal por 24 horas e direcionam o cliente ao atendimento "
            "presencial.",
        ]),
        Secao("4", "Restrições por cadastro desatualizado", [
            "Decorridos 30 dias do vencimento do prazo de atualização sem regularização, a "
            "conta entra em estado de restrição parcial: ficam bloqueadas as operações de "
            "crédito, investimento e transferência acima de R$ 5.000,00 por dia.",
            "Após 90 dias, a restrição passa a total: são permitidos apenas saques, "
            "pagamento de contas do próprio titular e encerramento de conta. O desbloqueio e "
            "imediato após a conclusão da atualização.",
        ]),
        Secao("5", "Alteração de titularidade", [
            "Contas individuais não admitem transferência de titularidade. O procedimento "
            "correto e o encerramento da conta existente e a abertura de nova conta em nome "
            "do novo titular, conforme PRO-ENC-002.",
            "Em contas conjuntas, a exclusão de um titular exige anuência por escrito de "
            "todos os titulares e não gera nova conta. A inclusão de titular segue o "
            "procedimento de abertura descrito na seção 2.",
        ]),
        Secao("6", "Cadastro de pessoa politicamente exposta", [
            "Clientes enquadrados como pessoa politicamente exposta (PEP) exigem aprovação "
            "prévia da área de Prevenção a Lavagem de Dinheiro antes da efetivação do "
            "cadastro.",
            "A condicao de PEP deve ser reavaliada a cada atualização cadastral e permanece "
            "aplicavel por 5 anos após o encerramento do exercicio do cargo. O tratamento "
            "detalhado esta na Politica de Prevenção a Lavagem de Dinheiro (POL-PLD-004), "
            "seção 4.",
        ]),
    ],
)


PROCEDIMENTO_PIX = Documento(
    arquivo="procedimento-operacional-pix.pdf",
    titulo="Procedimento Operacional de Pix",
    categoria="Pagamentos",
    descricao="Chaves, limites, devolução e tratamento de incidentes em operações Pix.",
    formato="pdf",
    codigo="PRO-PIX-007",
    versao="3.1",
    secoes=[
        Secao("1", "Escopo", [
            "Este procedimento descreve o tratamento operacional de transações Pix no Banco "
            "Exemplo S.A., incluindo cadastro de chaves, limites transacionais, devolução de "
            "valores e atendimento a incidentes.",
            "O Pix opera 24 horas por dia, todos os dias do ano. Não ha janela de "
            "indisponibilidade programada para o cliente final.",
        ]),
        Secao("2", "Chaves Pix", []),
        Secao("2.1", "Tipos de chave", [
            "São admitidos cinco tipos de chave: CPF, telefone celular, e-mail, chave "
            "aleatoria e, para pessoa jurídica, CNPJ.",
            "Cada conta pode registrar até 5 chaves para pessoa física e até 20 chaves para "
            "pessoa jurídica. O limite considera o total de chaves ativas, independentemente "
            "do tipo.",
        ]),
        Secao("2.2", "Portabilidade e reivindicação de chave", [
            "Quando o cliente informa que sua chave esta registrada em outra instituição, o "
            "atendente deve orientar o processo de reivindicação de posse.",
            "O prazo de resposta da instituição detentora é de 7 dias corridos. Sem resposta "
            "no prazo, a chave e transferida automaticamente. O cliente acompanha o status "
            "pelo aplicativo, na área Minhas Chaves.",
        ]),
        Secao("3", "Limites transacionais", [
            "O limite padrão para transações Pix e de R$ 1.000,00 por transação no período "
            "noturno, das 20h as 6h, e de R$ 10.000,00 por transação no período diurno.",
            "O cliente pode solicitar aumento de limite pelo aplicativo. O pedido passa por "
            "analise automatizada e o novo limite entra em vigor em 24 horas. A reducao de "
            "limite é imediata.",
        ]),
        Secao("4", "Devolução de valores", []),
        Secao("4.1", "Devolução por erro operacional", [
            "Quando o cliente informa ter feito um Pix por engano, o atendente registra a "
            "solicitação na transação PIX-DEV e informa o protocolo.",
            "O pedido é encaminhado a instituição do recebedor, que tem prazo de até 7 dias "
            "corridos para analise. A devolução depende da concordancia do recebedor e da "
            "existencia de saldo na conta. Não ha garantia de recuperacao do valor.",
        ]),
        Secao("4.2", "Mecanismo Especial de Devolução", [
            "O Mecanismo Especial de Devolução aplica-se a casos de fundada suspeita de "
            "fraude ou de falha operacional do sistema.",
            "O prazo para acionamento é de 80 dias corridos contados da transação. A "
            "solicitação exige registro de boletim de ocorrência quando houver suspeita de "
            "crime, e o número do boletim deve ser anexado ao protocolo.",
            "O bloqueio cautelar do valor na conta do recebedor ocorre em até 60 minutos do "
            "acionamento, quando ha saldo disponível.",
        ]),
        Secao("5", "Transações não reconhecidas", [
            "Transação Pix não reconhecida pelo cliente deve ser tratada como possível "
            "fraude. O atendente registra a contestação conforme o Guia de Contestação de "
            "Transações (GUI-CON-011) e aciona o Mecanismo Especial de Devolução descrito na "
            "seção 4.2.",
            "O bloqueio preventivo das chaves Pix do cliente é recomendado quando houver "
            "indício de acesso indevido a conta.",
        ]),
        Secao("6", "Indisponibilidade", [
            "Em caso de indisponibilidade do sistema, o atendente informa que a transação "
            "será processada assim que o serviço for restabelecido e registra ocorrência no "
            "painel de incidentes.",
            "Transações Pix em processamento não devem ser reenviadas pelo cliente: o "
            "reenvio pode gerar duplicidade, cuja devolução segue o procedimento da seção 4.1.",
        ]),
    ],
)


POLITICA_PLD = Documento(
    arquivo="politica-prevencao-lavagem-dinheiro.docx",
    titulo="Politica de Prevenção a Lavagem de Dinheiro",
    categoria="Compliance",
    descricao="Conheca seu cliente, classificação de risco, monitoramento e comunicação.",
    formato="docx",
    codigo="POL-PLD-004",
    versao="6.0",
    secoes=[
        Secao("1", "Principios", [
            "O Banco Exemplo S.A. adota politica de prevenção a lavagem de dinheiro e ao "
            "financiamento do terrorismo baseada em avaliação de risco, em conformidade com "
            "a Circular 3.978 do Banco Central do Brasil e com a Lei 9.613/1998.",
            "Nenhum relacionamento comercial se sobrepoe as obrigacoes de prevenção. A "
            "recusa de inicio ou a manutenção de relacionamento por razoes de conformidade "
            "não exige justificativa ao cliente.",
        ]),
        Secao("2", "Conheca seu cliente", []),
        Secao("2.1", "Identificação e qualificação", [
            "A identificação do cliente é requisito para o inicio do relacionamento. Os "
            "documentos exigidos estão no Manual de Cadastro de Pessoa Física (MAN-CAD-001), "
            "seção 2.",
            "A qualificação complementa a identificação com informações sobre ocupacao, "
            "renda, patrimonio e finalidade do relacionamento. Divergência relevante entre "
            "renda declarada e movimentação observada e sinal de alerta e deve ser tratada "
            "conforme a seção 5.",
        ]),
        Secao("2.2", "Atualização das informações", [
            "As informações de qualificação seguem a mesma periodicidade da atualização "
            "cadastral: 24 meses no perfil padrão e 12 meses no risco elevado.",
            "A área de Prevenção pode determinar atualização antecipada a qualquer momento, "
            "independentemente do prazo regular.",
        ]),
        Secao("3", "Classificação de risco do cliente", [
            "Todo cliente recebe classificação de risco em uma de três faixas: baixo, medio "
            "ou alto. A classificação é automática, calculada a partir de ocupacao, "
            "localidade, produtos contratados, volume transacionado e condicao de pessoa "
            "politicamente exposta.",
            "A reclassificação ocorre mensalmente e a cada atualização cadastral. Clientes "
            "de risco alto exigem aprovação de diretoria para contratação de novos produtos.",
        ]),
        Secao("4", "Pessoa politicamente exposta", [
            "Considera-se pessoa politicamente exposta quem desempenha ou tenha desempenhado, "
            "nos últimos 5 anos, cargo, emprego ou funcao pública relevante, bem como seus "
            "representantes, familiares e estreitos colaboradores.",
            "O relacionamento com PEP exige aprovação prévia da área de Prevenção, "
            "classificação mínima de risco medio e monitoramento reforçado das operações.",
            "A condicao de PEP não impede o relacionamento. Recusar atendimento apenas por "
            "essa condicao é conduta incorreta e deve ser reportada a ouvidoria.",
        ]),
        Secao("5", "Monitoramento de operações", []),
        Secao("5.1", "Situacoes de alerta", [
            "São situacoes de alerta, entre outras: movimentação incompativel com a "
            "qualificação do cliente; fracionamento de valores em sequencia; recebimento de "
            "múltiplos depositos de origens não relacionadas; e resistencia injustificada em "
            "prestar informações cadastrais.",
            "O atendente que identificar situacao de alerta registra a ocorrência na "
            "transação PLD-ALE. O registro é sigiloso e não deve ser comunicado ao cliente.",
        ]),
        Secao("5.2", "Vedação a comunicação ao cliente", [
            "E vedado informar ao cliente, ou a terceiros, que uma operação foi objeto de "
            "analise ou comunicação aos órgãos competentes.",
            "A quebra dessa vedação constitui falta grave. Em caso de questionamento do "
            "cliente, o atendente informa apenas que a operação esta em analise, sem "
            "detalhar motivo, área responsável ou prazo.",
        ]),
        Secao("6", "Comunicação aos órgãos competentes", [
            "As comunicações ao Conselho de Controle de Atividades Financeiras são de "
            "responsabilidade exclusiva da área de Prevenção. Nenhuma outra área esta "
            "autorizada a efetua-las.",
            "O prazo interno para analise de uma ocorrência registrada é de 30 dias "
            "corridos, contados do registro.",
        ]),
        Secao("7", "Treinamento e responsabilidades", [
            "Todo colaborador com contato direto com cliente realiza treinamento anual "
            "obrigatório de prevenção a lavagem de dinheiro. A ausência de conclusão no prazo "
            "suspende o acesso as transações de abertura de conta.",
            "A responsabilidade pela observancia desta politica e de cada colaborador, "
            "independentemente de cargo ou área.",
        ]),
    ],
)


MANUAL_ATENDIMENTO = Documento(
    arquivo="manual-atendimento-e-prazos.docx",
    titulo="Manual de Atendimento e Prazos de Resposta",
    categoria="Atendimento",
    descricao="Canais, classificação de demandas, prazos de resposta e escalonamento.",
    formato="docx",
    codigo="MAN-ATE-002",
    versao="2.8",
    secoes=[
        Secao("1", "Canais de atendimento", [
            "O Banco Exemplo S.A. atende por quatro canais: agências, central telefônica, "
            "aplicativo e portal web. A ouvidoria constitui segunda instancia e so recebe "
            "demandas ja tratadas nos canais primarios.",
            "A central telefônica opera de segunda a sexta, das 8h as 20h, e aos sabados das "
            "9h as 15h. O atendimento a transações não reconhecidas e emergencias de "
            "segurança funciona 24 horas, todos os dias.",
        ]),
        Secao("2", "Classificação das demandas", [
            "Toda demanda recebe uma classificação no momento do registro. A classificação "
            "determina o prazo de resposta e a área responsável.",
        ]),
        Secao("2.1", "Solicitação", [
            "Pedido de serviço ou informação que não decorre de falha. Exemplos: segunda via "
            "de documento, alteração de limite, atualização cadastral.",
            "Prazo de resposta: até 5 dias úteis.",
        ]),
        Secao("2.2", "Reclamacao", [
            "Manifestação de insatisfação decorrente de falha percebida no produto ou "
            "serviço. Exemplos: cobranca indevida, demora no atendimento, falha de sistema.",
            "Prazo de resposta: até 10 dias úteis. Demandas registradas via ouvidoria seguem "
            "o prazo de 10 dias úteis contados do registro na ouvidoria, sem reinicio de "
            "contagem.",
        ]),
        Secao("2.3", "Contestação", [
            "Discordancia quanto a lancamento ou transação. O tratamento operacional esta no "
            "Guia de Contestação de Transações (GUI-CON-011).",
            "Prazo de resposta: até 7 dias úteis para transações de cartão e até 10 dias "
            "úteis para demais lancamentos.",
        ]),
        Secao("3", "Registro do atendimento", [
            "Todo contato gera protocolo, inclusive quando resolvido no primeiro "
            "atendimento. O número do protocolo deve ser informado ao cliente antes do "
            "encerramento da ligacao.",
            "O registro descreve o pedido do cliente com as palavras dele, a orientação "
            "prestada e o encaminhamento dado. Registros genericos como 'cliente orientado' "
            "são insuficientes e geram apontamento em auditoria.",
        ]),
        Secao("4", "Escalonamento", [
            "O atendente escalona a demanda quando: o prazo de resposta esta a menos de 2 "
            "dias úteis do vencimento sem solucao; o cliente manifesta intencao de acionar "
            "órgão regulador; ou o valor envolvido supera R$ 50.000,00.",
            "O escalonamento é feito pela transação Até-ESC e não dispensa o atendente de "
            "acompanhar a demanda até o encerramento.",
        ]),
        Secao("5", "Reabertura de demanda", [
            "O cliente pode solicitar reabertura em até 30 dias corridos do encerramento, "
            "quando a solucao apresentada não tiver resolvido o problema.",
            "A reabertura mantem o protocolo original e reinicia a contagem do prazo de "
            "resposta. A partir da segunda reabertura, a demanda e automaticamente escalonada.",
        ]),
    ],
)


GUIA_CONTESTACAO = Documento(
    arquivo="guia-contestacao-transacoes.md",
    titulo="Guia de Contestação de Transações",
    categoria="Atendimento",
    descricao="Passo a passo para registrar e acompanhar contestações de lancamentos.",
    formato="md",
    codigo="GUI-CON-011",
    versao="1.9",
    secoes=[
        Secao("1", "Quando usar este guia", [
            "Use este guia quando o cliente discordar de um lancamento em conta ou fatura, "
            "seja por não reconhecer a transação, por divergência de valor ou por cobranca "
            "em duplicidade.",
            "Para transações Pix não reconhecidas, siga tambem o Procedimento Operacional de "
            "Pix (PRO-PIX-007), seção 5, que trata do Mecanismo Especial de Devolução.",
        ]),
        Secao("2", "Prazos para contestar", [
            "Cartão de crédito: 90 dias corridos da data da fatura em que o lancamento "
            "apareceu.",
            "Cartão de débito: 60 dias corridos da data da transação.",
            "Débito automático: 30 dias corridos da data do débito.",
            "Pix: 80 dias corridos, conforme PRO-PIX-007, seção 4.2.",
            "Contestações fora do prazo são registradas, mas o cliente deve ser informado de "
            "que a analise pode ser prejudicada pela indisponibilidade de comprovantes junto "
            "ao estabelecimento.",
        ]),
        Secao("3", "Informações obrigatórias no registro", [
            "Data e valor exatos da transação contestada.",
            "Nome do estabelecimento como aparece no extrato.",
            "Motivo da contestação, nas palavras do cliente.",
            "Se o cartão esta em posse do cliente ou foi perdido ou furtado.",
            "Se o cliente reconhece outras transações do mesmo estabelecimento.",
        ]),
        Secao("4", "Procedimento", [
            "Passo 1 — Confirmar a identidade do cliente conforme MAN-CAD-001, seção 3.2, "
            "etapa 1.",
            "Passo 2 — Localizar a transação no extrato e ler os dados em voz alta para "
            "confirmação.",
            "Passo 3 — Registrar a contestação na transação CON-REG, preenchendo todos os "
            "campos da seção 3 deste guia.",
            "Passo 4 — Quando houver suspeita de fraude, bloquear o cartão imediatamente e "
            "providenciar segunda via.",
            "Passo 5 — Informar ao cliente o protocolo e o prazo de resposta previsto no "
            "MAN-Até-002, seção 2.3.",
        ]),
        Secao("5", "Crédito provisorio", [
            "O crédito provisorio é concedido automaticamente em contestações de cartão de "
            "crédito com valor de até R$ 3.000,00, quando o cliente não possui contestação "
            "negada nos últimos 12 meses.",
            "O crédito aparece em até 2 dias úteis e é revertido caso a analise conclua pela "
            "improcedencia da contestação. A reversão é comunicada ao cliente com 5 dias "
            "úteis de antecedencia.",
        ]),
        Secao("6", "Resultado da analise", [
            "Procedente: o valor e estornado em definitivo e o cliente comunicado pelo canal "
            "de preferencia cadastrado.",
            "Improcedente: o crédito provisorio, se houver, é revertido. O cliente recebe a "
            "justificativa e pode solicitar reabertura conforme MAN-Até-002, seção 5.",
            "Inconclusiva: quando o estabelecimento não apresenta comprovação no prazo, a "
            "contestação é decidida em favor do cliente.",
        ]),
    ],
)


PROCEDIMENTO_ENCERRAMENTO = Documento(
    arquivo="procedimento-encerramento-conta.md",
    titulo="Procedimento de Encerramento de Conta",
    categoria="Cadastro",
    descricao="Requisitos, etapas e prazos para encerramento de conta corrente e poupanca.",
    formato="md",
    codigo="PRO-ENC-002",
    versao="2.3",
    secoes=[
        Secao("1", "Direito ao encerramento", [
            "O cliente pode solicitar o encerramento da conta a qualquer momento, por "
            "qualquer canal, sem necessidade de justificativa.",
            "Não é permitido condicionar o encerramento a contratação de produto, a "
            "comparecimento a agência quando o pedido foi feito por canal digital, ou a "
            "atendimento de retenção. A tentativa de retenção pode ser oferecida uma única "
            "vez e, recusada, não deve ser repetida.",
        ]),
        Secao("2", "Requisitos previos", [
            "Saldo devedor quitado, incluindo tarifas e juros do período.",
            "Saldo credor transferido ou sacado pelo cliente.",
            "Cancelamento de débitos automaticos vinculados a conta.",
            "Devolução ou inutilização das folhas de cheque não utilizadas, quando houver.",
            "Encerramento ou portabilidade de investimentos vinculados.",
        ]),
        Secao("3", "Etapas", [
            "Etapa 1 — Confirmar a identidade do cliente e a titularidade da conta. Em conta "
            "conjunta, o encerramento exige manifestação de todos os titulares.",
            "Etapa 2 — Verificar os requisitos da seção 2 e informar ao cliente o que ainda "
            "precisa ser resolvido.",
            "Etapa 3 — Registrar o pedido na transação CTA-ENC e entregar o comprovante com "
            "o número do protocolo.",
            "Etapa 4 — Informar que a conta entra em estado de encerramento em andamento, no "
            "qual não aceita novos creditos, e que o prazo de conclusão é de até 30 dias "
            "corridos.",
            "Etapa 5 — Ao final do prazo, o sistema emite o termo de encerramento, "
            "disponibilizado no aplicativo e enviado ao e-mail cadastrado.",
        ]),
        Secao("4", "Creditos recebidos após o pedido", [
            "Creditos recebidos durante o período de encerramento em andamento são devolvidos "
            "a origem. O cliente deve ser orientado a informar a nova conta a fontes "
            "pagadoras antes de solicitar o encerramento.",
            "Creditos de origem trabalhista ou previdenciária exigem tratamento especifico e "
            "devem ser escalonados conforme MAN-Até-002, seção 4.",
        ]),
        Secao("5", "Encerramento por iniciativa da instituição", [
            "A instituição pode encerrar o relacionamento mediante comunicação prévia de 30 "
            "dias corridos, sem obrigacao de justificar.",
            "Quando o encerramento decorre de razoes de conformidade, aplica-se a vedação a "
            "comunicação prevista na POL-PLD-004, seção 5.2: o atendente não informa o motivo "
            "ao cliente.",
        ]),
    ],
)


GLOSSARIO = Documento(
    arquivo="glossario-termos-e-siglas.txt",
    titulo="Glossario de Termos e Siglas",
    categoria="Referência",
    descricao="Definicoes de siglas, códigos de transação e termos usados nos manuais.",
    formato="txt",
    codigo="GLO-REF-001",
    versao="5.4",
    secoes=[
        Secao("1", "Siglas", [
            "CCS — Cadastro de Clientes do Sistema Financeiro Nacional.",
            "CPF — Cadastro de Pessoas Fisicas.",
            "CTPS — Carteira de Trabalho e Previdência Social.",
            "KYC — Know Your Customer, em portugues Conheca Seu Cliente. Ver POL-PLD-004, "
            "seção 2.",
            "MED — Mecanismo Especial de Devolução, aplicavel a transações Pix. Ver "
            "PRO-PIX-007, seção 4.2.",
            "PEP — Pessoa Politicamente Exposta. Ver POL-PLD-004, seção 4.",
            "PLD/FT — Prevenção a Lavagem de Dinheiro e ao Financiamento do Terrorismo.",
            "SLA — Service Level Agreement, o prazo acordado de resposta. Ver MAN-Até-002, "
            "seção 2.",
        ]),
        Secao("2", "Códigos de transação", [
            "Até-ESC — Escalonamento de demanda de atendimento.",
            "CAD-ATU — Atualização cadastral.",
            "CON-REG — Registro de contestação de transação.",
            "CTA-ENC — Pedido de encerramento de conta.",
            "PIX-DEV — Solicitação de devolução de Pix.",
            "PLD-ALE — Registro de situacao de alerta de prevenção.",
        ]),
        Secao("3", "Códigos de alerta em tela", [
            "COD-2041 — Cadastro com atualização vencida ou a vencer em menos de 60 dias.",
            "COD-2055 — Conta em restrição parcial por cadastro desatualizado.",
            "COD-2061 — Conta em restrição total por cadastro desatualizado.",
            "COD-3320 — Cliente classificado como risco alto em PLD.",
            "COD-3325 — Cliente enquadrado como pessoa politicamente exposta.",
            "COD-4102 — Conta em processo de encerramento.",
        ]),
        Secao("4", "Formulários", [
            "FOR-CAD-003 — Coleta de alterações cadastrais.",
            "FOR-CAD-017 — Declaração de residência por terceiro.",
            "FOR-ENC-005 — Termo de encerramento de conta.",
        ]),
        Secao("5", "Termos", [
            "Crédito provisorio — valor creditado ao cliente durante a analise de uma "
            "contestação, sujeito a reversão. Ver GUI-CON-011, seção 5.",
            "Identificação positiva — confirmação da identidade do cliente por dados "
            "cadastrais e perguntas de segurança antes de qualquer operação sensivel.",
            "Restrição parcial — estado da conta que bloqueia crédito, investimento e "
            "transferências acima de R$ 5.000,00 por dia.",
            "Restrição total — estado da conta que permite apenas saque, pagamento de contas "
            "do titular e encerramento.",
        ]),
    ],
)


SEGURANCA_ATENDIMENTO = Documento(
    arquivo="politica-seguranca-no-atendimento.pdf",
    titulo="Politica de Segurança da Informação no Atendimento",
    categoria="Segurança",
    descricao="Identificação do cliente, dados sensiveis é conduta diante de tentativas de fraude.",
    formato="pdf",
    codigo="POL-SEG-009",
    versao="3.5",
    secoes=[
        Secao("1", "Identificação do cliente", [
            "Nenhuma informação de conta e fornecida antes da identificação positiva do "
            "cliente. A regra vale para todos os canais e não admite exceção, inclusive "
            "quando o interlocutor demonstra irritação ou pressa.",
            "Em atendimento telefônico, a identificação exige nome completo, CPF, data de "
            "nascimento e duas perguntas de segurança. Três respostas incorretas encerram o "
            "atendimento e registram alerta COD-3320 quando houver suspeita de tentativa de "
            "acesso indevido.",
        ]),
        Secao("2", "Dados que nunca devem ser solicitados", [
            "O colaborador jamais solicita ao cliente: senha de acesso, senha de cartão, "
            "código de verificação recebido por SMS, código do aplicativo autenticador ou "
            "número completo do cartão com código de segurança.",
            "Se o cliente oferecer espontaneamente qualquer desses dados, o colaborador deve "
            "interrompe-lo, explicar que o banco nunca solicita essas informações e orientar "
            "a troca imediata da senha.",
        ]),
        Secao("3", "Conduta diante de suspeita de fraude", [
            "Ao identificar indício de que o cliente esta sendo vítima de golpe em andamento "
            "— por exemplo, quando relata estar sendo orientado por telefone a transferir "
            "valores —, o atendente deve interromper a operação e alertar o cliente "
            "explicitamente.",
            "O bloqueio preventivo de canais digitais e das chaves Pix é recomendado. O "
            "procedimento de contestação segue o GUI-CON-011.",
        ]),
        Secao("4", "Tratamento de dados pessoais", [
            "O acesso a dados de cliente é permitido apenas durante atendimento ativo e "
            "estritamente na medida necessária. Consultas sem demanda associada são "
            "auditadas e caracterizam falta grave.",
            "E vedado registrar dados sensiveis em campos de texto livre, anotações pessoais, "
            "aplicativos de mensagem ou qualquer meio fora dos sistemas corporativos.",
        ]),
        Secao("5", "Compartilhamento com terceiros", [
            "Informações de conta não são fornecidas a terceiros, ainda que familiares, sem "
            "procuração registrada no sistema.",
            "Pedidos de informação apresentados como sendo de autoridade policial ou judicial "
            "são encaminhados a área jurídica, sem qualquer confirmação ou negativa ao "
            "solicitante.",
        ]),
    ],
)


ACERVO: list[Documento] = [
    MANUAL_CADASTRO,
    PROCEDIMENTO_PIX,
    POLITICA_PLD,
    MANUAL_ATENDIMENTO,
    GUIA_CONTESTACAO,
    PROCEDIMENTO_ENCERRAMENTO,
    GLOSSARIO,
    SEGURANCA_ATENDIMENTO,
]

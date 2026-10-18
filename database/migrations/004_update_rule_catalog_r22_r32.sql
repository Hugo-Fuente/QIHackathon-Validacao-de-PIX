-- Replace historical placeholder labels with the implemented rules and points.
-- R25/R26 use profile medians in ruleset v7.1; monetary thresholds stay in the engine.
UPDATE fraud_rules AS rule
SET name = catalog_update.name,
    default_points = catalog_update.default_points
FROM (VALUES
    ('R22', 'Destino é sócio', 1),
    ('R23', 'Contraparte nova para a responsabilidade', 1),
    ('R24', 'Conta recém-ativada com saída grande', 1),
    ('R25', 'Passagem entrada-saída relativa à mediana', 3),
    ('R26', 'Destinatário em rede relativo à mediana', 3),
    ('R27', 'Sócio de muitas empresas (alerta)', 0),
    ('R30', 'Saída da empresa fora do padrão', 2),
    ('R31', 'Destino ligado a sócio', 2),
    ('R32', 'Credencial trocada seguida de saída', 2)
) AS catalog_update(code, name, default_points)
WHERE rule.code = catalog_update.code;

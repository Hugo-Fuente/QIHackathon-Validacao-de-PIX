CPF_LENGTH = 11

CHECK_DIGIT_POSITIONS = [9, 10]


def is_valid_cpf(document_number: str) -> bool:
    """Valida um CPF pelos dígitos verificadores (não apenas pelo formato).

    Cada dígito verificador é o resto da soma ponderada (pesos decrescentes)
    dos dígitos anteriores por 11: resto < 2 resulta em 0; caso contrário,
    11 - resto.
    """
    digits = []
    for character in document_number:
        if character.isdigit():
            digits.append(int(character))

    if len(digits) != CPF_LENGTH:
        return False

    # Sequências de dígitos iguais passam no cálculo, mas são inválidas.
    all_digits_are_equal = True
    for digit in digits:
        if digit != digits[0]:
            all_digits_are_equal = False
            break

    if all_digits_are_equal:
        return False

    for position in CHECK_DIGIT_POSITIONS:
        total = 0
        first_weight = position + 1

        for index in range(position):
            total = total + digits[index] * (first_weight - index)

        remainder = total % 11

        if remainder < 2:
            expected_digit = 0
        else:
            expected_digit = 11 - remainder

        if digits[position] != expected_digit:
            return False

    return True


CNPJ_LENGTH = 14


def only_digits(value: str) -> str:
    """Remove a máscara ('123.456.789-09' -> '12345678909'); CPF/CNPJ são persistidos só com dígitos."""
    return "".join(character for character in value if character.isdigit())


def is_valid_cnpj(document_number: str) -> bool:
    """Valida um CNPJ pelos dígitos verificadores (pesos cíclicos de 9 a 2)."""
    digits = [int(character) for character in only_digits(document_number)]

    if len(digits) != CNPJ_LENGTH:
        return False

    if len(set(digits)) == 1:
        return False

    for position in (12, 13):
        weights = list(range(position - 7, 1, -1)) + list(range(9, 1, -1))
        weights = weights[:position]
        total = sum(digits[index] * weights[index] for index in range(position))
        remainder = total % 11
        expected_digit = 0 if remainder < 2 else 11 - remainder

        if digits[position] != expected_digit:
            return False

    return True

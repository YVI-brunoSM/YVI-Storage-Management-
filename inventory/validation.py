from decimal import Decimal, InvalidOperation
import re
from flask import request


class ApiError(Exception):
    def __init__(self, code, message, status=422, fields=None):
        self.code, self.message, self.status, self.fields = code, message, status, fields or {}
        super().__init__(message)


def invalid(field, message='Valor inválido.'):
    raise ApiError('VALIDATION_ERROR', 'Revise os campos indicados.', fields={field: message})


def body():
    data = request.get_json()
    if not isinstance(data, dict):
        raise ApiError('INVALID_JSON', 'Envie um objeto JSON válido.')
    return data


def text(data, field, required=False, maximum=200, default=''):
    value = data.get(field, default)
    if value is None and not required:
        value = default
    if not isinstance(value, str):
        invalid(field, 'Informe um texto.')
    value = value.strip()
    if (required and not value) or len(value) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
        invalid(field, f'Informe de {1 if required else 0} a {maximum} caracteres válidos.')
    return value


def integer(value, field, minimum=1, maximum=2147483647):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)):
        invalid(field, 'Informe um número inteiro válido.')
    result = int(value)
    if not minimum <= result <= maximum:
        invalid(field, f'Valor deve estar entre {minimum} e {maximum}.')
    return result


def number(data, field, places=3, minimum=Decimal('0'), default=None):
    value = data.get(field, default)
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)):
        invalid(field, 'Informe um número válido.')
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < minimum or result > Decimal('99999999999'):
            invalid(field, 'Número fora do intervalo permitido.')
        if result != result.quantize(Decimal(1).scaleb(-places)):
            invalid(field, f'Use no máximo {places} casas decimais.')
        return result
    except InvalidOperation:
        invalid(field, 'Informe um número válido.')


def choice(data, field, choices, default=None):
    value = data.get(field, default)
    if not isinstance(value, str) or value not in choices:
        invalid(field, 'Selecione uma opção válida.')
    return value


def boolean(data, field):
    if type(data.get(field)) is not bool:
        invalid(field, 'Informe verdadeiro ou falso.')
    return int(data[field])


def password(data, required=True):
    value = data.get('password', '')
    if not isinstance(value, str):
        invalid('password')
    if not value and not required:
        return None
    if not 12 <= len(value) <= 128:
        invalid('password', 'Use entre 12 e 128 caracteres.')
    return value


def quantity_for_unit(value, unit, field='quantity'):
    if unit not in ('m', 'kg') and value != value.to_integral_value():
        invalid(field, 'Esta unidade de medida exige quantidade inteira.')


def page():
    return integer(request.args.get('page', '1'), 'page', maximum=100000), integer(request.args.get('limit', '50'), 'limit', maximum=100)

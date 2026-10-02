from copy import deepcopy
from pathlib import Path

import pytest
from flask import Flask

from inventory.mail_worker import render_message, stock_quantity


def example_row():
    return {'id': 42, 'kind': 'stock', 'recipient': 'admin@example.test', 'payload': {
        'at': '2026-10-01T12:22:00+00:00', 'state': 'low', 'name': 'ROLDANA 30cm',
        'code': '1', 'category': 'Roldanas', 'location': 'Quadramares', 'unit': 'un',
        'before': '1002.000', 'stock': '1000.000', 'minimum': '10000.000',
        'operation': 'Saída', 'quantity': '2.000', 'branch': 'LETS VIBE BESSA',
        'actor': 'Bruno Machado', 'notes': ''}}


def message(row):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
    app.config.update(APP_BASE_URL='https://inventory.example.test', EMAIL_REPLY_TO='owner@example.test')
    with app.app_context():
        return render_message(row, 'sender@example.test')


def test_stock_email_separates_current_stock_from_movement_and_localizes_values():
    row = example_row()
    original = deepcopy(row)
    msg = message(row)
    assert msg['Subject'] == 'YVI GESTÃO - REPOR ROLDANA 30cm'
    text = msg.get_body(preferencelist=('plain',)).get_content()
    assert 'Estoque mínimo: 10.000 un' in text
    assert 'ESTOQUE ATUAL: 1.000 un' in text
    assert 'Quantidade movimentada: 2 un' in text
    assert 'Data: 01/10/2026 às 09:22' in text
    assert 'Unidade de destino da movimentação: LETS VIBE BESSA' in text
    assert 'Responsável: Bruno Machado' in text
    assert text.index('DADOS DA PEÇA') < text.index('ESTOQUE ATUAL') < text.index('ÚLTIMA MOVIMENTAÇÃO')
    assert 'Saldo anterior' not in text and '1002' not in text
    html = msg.get_body(preferencelist=('html',)).get_content()
    assert html.index('Dados da peça') < html.index('Estoque Atual') < html.index('Última movimentação')
    assert 'momento deste registro' in html
    assert 'Referência: YVI-42' in html
    assert row == original


def test_out_of_stock_subject_and_html_escaping():
    row = example_row()
    row['payload'].update(state='out', stock='0', name='<script>Peça & peça</script>',
                          notes='<img src=x onerror=alert(1)>', actor='Bruno <teste>')
    msg = message(row)
    assert msg['Subject'].startswith('YVI GESTÃO - ESGOTADO ')
    text = msg.get_body(preferencelist=('plain',)).get_content()
    assert 'ESTOQUE ATUAL: 0 un' in text
    html = msg.get_body(preferencelist=('html',)).get_content()
    assert '<script>' not in html and '<img src=x' not in html
    assert '&lt;script&gt;' in html and '&lt;teste&gt;' in html


def test_minimum_change_does_not_claim_to_be_a_movement():
    row = example_row()
    row['payload'].pop('quantity')
    row['payload']['operation'] = 'Alteração do mínimo da unidade'
    msg = message(row)
    for kind in ('plain', 'html'):
        content = msg.get_body(preferencelist=(kind,)).get_content()
        assert 'movimentação' not in content.lower()
        assert 'registro que gerou o alerta' in content.lower()
        assert 'Quantidade movimentada' not in content


def test_transfer_does_not_label_the_alerted_source_as_the_destination():
    row = example_row()
    row['payload'].update(operation='Transferência · Saída', location='Quadramares', branch='Quadramares')
    text = message(row).get_body(preferencelist=('plain',)).get_content()
    assert 'Unidade da movimentação: Quadramares' in text
    assert 'Unidade de destino da movimentação' not in text


@pytest.mark.parametrize('value,unit,expected', [
    ('10000.000', 'un', '10.000 un'), ('1000.000', 'un', '1.000 un'),
    ('2.000', 'un', '2 un'), ('1234.500', 'm', '1.234,5 m'),
    ('0.001', 'kg', '0,001 kg'), ('0.000', 'un', '0 un')])
def test_quantity_format_is_unambiguous(value, unit, expected):
    assert stock_quantity(value, unit) == expected

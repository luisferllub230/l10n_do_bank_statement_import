import logging
from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BANK_ENTITY = "BPD"

class AccountBanckStatementImportBpd(models.TransientModel):
    _inherit = 'account.bank.statement.import'
    
    def _parse_lines_csv(self, data_file, bank_entity, currency_code, currency_symbol):
        if not self._check_bank_entity(BANK_ENTITY, bank_entity):
            return super(AccountBanckStatementImportBpd, self)._parse_lines_csv(data_file, bank_entity, currency_code, currency_symbol)
        
        # TODO: we need to find a way to parametrize the header for no harcode it
        header_expected = ['Fecha Posteo','Descripción Corta','Monto Transacción','No. Referencia','No. Serial','Descripción']
        date_header_index = 0
        short_description_header_index = 1
        ammount_header_index = 2
        ref_header_index = 3
        serial_header_index = 4
        description_header_index = 5
        
        csv_options = {}
        csv_options['delimiter'] = ','
        csv_options['quotechar'] = '"'
        
        csv = self._get_csv_iterator(data_file, csv_options)
        header_index = self._find_headers_position_in_csv(csv_file=csv, header=header_expected)
        
        csv = self._get_csv_iterator(data_file, csv_options)
        bodys = self._find_body_in_csv(csv_file=csv, headers_position=header_index, header=header_expected)

        if not bodys:
            raise UserError(_("There are no data in the file."))
        
        data = []
        faild_lines = []
        journal_id = self.env["account.journal"].browse(self.env.context.get("journal_id", 0))
        is_credict_card = journal_id.l10n_do_invert_ammounts
        for i, body in enumerate(bodys):
            try:
                _description = body[description_header_index]
                _is_credit_or_debit = body[short_description_header_index]
                _ref = body[ref_header_index]
                _debit = ""
                _credict = ""
                _ammount = ""
                _date = body[date_header_index]
                _serial = body[serial_header_index]

                if "CR" in _is_credit_or_debit or "Crédito" in _is_credit_or_debit:
                    _credict = body[ammount_header_index]
                    _ammount = str(_credict.replace(currency_symbol, '').replace(',','').replace('-', ''))
                    _ammount = '-' + _ammount if is_credict_card else _ammount
                elif "DB" in _is_credit_or_debit or "Débito" in _is_credit_or_debit:
                    _debit = body[ammount_header_index]
                    _ammount = str(_debit.replace(currency_symbol, '').replace(',','').replace('-', ''))
                    _ammount = _ammount if is_credict_card else '-' + _ammount
                
                # para los casos en que el banco no envie el tipo de transaccion en la descripcion corta.
                # en estos casos se dan cuano hay mas de una transaccion con la misma fecha y tipo.
                if _ammount == '':
                    if "CR" in bodys[i-1][short_description_header_index]  or "Crédito" in bodys[i-1][short_description_header_index]:
                        _credict = body[ammount_header_index]
                        _ammount = str(_credict.replace(currency_symbol, '').replace(',','').replace('-', ''))
                        _ammount = '-' + _ammount if is_credict_card else _ammount
                    elif "DB" in bodys[i-1][short_description_header_index] or "Débito" in bodys[i-1][short_description_header_index]:
                        _debit = body[ammount_header_index]
                        _ammount = str(_debit.replace(currency_symbol, '').replace(',','').replace('-', ''))
                        _ammount = _ammount if is_credict_card else '-' + _ammount

                _date = body[date_header_index]
                if not self._check_is_valid_date(_date, expected_format='%d/%m/%Y'):
                    if not self.statement_year:
                        raise UserError(_("Dont have the year of the statement"))
                    _date = body[date_header_index] + f'/{self.statement_year}'
                
                _date = self._formated_date(_date, current_format='%d/%m/%Y')
                _unique_import_id = "%s-%s-%s-%s-%s-%s-%s" % (BANK_ENTITY, _date, _ref, _ammount, _is_credit_or_debit, _serial, i)
                data.append({
                    'date': _date,
                    'payment_ref': _description,
                    'amount': float(_ammount),
                    'unique_import_id': _unique_import_id,
                    'sequence': i + 1,
                })
            except Exception as e:
                _logger.error(e)
                faild_lines.append({
                        'date': _date,
                        'payment_ref': body[short_description_header_index],
                        'amount': body[ammount_header_index],
                        'serial': body[serial_header_index],
                        'description': body[description_header_index],
                    })
                continue
        return faild_lines, data
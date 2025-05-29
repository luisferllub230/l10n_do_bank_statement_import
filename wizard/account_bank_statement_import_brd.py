import logging
from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BANK_ENTITY = "BRD"

class AccountBankStatementImportBhd(models.TransientModel):

    _inherit = "account.bank.statement.import"

    def _parse_lines_csv(self, data_file, bank_entity, currency_code, currency_symbol):
        if not self._check_bank_entity(BANK_ENTITY, bank_entity):
            return super(AccountBankStatementImportBhd, self)._parse_lines_csv(data_file, bank_entity, currency_code, currency_symbol)
        
        # TODO: we need to find a way to parametrize the header for no harcode it
        header_expected = ['Producto', 'Fecha', 'Concepto', 'Id de transacción', 'Débito', 'Crédito', 'Balance', 'Descripción', 'Referencia', '']
        
        product_index = 0
        date_index = 1
        concept_index = 2
        transaction_id_index = 3
        debit_index = 4
        credit_index = 5
        balance_index = 6
        description_index = 7
        reference_index = 8
        
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
                _description = body[description_index]
                _debit = body[debit_index]
                _credict = body[credit_index]
                _ref = body[reference_index]
                _date = body[date_index]
                _serial = body[transaction_id_index]
                _ammount = ""
                    
                if _credict != '' and _credict != '0.00':
                    _ammount = str(_credict.replace(currency_symbol, '').replace(',','').replace('-', ''))
                    _ammount = '-' + _ammount if is_credict_card else _ammount

                if _debit != '' and _debit != '0.00':
                    _ammount = str(_debit.replace(currency_symbol, '').replace(',','').replace('-', ''))
                    _ammount = _ammount if is_credict_card else '-' + _ammount
                
                if _ammount == "":
                    _ammount = '0'
                    raise UserError(_("The ammount %s is not valid.") % _ammount)
                
                if not self._check_is_valid_date(_date, expected_format='%d/%m/%Y'):
                    raise UserError(_("The date %s is not valid.") % _date)
                
                _date = self._formated_date(_date, current_format='%d/%m/%Y')
                
                _unique_import_id = '%s-%s-%s-%s-%s-%s' % (BANK_ENTITY, _date, _ref, _ammount, _serial, i)

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
                        'payment_ref': body[concept_index],
                        'amount': _ammount,
                        'serial': body[reference_index],
                        'description': body[description_index],
                    })
                continue
        return faild_lines, data
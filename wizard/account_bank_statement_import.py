import re
import base64
import chardet
from csv import reader
from io import StringIO
from datetime import datetime, date
from odoo import models, fields, tools, _
from odoo.addons.base.models.res_bank import sanitize_account_number
from odoo.exceptions import UserError, RedirectWarning

import logging
_logger = logging.getLogger(__name__)

DATE_FORMAT = '%Y-%m-%d'

class AccountBankStatementImport(models.TransientModel):
    
    _name = 'account.bank.statement.import'
    _description = 'Bank Statement Import Wizard'

    def year_selection(self):
        current_year = datetime.today().year
        year_list = [(str(year), str(year)) for year in range(current_year - 2, current_year + 11)]
        return year_list

    statement_year = fields.Selection(
        selection=year_selection,
        string=_('Statement year'),
    )

    is_for_credit_card = fields.Boolean(
        string=_('Is a credit card?'),
        default=False,
        help=_('Mark if this journaal is for a credit card, this option will invert the ammounts the credit passed to the debit and vice versa'),
    )

    attachment_ids = fields.Many2many(
        'ir.attachment',
        string=_('Attachments'),
    )
    
    def import_bank_statement(self):
        """ Process the file chosen in the wizard, create bank statement(s) and go to reconciliation. """
        
        attachments = self.attachment_ids

        if any(not a.raw for a in attachments):
            raise UserError(_("You uploaded an invalid or empty file."))
        
        if not attachments:
            raise UserError(_("You have to upload a file."))

        statement_ids_all = []
        faild_stmts_vals_all = []
        notifications_all = {}
        errors = {}

        faild_statements_id = self.env['account.bank.statement.faild.import'].sudo().create({'journal_id': self.env.context.get('journal_id')})

        if not self._check_is_only_one_statements_type():
            raise UserError(_('You have to upload only one statement type'))
        
        for attachment in attachments:
            try:
                journal = self.env['account.journal'].browse(self.env.context.get('journal_id'))
                currency_code, account_number, faild_stmts_vals, stmts_vals = self._parse_file(attachment)
                self._check_parsed_data(stmts_vals, account_number)

                if not journal.default_account_id:
                    raise UserError(_('You have to set a Default Account for the journal: %s') % (journal.name,))
                
                stmts_vals = self._complete_bank_statement_vals(stmts_vals, journal, account_number, attachment)
                statement_ids, dummy, notifications = self._create_bank_statements(stmts_vals, journal)
                statement_ids_all.extend(statement_ids)
                faild_statmts_lines_ids = self._create_faild_statements_lines(faild_stmts_vals, journal, statement_ids, faild_statements_id)
                faild_stmts_vals_all.extend(faild_statmts_lines_ids)

                msg = ""
                for notif in notifications:
                    msg += (
                        f"{notif['message']}"
                    )
                if notifications:
                    notifications_all[attachment.name] = msg
                if len(faild_stmts_vals) > 0:
                    count_lines = len(faild_stmts_vals[0]['transactions'])
                    notifications_all[attachment.name] = _("We could not import some lines please check and import manually the remaining lines %s lines", count_lines)
            except (UserError, RedirectWarning) as e:
                errors[attachment.name] = e.args[0]

        statements = self.env['account.bank.statement'].browse(statement_ids_all)
        line_to_reconcile = statements.line_ids
        if line_to_reconcile:
            cron_limit_time = tools.config['limit_time_real_cron']  # default is -1
            limit_time = cron_limit_time if 0 < cron_limit_time < 180 else 180
            line_to_reconcile._cron_try_auto_reconcile_statement_lines(limit_time=limit_time)

        result = self.env['account.bank.statement.line']._action_open_bank_reconciliation_widget(
            extra_domain=[('statement_id', 'in', statements.ids)],
            default_context={
                'search_default_not_matched': True,
                'default_journal_id': statements[:1].journal_id.id,
                'notifications': notifications_all,
            },
        )

        if faild_stmts_vals_all:
            self.env.cr.commit()
            return faild_statements_id.action_open_faild_statements_wizard(faild_statements_id.id)

        if errors:
            error_msg = _("The following files could not be imported:\n")
            error_msg += "\n".join([f"- {attachment_name}: {msg}" for attachment_name, msg in errors.items()])
            if statements:
                self.env.cr.commit()  # save the correctly uploaded statements to the db before raising the errors
                raise RedirectWarning(error_msg, result, _('View successfully imported statements'))
            else:
                raise UserError(error_msg)
        return result
    
    def _check_parsed_data(self, stmts_vals, account_number):
        """ Basic and structural verifications """
        extra_msg = _('If it contains transactions for more than one account, it must be imported on each of them.')
        if len(stmts_vals) == 0:
            raise UserError(
                _('This file doesn\'t contain any statement for account %s.') % (account_number,)
                + '\n' + extra_msg
            )

        no_st_line = True
        for vals in stmts_vals:
            if vals['transactions'] and len(vals['transactions']) > 0:
                no_st_line = False
                break
        if no_st_line:
            raise UserError(
                _('This file doesn\'t contain any transaction for account %s.') % (account_number,)
                + '\n' + extra_msg
            )
    
    def _check_is_only_one_statements_type(self):
        """
        Check if there is only one statement type in attachments. return True if there is only one statement type else False
        """
        fieldnames = set([att.name.split('.')[-1] for att in self.attachment_ids])
        if len(fieldnames) > 1:
            return False
        return True

    def _check_file_type(self, filename, type_expected):
        """
        Check file type. return True if file type is correct else False
        """
        if not filename or not filename.lower().strip().endswith(type_expected.lower()):
            return False
        return True

    def _check_bank_entity(self, bank_entity, bank_expected):
        """
        Check bank entity. return True if bank entity is correct else False
        """
        if bank_entity != bank_expected:
            return False
        return True
    
    def _check_is_valid_date(self, date_str, expected_format=''):
        """
        Method to validate date. return True if date is valid else False
        """
        try:
            datetime.strptime(date_str, expected_format)
        except ValueError:
            return False
        return True

    def _parse_file(self, attachment):
        data_file = base64.b64decode(attachment.datas)
        filename = attachment.name
        journal_id = self.env["account.journal"].browse(self.env.context.get("journal_id", 0))
        import_type = journal_id.l10n_do_statement_file_type
        bank_entity = journal_id.l10n_do_bank
        
        if not self._check_file_type(filename, import_type):
            raise UserError(_("You must select a file with the correct type or change the file import statement type in the journal."))
        
        statement_name = f"{bank_entity} {str(date.today().strftime('%Y-%m-%d'))} Bank Statement"
        currency_code = (journal_id.currency_id or journal_id.company_id.currency_id).name
        currency_symbol = (journal_id.currency_id or journal_id.company_id.currency_id).symbol
        account_number = journal_id.bank_account_id.acc_number

        if import_type == 'CSV':
            faild_lines, lines = self.with_context(journal_id=journal_id.id)._parse_lines_csv(
                data_file=data_file, 
                bank_entity=bank_entity, 
                currency_code=currency_code, 
                currency_symbol=currency_symbol,
            )

        faild_stmts_vals = [{
            'name': statement_name,
            'transactions': faild_lines,
        }]
        
        if not faild_lines:
            faild_stmts_vals = []

        if not lines:
            return currency_code, account_number, faild_stmts_vals, [{
                'name': statement_name,
                'transactions': [],
            }]
        
        lines = list(sorted(lines, key=lambda line: line['date']))
        stmts_vals = [{
            'name': statement_name,
            'transactions': lines,
        }]

        return currency_code, account_number, faild_stmts_vals, stmts_vals

    def _parse_lines_csv(self, data_file,  bank_entity, currency_code, currency_symbol):
        """
        Generic method to parse lines from CSV file. Extend to parse lines from csv statements
        """
        pass
    
    def _get_encode_data_file(self, data_file, encoding='utf-8'):
        """
        Method to encode data_file. return a file encode with encoding type pass, use default utf-8
        """
        if not data_file:
            raise UserError(_('No file text passed for encoding'))
        return data_file.encode(encoding)

    def _get_decode_data_file(self, data_file):
        """
        Method to decode data_file. return a tuple with data_file decode[0] and decode[1]
        """
        if not data_file:
            raise UserError(_('Not file to decode'))
        
        decode = chardet.detect(data_file)['encoding']
        return data_file.decode(decode), decode
        
    def _get_csv_iterator(self, data_file, csv_options={}):
        """
        Method to get a csv iterator. return a csv iterator
        """
        decode_file = self._get_decode_data_file(data_file)[0]
        csv = reader(
            StringIO(decode_file),
            **csv_options
        )
        return csv

    def _normalise_doublequote_csv(self, data_file):
        """
        Method to normalise csv with double quote can't not normalise with the csv reader. return a encode file normalise    
        """
        if not data_file:
            raise UserError(_('Not file to normalise'))

        csv_text, decode = self._get_decode_data_file(data_file)
        lines = csv_text.splitlines()

        pattern = r'""(.*?)""'

        def replace_commas(match):
            inner_text = match.group(1)
            cleaned = inner_text.replace(',', '')
            return cleaned

        normalized_lines = []
        for line in lines:
            line = re.sub(pattern, replace_commas, line)
            line = line.replace('"', '')
            normalized_lines.append(line)

        normalized_text = "\n".join(normalized_lines)
        normalized_bytes = self._get_encode_data_file(normalized_text, decode)

        return normalized_bytes
    
    def _find_headers_position_in_csv(self, csv_file, header=[]):
        """
        Method to find headers position in csv. return a list of integers with the position of the headers finded.
        """
        try:
            header_index = []
            for i, row in enumerate(csv_file):
                if list(row) == header:
                    header_index.append(i)
        except Exception as e:
            _logger.warning(e)
            return header_index
        return header_index
        
    def _find_body_in_csv(self, csv_file, headers_position=[], header=[]):
        """
        Method to find all bodys in csv. return a list of list with the body finded.
        """
        body = []
        for i, row in enumerate(csv_file):
            try:
                if i in headers_position or len(list(row)) != len(header):
                    continue
                body.append(list(row))
            except Exception as e:
                _logger.warning(e)
                continue
        return body
        
    def _formated_date(self, date_str, current_format='%d/%m/%Y'):
        """
        Method to format date. return date if date is valid else False
        """
        try:
            date_obj = datetime.strptime(date_str, current_format)
            formatted_date = date_obj.strftime(DATE_FORMAT)
            return formatted_date
        except ValueError:
            return False
    
    def _complete_bank_statement_vals(self, stmts_vals, journal, account_number, attachment):
        for st_vals in stmts_vals:
            if not st_vals.get('reference'):
                st_vals['reference'] = attachment.name
            for line_vals in st_vals['transactions']:
                line_vals['journal_id'] = journal.id
                unique_import_id = line_vals.get('unique_import_id')
                if unique_import_id:
                    sanitized_account_number = sanitize_account_number(account_number)
                    line_vals['unique_import_id'] = (sanitized_account_number and sanitized_account_number + '-' or '') + str(journal.id) + '-' + unique_import_id

                # if not line_vals.get('partner_bank_id'):
                #     identifying_string = line_vals.get('account_number')
                #     if identifying_string:
                #         if line_vals.get('partner_id'):
                #             partner_bank = self.env['res.partner.bank'].search([
                #                 ('acc_number', '=', identifying_string),
                #                 ('partner_id', '=', line_vals['partner_id'])
                #             ])
                #         else:
                #             partner_bank = self.env['res.partner.bank'].search([
                #                 ('acc_number', '=', identifying_string),
                #                 ('company_id', 'in', (False, journal.company_id.id))
                #             ])
                #         if partner_bank and len(partner_bank) == 1:
                #             line_vals['partner_bank_id'] = partner_bank.id
                #             line_vals['partner_id'] = partner_bank.partner_id.id
        return stmts_vals
        
    def _create_bank_statements(self, stmts_vals, journal):
        """ Create new bank statements from imported values, filtering out already imported transactions, and returns data used by the reconciliation widget """
        BankStatement = self.env['account.bank.statement']
        BankStatementLine = self.env['account.bank.statement.line']

        # Filter out already imported transactions and create statements
        statement_ids = []
        statement_line_ids = []
        ignored_statement_lines_import_ids = []
        for st_vals in stmts_vals:
            filtered_st_lines = []
            for line_vals in st_vals['transactions']:
                if (line_vals['amount'] != 0
                   and ('unique_import_id' not in line_vals
                   or not line_vals['unique_import_id']
                   or not bool(BankStatementLine.sudo().search([('unique_import_id', '=', line_vals['unique_import_id'])], limit=1)))):
                    filtered_st_lines.append(line_vals)
                else:
                    ignored_statement_lines_import_ids.append(line_vals['unique_import_id'])
                    if st_vals.get('balance_start') is not None:
                        st_vals['balance_start'] += float(line_vals['amount'])

            if len(filtered_st_lines) > 0:
                # Remove values that won't be used to create records
                st_vals.pop('transactions', None)
                # Create the statement
                st_vals['line_ids'] = [[0, False, line] for line in filtered_st_lines]
                statement = BankStatement.with_context(default_journal_id=journal.id).create(st_vals)
                if not statement.name:
                    statement.name = st_vals['reference']
                statement_ids.append(statement.id)
                statement_line_ids.extend(statement.line_ids.ids)

                # Create the report.
                if statement.is_complete:
                    statement.action_generate_attachment()

        if len(statement_line_ids) == 0:
            raise UserError(_('You already have imported that file.'))

        notifications = []
        num_ignored = len(ignored_statement_lines_import_ids)
        if num_ignored > 0:
            notifications += [{
                'type': 'warning',
                'message': _("%d transactions had already been imported and were ignored.", num_ignored)
                           if num_ignored > 1
                           else _("1 transaction had already been imported and was ignored."),
            }]
        return statement_ids, statement_line_ids, notifications
    
    def _create_faild_statements_lines(self, faild_stmts_vals_all, journal, statement_ids, faild_statements_id):
        """
        Create a new Account Bank Failed Statement Import Lines from imported values. Returns a list of faild statement lines
        """
        lines = []
        faild_statement_lines = []
        for statement in statement_ids:
            for faild_stmt_vals in faild_stmts_vals_all:
                transactions = faild_stmt_vals.get('transactions')
                for transaction in transactions:
                    _is_valid_date = self._check_is_valid_date(transaction.get('date'), DATE_FORMAT) 
                    lines.append({
                        'statement_import_id': self.id,
                        'statement_faild_id': faild_statements_id.id,
                        'journal_id': journal.id,
                        'statement_id': statement,
                        'date': transaction.get('date') if _is_valid_date else False,
                        'payment_ref': transaction.get('payment_ref'),
                        'amount': transaction.get('amount', '0').replace(',', '').replace(' ', ''),
                        'unique_import_id': transaction.get('unique_import_id'),
                        'type_transaction': 'none',
                        'is_for_credit_card': journal.l10n_do_invert_ammounts,
                    })
            faild_statements_id.line_ids = [[0, False, line] for line in lines]
            faild_statement_lines.extend(faild_statements_id.line_ids.ids)
        return faild_statement_lines